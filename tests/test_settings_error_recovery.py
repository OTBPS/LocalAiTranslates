"""Saving settings must fail cleanly, and the error path must not fail itself."""

import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.config_store import ConfigStore
from screen_translator.core import Config
from screen_translator.feedback import Occupancy
from screen_translator.native import hotkey_parts
from screen_translator.settings import Settings


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeHotkeys:
    """Stands in for HotkeyService, recording what it was asked to register."""

    def __init__(self, current="Ctrl+Alt+T"):
        self.current = current
        self.applied = []

    def apply(self, sequence):
        if not isinstance(sequence, str):
            raise ValueError("快捷键格式错误")
        self.applied.append(sequence)
        self.current = sequence

    @contextmanager
    def pending(self, sequence):
        previous = self.current
        self.apply(sequence)
        try:
            yield
        except BaseException:
            self.apply(previous)
            raise


def controller(tmp_path, **overrides):
    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    state = SimpleNamespace(
        configuration=store,
        config=store.current,
        busy=False,
        download_token=None,
        detected_source_language=None,
        ocr=SimpleNamespace(mode="未加载"),
        translator=SimpleNamespace(mode="未加载", stop=Mock()),
        backend=SimpleNamespace(kind="local", ready=lambda: True, describe=lambda: "本地模型就绪"),
        occupancy=lambda: Occupancy(),
        host_service=SimpleNamespace(status=SimpleNamespace(describe=lambda: "远程服务未启用")),
        hotkey=FakeHotkeys(),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        refresh_language_actions=Mock(),
        replace_engines=Mock(),
        apply_host_service=Mock(),
        toggle=Mock(),
    )
    for name, value in overrides.items():
        setattr(state, name, value)
    return state


@pytest.mark.parametrize("value", [None, 5, Config(), ["Ctrl", "Alt", "T"]])
def test_a_non_string_shortcut_is_a_readable_error(value):
    # Guards the error path: an AttributeError raised from inside an exception
    # handler is far harder to diagnose than a rejected value.
    with pytest.raises(ValueError, match="快捷键格式错误"):
        hotkey_parts(value)


def test_a_failure_while_saving_restores_the_previous_shortcut(monkeypatch, tmp_path):
    state = controller(tmp_path)
    settings = Settings(state)
    try:
        monkeypatch.setattr(
            "screen_translator.settings.models_ready", lambda *_args: True
        )
        monkeypatch.setattr(
            "screen_translator.settings.set_startup", lambda _enabled: None
        )
        warned = []
        monkeypatch.setattr(settings, "notify", lambda notice: warned.append(notice))
        # Fail while persisting, i.e. after the point where the old code had
        # already rebound the variable the rollback depended on.
        monkeypatch.setattr(
            state.configuration, "update", Mock(side_effect=OSError("disk full"))
        )
        settings.hotkey.setKeySequence("Ctrl+Alt+J")

        assert settings.apply() is False

        # The shortcut in force is the one the application actually had, and
        # the rollback ran without raising anything of its own.
        assert state.hotkey.current == "Ctrl+Alt+T"
        assert state.hotkey.applied == ["Ctrl+Alt+J", "Ctrl+Alt+T"]
        # Reported as a notice, not a modal the user has to dismiss to read.
        assert warned and "disk full" in warned[0].detail
        assert warned[0].persistent, "an error the user must act on cannot expire"
    finally:
        settings.close()


def test_redownload_leaves_a_remote_backend_alone(monkeypatch, tmp_path):
    state = controller(
        tmp_path,
        backend=SimpleNamespace(
            kind="remote", ready=lambda: True, describe=lambda: "远程 CUDA"
        ),
    )
    settings = Settings(state)
    try:
        monkeypatch.setattr(
            "screen_translator.settings.models_ready", lambda *_args: True
        )
        monkeypatch.setattr(
            "screen_translator.settings.QMessageBox.question",
            lambda *_args, **_kwargs: __import__(
                "PySide6.QtWidgets", fromlist=["QMessageBox"]
            ).QMessageBox.StandardButton.Yes,
        )
        monkeypatch.setattr(
            "screen_translator.settings.isolate_model_for_redownload",
            lambda *_args: None,
        )
        monkeypatch.setattr(settings, "download_models", Mock())

        settings.reset_models()

        # The remote port owns no local server; stopping it would claim
        # something that did not happen.
        state.translator.stop.assert_not_called()
    finally:
        settings.close()


def test_redownload_still_stops_a_local_translator(monkeypatch, tmp_path):
    state = controller(tmp_path)
    settings = Settings(state)
    try:
        monkeypatch.setattr(
            "screen_translator.settings.models_ready", lambda *_args: True
        )
        monkeypatch.setattr(
            "screen_translator.settings.QMessageBox.question",
            lambda *_args, **_kwargs: __import__(
                "PySide6.QtWidgets", fromlist=["QMessageBox"]
            ).QMessageBox.StandardButton.Yes,
        )
        monkeypatch.setattr(
            "screen_translator.settings.isolate_model_for_redownload",
            lambda *_args: None,
        )
        monkeypatch.setattr(settings, "download_models", Mock())

        settings.reset_models()

        state.translator.stop.assert_called_once()
    finally:
        settings.close()
