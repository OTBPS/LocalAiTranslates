"""Switching backends must not leave the application without a working one.

These used to call unbound `Controller` methods on a namespace pretending
to be `self`. `BackendService` is a real object with no window behind it,
so they construct one.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from screen_translator.backend_service import BackendService
from screen_translator.core import Config


class FakeBackend:
    def __init__(self, kind="local", ready=True):
        self.kind = kind
        self.stopped = False
        self._ready = ready
        self.refreshed = 0
        self.ocr = SimpleNamespace(mode="CUDA", warmup=Mock())
        self.translator = SimpleNamespace(mode="CUDA")

    def ready(self):
        return self._ready

    def refresh(self):
        self.refreshed += 1

    def describe(self):
        return self.kind

    def stop(self):
        self.stopped = True


def service(factory, *, config=None, notices=None, stop_work=None):
    """A service whose background work runs inline, so tests stay ordered."""
    return BackendService(
        factory=factory,
        config_provider=lambda: config or Config(),
        tasks=SimpleNamespace(start=lambda target, name: target()),
        notices=notices or Mock(),
        stop_work=stop_work or Mock(),
    )


def test_a_successful_switch_stops_only_the_previous_backend():
    previous = FakeBackend("local")
    replacement = FakeBackend("remote")
    backends = iter([previous, replacement])
    subject = service(lambda _config: next(backends))
    changed = Mock()
    subject.changed.connect(changed)

    assert subject.replace() is True

    assert subject.backend is replacement
    assert previous.stopped is True
    assert replacement.stopped is False
    changed.assert_called_once()


def test_a_failed_switch_keeps_the_working_backend_alive():
    previous = FakeBackend("remote")
    built = [previous]

    def factory(_config):
        if built:
            return built.pop()
        raise ValueError("远程模式需要填写主机地址")

    notices = Mock()
    subject = service(factory, notices=notices)
    changed = Mock()
    subject.changed.connect(changed)

    assert subject.replace() is False

    assert subject.backend is previous
    assert previous.stopped is False, "a closed session cannot be reused"
    notice = notices.post.call_args.args[0]
    assert "远程模式需要填写主机地址" in notice.detail
    # The message says where to fix it, rather than only what broke.
    assert notice.actionable
    changed.assert_not_called()


def test_a_failed_switch_still_cancels_in_flight_manual_work():
    built = [FakeBackend()]
    stop_work = Mock()
    subject = service(
        lambda _config: built.pop() if built else (_ for _ in ()).throw(ValueError("boom")),
        stop_work=stop_work,
    )
    stop_work.reset_mock()

    subject.replace()

    # In-flight work holds the engines being replaced.
    stop_work.assert_called_once()


@pytest.mark.parametrize("kind", ["local", "remote"])
def test_the_engine_properties_follow_the_current_backend(kind):
    backend = FakeBackend(kind)
    subject = service(lambda _config: backend)

    assert subject.ocr is backend.ocr
    assert subject.translator is backend.translator
    assert subject.kind == kind
    assert subject.describe() == kind


def test_stopping_closes_the_backend_but_suspending_does_not():
    backend = FakeBackend()
    subject = service(lambda _config: backend)

    subject.suspend()
    assert backend.stopped is False

    subject.stop()
    assert backend.stopped is True
