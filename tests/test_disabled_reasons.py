"""A disabled control must say why.

Greying something out and leaving the user to guess was the most common
complaint about this window. `Occupancy` answers "is anything busy, and what"
once, so that disabling and explaining cannot drift apart.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.config_store import ConfigStore
from screen_translator.core import Config
from screen_translator.feedback import Occupancy
from screen_translator.settings import Settings


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


def window(tmp_path, occupancy, *, ready=True):
    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    controller = SimpleNamespace(
        configuration=store,
        config=store.current,
        busy=occupancy.busy,
        occupancy=lambda: occupancy,
        downloads=SimpleNamespace(active=False, cancel=Mock()),
        detected_source_language=None,
        ocr=SimpleNamespace(mode="CUDA"),
        translator=SimpleNamespace(mode="CUDA"),
        backend=SimpleNamespace(
            kind="local", ready=lambda: ready, describe=lambda: "本地模型未下载"
        ),
        host_service=SimpleNamespace(status=SimpleNamespace(describe=lambda: "未启用")),
        hotkey=SimpleNamespace(current="Ctrl+Alt+T"),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        refresh_language_actions=Mock(),
        manual=None,
        toggle=Mock(),
    )
    return Settings(controller)


GUARDED = (
    "source_language",
    "target_language",
    "hotkey",
    "directory",
    "translation_model",
    "startup",
    "cpu",
    "save",
    "download_button",
)


def test_every_control_disabled_by_a_download_explains_itself(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    view = window(tmp_path, Occupancy(True, "正在下载模型"))
    try:
        for name in GUARDED:
            widget = getattr(view, name)
            assert widget.isEnabled() is False, name
            assert widget.toolTip() == "正在下载模型", name
    finally:
        view.close()


def test_the_reason_is_removed_once_the_control_is_usable_again(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    view = window(tmp_path, Occupancy(True, "截图翻译正在进行"))
    try:
        assert view.save.toolTip() == "截图翻译正在进行"

        view.c.occupancy = Occupancy
        view.refresh()

        assert view.save.isEnabled() is True
        assert view.save.toolTip() == ""
    finally:
        view.close()


def test_a_control_with_its_own_tooltip_gets_it_back(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    view = window(tmp_path, Occupancy())
    try:
        # The CPU toggle explains what it does; that must survive a spell of
        # being disabled.
        original = view.cpu.toolTip()
        assert original

        view.c.occupancy = lambda: Occupancy(True, "正在下载模型")
        view.refresh()
        assert view.cpu.toolTip() == "正在下载模型"

        view.c.occupancy = Occupancy
        view.refresh()
        assert view.cpu.toolTip() == original
    finally:
        view.close()


def test_the_capture_button_explains_a_backend_that_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: False)
    view = window(tmp_path, Occupancy(), ready=False)
    try:
        assert view.capture_button.isEnabled() is False
        # The reason is the backend's own words, not a generic "unavailable".
        assert view.capture_button.toolTip() == "本地模型未下载"
    finally:
        view.close()
