import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from screen_translator.controller import Controller
from screen_translator.core import Config
from screen_translator.feedback import Occupancy
from screen_translator.settings import Settings


def qt_app():
    return QApplication.instance() or QApplication([])


def fake_controller(tmp_path, **overrides):
    """A controller stand-in with just the surface the settings window reads."""
    state = SimpleNamespace(
        config=Config(model_dir=str(tmp_path)),
        busy=False,
        occupancy=Occupancy,
        downloads=SimpleNamespace(active=False, cancel=Mock()),
        detected_source_language=None,
        ocr=SimpleNamespace(mode="未加载"),
        translator=SimpleNamespace(mode="未加载"),
        backend=SimpleNamespace(ready=lambda: False, describe=lambda: "本地模型未下载"),
        host_service=SimpleNamespace(
            status=SimpleNamespace(describe=lambda: "远程服务未启用")
        ),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        toggle=Mock(),
    )
    for name, value in overrides.items():
        setattr(state, name, value)
    return state


def test_tray_menu_places_exit_after_settings_and_language_pair():
    qt_app()
    state = SimpleNamespace(show_settings=Mock(), request_quit=Mock())
    menu = Controller._build_tray_menu(state)
    actions = menu.actions()
    assert [action.text() for action in actions if not action.isSeparator()] == ["设置", "", "退出"]
    assert actions[1].isSeparator()
    assert actions[2].isEnabled()
    assert actions[3].isSeparator()
    actions[2].trigger()
    state.show_settings.assert_called_once_with(focus_language=True)
    actions[4].trigger()
    state.request_quit.assert_called_once()


def test_tray_exit_reuses_settings_confirmation():
    settings = SimpleNamespace(confirm_exit=Mock())
    state = SimpleNamespace(settings=settings)

    Controller.request_quit(state)

    settings.confirm_exit.assert_called_once()


def test_showing_visible_settings_preserves_unsaved_values(monkeypatch):
    settings = Mock()
    settings.isVisible.return_value = True
    state = SimpleNamespace(settings=settings)
    Controller.show_settings(state)
    settings.load_config.assert_not_called()
    settings.refresh.assert_not_called()
    settings.showNormal.assert_called_once()
    settings.raise_.assert_called_once()
    settings.activateWindow.assert_called_once()


def test_showing_hidden_settings_loads_latest_config():
    settings = Mock()
    settings.isVisible.return_value = False
    state = SimpleNamespace(settings=settings)
    Controller.show_settings(state)
    settings.load_config.assert_called_once()
    settings.refresh.assert_called_once()


def test_explicit_activation_cancels_overlay_before_opening_settings():
    state = SimpleNamespace(overlays=[object()], cancel=Mock(), show_settings=Mock())
    Controller.activate_settings(state)
    state.cancel.assert_called_once()
    state.show_settings.assert_called_once()


def test_language_focus_is_deferred_until_window_is_visible(monkeypatch):
    settings = Mock()
    settings.isVisible.return_value = True
    state = SimpleNamespace(settings=settings)
    callbacks = []
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, callback: callbacks.append(callback))
    Controller.show_settings(state, focus_language=True)
    assert len(callbacks) == 1
    callbacks[0]()
    settings.focus_language_controls.assert_called_once()


def test_settings_exit_requires_confirmation_and_emits_request(monkeypatch, tmp_path):
    settings = Settings(fake_controller(tmp_path))
    spy = QSignalSpy(settings.exit_requested)
    asked = []
    # Patched at the port, not at QMessageBox: quitting is one of only two
    # places that still blocks on an answer, and it goes through `confirm`.
    monkeypatch.setattr(
        settings, "confirm", lambda request: bool(asked.append(request)) or True
    )

    settings.exit_button.click()

    assert spy.count() == 1
    assert asked and asked[0].danger is True
    settings.close()


def test_declining_the_exit_confirmation_keeps_the_application_running(tmp_path, monkeypatch):
    settings = Settings(fake_controller(tmp_path))
    spy = QSignalSpy(settings.exit_requested)
    monkeypatch.setattr(settings, "confirm", lambda _request: False)

    settings.exit_button.click()

    assert spy.count() == 0
    settings.close()


def test_settings_copy_is_concise_without_removing_field_labels(monkeypatch, tmp_path):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    settings = Settings(
        fake_controller(
            tmp_path,
            backend=SimpleNamespace(ready=lambda: True, describe=lambda: "本地模型就绪"),
        )
    )
    visible_copy = {label.text() for label in settings.findChildren(QLabel)}
    button_copy = {button.text() for button in settings.findChildren(QPushButton)}
    assert {"输入语言", "输出语言", "全局截图快捷键", "翻译模型", "模型目录"} <= visible_copy
    assert "自动识别 → 简体中文" not in visible_copy
    assert "关闭窗口后继续驻留托盘" not in " ".join(visible_copy)
    assert {"退出", "保存", "开始截图", "下载模型", "重新下载"} <= button_copy
    settings.close()
