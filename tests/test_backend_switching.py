"""Switching backends must not leave the application without a working one."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from screen_translator.controller import Controller
from screen_translator.core import Config


class FakeBackend:
    def __init__(self, kind="local"):
        self.kind = kind
        self.stopped = False
        self.ocr = SimpleNamespace(mode="CUDA")
        self.translator = SimpleNamespace(mode="CUDA")

    def ready(self):
        return True

    def refresh(self):
        pass

    def describe(self):
        return self.kind

    def stop(self):
        self.stopped = True


def state(factory, backend):
    return SimpleNamespace(
        config=Config(),
        backend=backend,
        _backend_factory=factory,
        ocr_warmup_token=None,
        manual=Mock(),
        tasks=Mock(start=Mock()),
        tray=Mock(),
        settings=Mock(),
        host_service=Mock(apply=Mock(return_value=SimpleNamespace(state="stopped", detail=""))),
        apply_host_service=Mock(),
        schedule_ocr_warmup=Mock(),
    )


def test_a_successful_switch_stops_only_the_previous_backend():
    previous = FakeBackend("local")
    replacement = FakeBackend("remote")
    context = state(lambda _config: replacement, previous)

    Controller.replace_engines(context)

    assert context.backend is replacement
    assert previous.stopped is True
    assert replacement.stopped is False
    context.apply_host_service.assert_called_once()


def test_a_failed_switch_keeps_the_working_backend_alive():
    previous = FakeBackend("remote")

    def factory(_config):
        raise ValueError("远程模式需要填写主机地址")

    context = state(factory, previous)

    Controller.replace_engines(context)

    assert context.backend is previous
    assert previous.stopped is False, "a closed session cannot be reused"
    context.tray.showMessage.assert_called_once()
    assert "远程模式需要填写主机地址" in context.tray.showMessage.call_args.args[1]
    context.apply_host_service.assert_not_called()


def test_a_failed_switch_still_cancels_in_flight_manual_work():
    context = state(lambda _config: (_ for _ in ()).throw(ValueError("boom")), FakeBackend())

    Controller.replace_engines(context)

    context.manual.cancel.assert_called_once()


@pytest.mark.parametrize("kind", ["local", "remote"])
def test_the_engine_properties_follow_the_current_backend(kind):
    backend = FakeBackend(kind)
    context = SimpleNamespace(backend=backend)

    assert Controller.ocr.fget(context) is backend.ocr
    assert Controller.translator.fget(context) is backend.translator
