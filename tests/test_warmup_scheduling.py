"""Warm-up runs once per backend, not once per readiness tick.

Found by running the real GUI against a real host: the 15-second readiness
tick was re-warming every time, which locally is a cheap no-op but remotely
became an HTTP round trip and a host log line every 15 seconds.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from screen_translator.backend_service import BackendService
from screen_translator.core import Cancelled, Config


def service(ready=True, warmup=None, config=None):
    backend = SimpleNamespace(
        ready=lambda: ready,
        refresh=Mock(),
        stop=Mock(),
        kind="local",
        ocr=SimpleNamespace(warmup=warmup or Mock()),
        translator=SimpleNamespace(),
    )
    subject = BackendService(
        factory=lambda _config: backend,
        config_provider=lambda: config or Config(source_language="en"),
        tasks=SimpleNamespace(start=lambda target, name: target()),
        notices=Mock(),
    )
    return subject, backend


def test_repeated_ticks_warm_up_only_once():
    subject, backend = service()

    for _ in range(5):
        subject.warm_up()

    assert backend.ocr.warmup.call_count == 1
    assert subject.warmed is True


def test_a_failed_warm_up_is_retried_on_the_next_tick():
    attempts = []

    def failing(source_language, token, progress):
        attempts.append(source_language)
        if len(attempts) < 3:
            raise RuntimeError("远程主机不可用")

    subject, _backend = service(warmup=failing)

    for _ in range(5):
        subject.warm_up()

    # Retries until it succeeds, then stops.
    assert len(attempts) == 3
    assert subject.warmed is True


def test_a_cancelled_warm_up_does_not_count_as_completed():
    def cancelled(source_language, token, progress):
        raise Cancelled()

    subject, _backend = service(warmup=cancelled)

    subject.warm_up()

    assert subject.warmed is False


def test_nothing_is_warmed_while_the_backend_is_not_ready():
    subject, backend = service(ready=False)

    subject.warm_up()

    backend.ocr.warmup.assert_not_called()
    assert subject.warmed is False


def test_the_readiness_tick_refreshes_and_warms():
    subject, backend = service()

    subject.poll()

    backend.refresh.assert_called_once()
    assert backend.ocr.warmup.call_count == 1

    subject.poll()

    # Readiness keeps being polled; warm-up does not repeat.
    assert backend.refresh.call_count == 2
    assert backend.ocr.warmup.call_count == 1


def test_replacing_the_backend_allows_warming_the_new_one():
    warmups = []

    def make(_config):
        warmup = Mock()
        warmups.append(warmup)
        return SimpleNamespace(
            ready=lambda: True,
            refresh=Mock(),
            stop=Mock(),
            kind="local",
            ocr=SimpleNamespace(warmup=warmup),
            translator=SimpleNamespace(),
        )

    subject = BackendService(
        factory=make,
        config_provider=Config,
        tasks=SimpleNamespace(start=lambda target, name: target()),
        notices=Mock(),
    )
    subject.warm_up()
    assert subject.warmed is True

    subject.replace()

    # New weights, new warm-up -- the flag belongs to the backend, not the
    # process.
    assert len(warmups) == 2
    warmups[1].assert_called_once()
    assert subject.warmed is True


def test_changing_the_source_language_makes_the_engine_cold_again():
    subject, backend = service()
    subject.warm_up()

    subject.reset_warmup()

    # OCR weights are per-language; a warm English engine is no use for
    # Japanese.
    assert subject.warmed is False
    subject.warm_up()
    assert backend.ocr.warmup.call_count == 2


def test_a_readiness_refresh_already_running_is_not_started_twice():
    started = []
    backend = SimpleNamespace(
        ready=lambda: True,
        refresh=Mock(),
        stop=Mock(),
        kind="local",
        ocr=SimpleNamespace(warmup=Mock()),
        translator=SimpleNamespace(),
    )
    subject = BackendService(
        factory=lambda _config: backend,
        config_provider=Config,
        # Never runs the work, so the token stays outstanding.
        tasks=SimpleNamespace(start=lambda target, name: started.append(name)),
        notices=Mock(),
    )

    subject.refresh_readiness()
    subject.refresh_readiness()

    assert started == ["backend-readiness"]
