import os
from dataclasses import replace

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.core import Config
from screen_translator.remote_settings import (
    RemoteSettingsCard,
    runtime_fields_changed,
    service_fields_changed,
)

SECRET = "s" * 32


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def card():
    widget = RemoteSettingsCard()
    yield widget
    widget.close()


def test_a_fresh_card_reports_the_local_defaults(card):
    card.load_config(Config())

    assert card.values() == {
        "mode": "local",
        "remote_url": "",
        "remote_token": "",
        "service_enabled": False,
        "service_address": "auto",
        "service_port": 8765,
        "service_token": "",
        "service_allowed_peers": (),
    }


def test_remote_client_fields_appear_only_in_remote_mode(card):
    card.load_config(Config())
    assert card.client_group.isVisibleTo(card) is False

    card.mode.setCurrentIndex(card.mode.findData("remote"))

    assert card.client_group.isVisibleTo(card) is True


def test_remote_mode_requires_an_address(card):
    card.load_config(Config())
    card.mode.setCurrentIndex(card.mode.findData("remote"))
    card.remote_token.setText(SECRET)

    with pytest.raises(ValueError, match="远程主机地址"):
        card.values()


def test_remote_mode_requires_a_pairing_secret(card):
    card.load_config(Config())
    card.mode.setCurrentIndex(card.mode.findData("remote"))
    card.remote_url.setText("100.101.102.103:8765")

    with pytest.raises(ValueError, match="配对密钥"):
        card.values()


def test_a_bare_host_and_port_is_accepted_and_normalised(card):
    card.load_config(Config())
    card.mode.setCurrentIndex(card.mode.findData("remote"))
    card.remote_url.setText("100.101.102.103:8765")
    card.remote_token.setText(SECRET)

    assert card.values()["remote_url"] == "http://100.101.102.103:8765"


def test_enabling_the_host_role_requires_a_generated_secret(card):
    card.load_config(Config())
    card.service_enabled.setChecked(True)

    with pytest.raises(ValueError, match="主机配对密钥"):
        card.values()

    card.generate_button.click()
    assert card.values()["service_enabled"] is True
    assert len(card.values()["service_token"]) >= 32


def test_the_host_role_is_disabled_in_remote_mode(card):
    card.load_config(replace(Config(), service_enabled=True, service_token=SECRET))
    card.mode.setCurrentIndex(card.mode.findData("remote"))
    card.remote_url.setText("http://100.101.102.103:8765")
    card.remote_token.setText(SECRET)

    values = card.values()

    assert values["service_enabled"] is False
    assert card.service_row.isEnabled() is False


def test_an_invalid_listen_address_is_rejected_rather_than_silently_reset(card):
    card.load_config(replace(Config(), service_enabled=True, service_token=SECRET))
    card.service_address.setText("not-an-address")

    with pytest.raises(ValueError, match="监听地址无效"):
        card.values()


def test_a_malformed_allow_list_is_rejected(card):
    card.load_config(replace(Config(), service_enabled=True, service_token=SECRET))
    card.allowed_peers.setText("100.101.102.103, nonsense")

    with pytest.raises(ValueError, match="设备白名单"):
        card.values()


def test_a_valid_allow_list_is_parsed_into_addresses(card):
    card.load_config(replace(Config(), service_enabled=True, service_token=SECRET))
    card.allowed_peers.setText(" 100.101.102.103 , 100.104.105.106 ")

    assert card.values()["service_allowed_peers"] == ("100.101.102.103", "100.104.105.106")


def test_an_existing_configuration_is_displayed_and_returned_unchanged(card):
    config = replace(
        Config(),
        mode="remote",
        remote_url="http://100.101.102.103:8765",
        remote_token=SECRET,
        service_address="100.104.105.106",
        service_port=9100,
    )

    card.load_config(config)
    values = card.values()

    assert values["mode"] == "remote"
    assert values["remote_url"] == config.remote_url
    assert values["remote_token"] == SECRET
    assert values["service_port"] == 9100


def test_the_secret_is_masked_in_the_client_field(card):
    from PySide6.QtWidgets import QLineEdit

    assert card.remote_token.echoMode() == QLineEdit.EchoMode.Password


def test_readonly_mode_disables_every_editable_control(card):
    card.load_config(Config())

    card.set_editable(False)

    assert card.mode.isEnabled() is False
    assert card.service_enabled.isEnabled() is False
    assert card.allowed_peers.isEnabled() is False


def test_the_model_selection_is_marked_as_local_only_in_remote_mode(tmp_path, monkeypatch):
    # The dropdown keeps governing downloads, but it does not choose the
    # model a remote host translates with; an unqualified control would imply
    # it does.
    from types import SimpleNamespace
    from unittest.mock import Mock

    from screen_translator.settings import Settings

    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    controller = SimpleNamespace(
        config=Config(model_dir=str(tmp_path)),
        busy=False,
        download_token=None,
        detected_source_language=None,
        ocr=SimpleNamespace(mode="未加载"),
        translator=SimpleNamespace(mode="未加载"),
        backend=SimpleNamespace(ready=lambda: True, describe=lambda: "本地模型就绪"),
        host_service=SimpleNamespace(status=SimpleNamespace(describe=lambda: "远程服务未启用")),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        toggle=Mock(),
    )
    settings = Settings(controller)
    try:
        # isHidden rather than isVisibleTo: the card sits on a tab page that
        # is not current, which would make isVisibleTo false either way.
        assert settings.model_scope_note.isHidden() is True

        settings.remote_card.mode.setCurrentIndex(settings.remote_card.mode.findData("remote"))

        assert settings.model_scope_note.isHidden() is False
        assert "主机的模型" in settings.model_scope_note.text()
        # Still usable, because downloading a local model must stay possible.
        assert settings.translation_model.isEnabled() is True
    finally:
        settings.close()


def test_backend_rebuild_is_triggered_only_by_client_role_changes():
    base = Config()

    assert runtime_fields_changed(base, replace(base, mode="remote")) is True
    assert runtime_fields_changed(base, replace(base, remote_url="http://100.64.0.1:8765")) is True
    assert runtime_fields_changed(base, replace(base, service_port=9000)) is False
    assert runtime_fields_changed(base, replace(base, hotkey="Ctrl+Alt+Y")) is False


def test_listener_reconciliation_is_triggered_by_host_role_changes():
    base = Config()

    assert service_fields_changed(base, replace(base, service_enabled=True)) is True
    assert service_fields_changed(base, replace(base, service_port=9000)) is True
    assert service_fields_changed(base, replace(base, service_allowed_peers=("100.64.0.1",))) is True
    assert service_fields_changed(base, replace(base, hotkey="Ctrl+Alt+Y")) is False
