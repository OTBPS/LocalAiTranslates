"""Warm-up runs once per backend, not once per readiness tick.

Found by running the real GUI against a real host: the 15-second readiness
tick was re-warming every time, which locally is a cheap no-op but remotely
became an HTTP round trip and a host log line every 15 seconds.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from screen_translator.controller import Controller
from screen_translator.core import Cancelled, Config


def state(ready=True, warmup=None):
    return SimpleNamespace(
        config=Config(source_language="en"),
        backend=SimpleNamespace(ready=lambda: ready, refresh=Mock()),
        ocr=SimpleNamespace(warmup=warmup or Mock()),
        tasks=SimpleNamespace(start=lambda target, name: target()),
        ocr_warmup_token=None,
        readiness_token=None,
        warmup_completed=False,
    )


def test_repeated_ticks_warm_up_only_once():
    context = state()

    for _ in range(5):
        Controller.schedule_ocr_warmup(context)

    assert context.ocr.warmup.call_count == 1
    assert context.warmup_completed is True


def test_a_failed_warm_up_is_retried_on_the_next_tick():
    attempts = []

    def failing(source_language, token, progress):
        attempts.append(source_language)
        if len(attempts) < 3:
            raise RuntimeError("远程主机不可用")

    context = state(warmup=failing)

    for _ in range(5):
        Controller.schedule_ocr_warmup(context)

    # Retries until it succeeds, then stops.
    assert len(attempts) == 3
    assert context.warmup_completed is True


def test_a_cancelled_warm_up_does_not_count_as_completed():
    def cancelled(source_language, token, progress):
        raise Cancelled()

    context = state(warmup=cancelled)

    Controller.schedule_ocr_warmup(context)

    assert context.warmup_completed is False


def test_nothing_is_warmed_while_the_backend_is_not_ready():
    context = state(ready=False)

    Controller.schedule_ocr_warmup(context)

    context.ocr.warmup.assert_not_called()
    assert context.warmup_completed is False


def test_the_readiness_tick_refreshes_and_warms():
    context = state()
    context.refresh_readiness = lambda: Controller.refresh_readiness(context)
    context.schedule_ocr_warmup = lambda: Controller.schedule_ocr_warmup(context)

    Controller.on_readiness_tick(context)

    context.backend.refresh.assert_called_once()
    assert context.ocr.warmup.call_count == 1

    Controller.on_readiness_tick(context)

    # Readiness keeps being polled; warm-up does not repeat.
    assert context.backend.refresh.call_count == 2
    assert context.ocr.warmup.call_count == 1


def test_replacing_the_backend_allows_warming_the_new_one():
    context = state()
    Controller.schedule_ocr_warmup(context)
    assert context.warmup_completed is True

    context.manual = Mock()
    context.tray = Mock()
    context._backend_factory = lambda _config: SimpleNamespace(
        ready=lambda: True, refresh=Mock(), ocr=SimpleNamespace(warmup=Mock())
    )
    context.apply_host_service = Mock()
    context.schedule_ocr_warmup = Mock()
    context.backend = SimpleNamespace(
        ready=lambda: True, refresh=Mock(), stop=Mock(), ocr=SimpleNamespace(warmup=Mock())
    )

    Controller.replace_engines(context)

    assert context.warmup_completed is False
    context.schedule_ocr_warmup.assert_called_once()
