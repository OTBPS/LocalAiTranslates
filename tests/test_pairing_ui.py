"""Picking a host and typing six digits, instead of pasting 43 characters.

The parts below the window are covered in test_pairing.py and
test_remote_roundtrip.py; this is about the three things the window has to
get right: the picker turns a device into an address, a code that fails
says so where the user is looking, and the old manual field still works
for a host that has not been updated.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.config_store import ConfigStore
from screen_translator.core import PairedDevice
from screen_translator.feedback import NoticeCenter, Occupancy
from screen_translator.remote.client import RemoteError
from screen_translator.remote.pairing import PairingGrant, PairingOffer, identify
from screen_translator.remote.tailnet import TailnetPeer, TailnetUnavailable
from screen_translator.remote_settings import MANUAL_DEVICE_LABEL
from screen_translator.settings import Settings

SECRET = "s" * 43


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    from screen_translator.core import Config

    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    host_service = SimpleNamespace(
        status=SimpleNamespace(describe=lambda: "正在监听 100.64.0.10:8765"),
        broker=None,
        offer_pairing=Mock(return_value=None),
    )
    controller = SimpleNamespace(
        configuration=store,
        config=store.current,
        busy=False,
        occupancy=lambda: Occupancy(),
        downloads=SimpleNamespace(active=False, cancel=Mock(), start=Mock()),
        detected_source_language=None,
        ocr=SimpleNamespace(mode="CUDA"),
        translator=SimpleNamespace(mode="CUDA"),
        backend=SimpleNamespace(kind="local", ready=lambda: True, describe=lambda: "就绪"),
        host_service=host_service,
        hotkey=SimpleNamespace(current="Ctrl+Alt+T"),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        refresh_language_actions=Mock(),
        replace_engines=Mock(),
        apply_host_service=Mock(),
        manual=None,
        toggle=Mock(),
    )
    view = Settings(controller)
    view.register_notice_sinks(NoticeCenter())
    # The user is looking at the window while pairing, which is what makes
    # the in-page banner the right surface for what pairing has to say.
    view.show()
    view.tabs.setCurrentIndex(2)
    yield view, controller
    view.close()


def peers():
    return (
        TailnetPeer("laptop", "laptop.example.ts.net", "100.64.0.20", "windows", True, "direct"),
        TailnetPeer("tablet", "tablet.example.ts.net", "100.64.0.30", "linux", False, "unknown"),
    )


def test_picking_a_device_fills_in_its_address(window):
    view, _controller = window
    card = view.remote_card

    card.show_devices(peers())
    card.device_picker.setCurrentIndex(card.device_picker.findData("100.64.0.20"))

    # The user had to look this address up by hand before.
    assert card.remote_url.text() == "http://100.64.0.20:8765"


def test_the_list_says_which_devices_are_usable(window):
    view, _controller = window

    view.remote_card.show_devices(peers())

    labels = [
        view.remote_card.device_picker.itemText(index)
        for index in range(view.remote_card.device_picker.count())
    ]
    assert labels[0] == MANUAL_DEVICE_LABEL, "a host Tailscale cannot see is still reachable"
    assert "laptop" in labels[1] and "在线" in labels[1] and "直连" in labels[1]
    assert "离线" in labels[2]


def test_a_tailnet_that_cannot_be_read_says_so_instead_of_showing_nothing(view_or=None):
    from screen_translator.remote_settings import RemoteSettingsCard

    card = RemoteSettingsCard()
    try:
        card.show_devices((), error=str(TailnetUnavailable("未找到 tailscale 命令")))

        assert "tailscale" in card.client_status.text()
    finally:
        card.deleteLater()


def test_a_successful_pairing_fills_in_the_secret_without_showing_it(window, monkeypatch):
    view, _controller = window
    grant = PairingGrant(identify(SECRET), SECRET, label="laptop", host_label="workstation")
    monkeypatch.setattr(
        "screen_translator.remote.client.claim_pairing",
        lambda url, code, **kwargs: grant,
    )
    view.remote_card.remote_url.setText("http://100.64.0.20:8765")
    view.remote_card.pairing_code.setText("123 456")

    assert view.pair_with_host() is True

    assert view.remote_card.remote_token.text() == SECRET
    # Filled in, but never rendered: the field is a password field, and
    # the code box is cleared so it cannot be resubmitted.
    assert view.remote_card.remote_token.echoMode().name == "Password"
    assert view.remote_card.pairing_code.text() == ""
    assert view.banner.notice.notice_id == "pairing"
    assert "workstation" in view.banner.notice.detail


def test_a_rejected_code_is_reported_where_the_user_is_looking(window, monkeypatch):
    view, _controller = window

    def refuse(*_args, **_kwargs):
        raise RemoteError("配对失败，请向主机确认配对码后重试")

    monkeypatch.setattr("screen_translator.remote.client.claim_pairing", refuse)
    view.remote_card.remote_url.setText("http://100.64.0.20:8765")
    view.remote_card.pairing_code.setText("000000")

    assert view.pair_with_host() is False

    # Not a tray balloon: the user is in the window, typing.
    assert view.banner.notice.notice_id == "pairing"
    assert "配对失败" in view.banner.notice.detail
    assert view.remote_card.remote_token.text() == "", "no secret is invented on failure"


@pytest.mark.parametrize(
    ("code", "address", "expected"),
    [("12345", "http://h:1", "配对码"), ("123456", "", "主机")],
)
def test_an_incomplete_form_is_refused_before_any_request(window, code, address, expected):
    view, _controller = window
    view.remote_card.pairing_code.setText(code)
    view.remote_card.remote_url.setText(address)

    assert view.pair_with_host() is False

    assert expected in view.banner.notice.title + view.banner.notice.detail


def test_offering_a_code_without_a_running_host_explains_rather_than_fails(window):
    view, _controller = window

    assert view.offer_pairing() is False

    assert "主机服务" in view.banner.notice.title


def test_an_open_offer_shows_the_code_and_the_time_left(window):
    view, controller = window
    offer = PairingOffer(code="246813")
    controller.host_service.offer_pairing = Mock(return_value=offer)

    assert view.offer_pairing() is True

    text = view.remote_card.pairing_offer.text()
    assert "246813" in text
    # The window is short; not saying how short is how a code goes stale
    # while the user walks to the other machine.
    assert "秒" in text


def test_paired_devices_are_listed_by_name_and_never_by_secret(window):
    view, _controller = window
    devices = (PairedDevice(identify(SECRET), "laptop", "100.64.0.20", SECRET, 0.0),)

    view.remote_card.show_paired_devices(devices)

    text = view.remote_card.paired_devices.text()
    assert "laptop" in text and "100.64.0.20" in text
    assert SECRET not in text


def test_the_manual_secret_field_survives_for_older_hosts(window):
    view, _controller = window

    # A v0.7.0 host has no pairing route at all. Removing this field would
    # strand anyone who updates the client first.
    assert view.remote_card.remote_token.isEnabled()
    view.remote_card.mode.setCurrentIndex(view.remote_card.mode.findData("remote"))
    view.remote_card.remote_url.setText("http://100.64.0.20:8765")
    view.remote_card.remote_token.setText(SECRET)

    assert view.remote_card.values()["remote_token"] == SECRET
