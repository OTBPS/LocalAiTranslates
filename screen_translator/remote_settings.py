"""The cross-device section of the settings window.

A separate widget rather than another 150 lines inside ``settings`` : it owns
exactly the configuration fields that describe where models run and who may
reach this machine, and it validates them before the rest of the form is
saved.  It reads configuration and reports edits; it never starts work.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .core import (
    AUTO_SERVICE_ADDRESS,
    DEFAULT_SERVICE_PORT,
    LOCAL_MODE,
    REMOTE_MODE,
    Config,
    normalize_allowed_peers,
    normalize_remote_url,
    normalize_service_address,
)
from .design import metrics
from .remote.access import MINIMUM_SECRET_CHARACTERS, generate_secret
from .widgets import Card, ToggleRow

SIZES = metrics.ACTIVE

MODE_LABELS = ((LOCAL_MODE, "本地模型"), (REMOTE_MODE, "远程主机"))
#: The picker always offers this, so a host that Tailscale cannot see --
#: or a build with no Tailscale at all -- is still reachable by address.
MANUAL_DEVICE_LABEL = "手动填写地址"


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


class RemoteSettingsCard(QWidget):
    """Edit the client role (where models run) and the host role (who may connect)."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES.space_card)

        card = Card("跨设备", "让另一台设备负责截屏，由这台或另一台主机运行模型")
        card_layout = card.body
        layout.addWidget(card)

        card_layout.addWidget(_field_label("模型运行位置"))
        self.mode = QComboBox()
        self.mode.setAccessibleName("模型运行位置")
        for code, label in MODE_LABELS:
            self.mode.addItem(label, code)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        card_layout.addWidget(self.mode)

        self.client_group = QWidget()
        client_layout = QVBoxLayout(self.client_group)
        client_layout.setContentsMargins(0, 0, 0, 0)
        client_layout.setSpacing(SIZES.space_tight)

        # Pick the host from the tailnet rather than typing an address the
        # user has to look up first. Tailscale already knows the device
        # name, the operating system and whether it is online.
        client_layout.addWidget(_field_label("主机设备"))
        picker_row = QHBoxLayout()
        picker_row.setSpacing(SIZES.space_tight)
        self.device_picker = QComboBox()
        self.device_picker.setAccessibleName("主机设备")
        self.device_picker.addItem(MANUAL_DEVICE_LABEL, "")
        self.device_picker.currentIndexChanged.connect(self._device_chosen)
        self.refresh_devices_button = QPushButton("刷新")
        self.refresh_devices_button.setAccessibleName("刷新 Tailscale 设备列表")
        picker_row.addWidget(self.device_picker, 1)
        picker_row.addWidget(self.refresh_devices_button)
        client_layout.addLayout(picker_row)

        client_layout.addWidget(_field_label("配对码（在主机上生成）"))
        code_row = QHBoxLayout()
        code_row.setSpacing(SIZES.space_tight)
        self.pairing_code = QLineEdit()
        self.pairing_code.setAccessibleName("配对码")
        self.pairing_code.setPlaceholderText("六位数字")
        self.pairing_code.setMaxLength(16)
        self.pair_button = QPushButton("配对")
        self.pair_button.setAccessibleName("使用配对码连接主机")
        code_row.addWidget(self.pairing_code, 1)
        code_row.addWidget(self.pair_button)
        client_layout.addLayout(code_row)

        client_layout.addWidget(_field_label("远程主机地址"))
        self.remote_url = QLineEdit()
        self.remote_url.setAccessibleName("远程主机地址")
        self.remote_url.setPlaceholderText("http://100.101.102.103:8765")
        client_layout.addWidget(self.remote_url)
        # Still here, and still works: a v0.7.0 host has no pairing route,
        # and a user mid-upgrade must not be stranded.
        client_layout.addWidget(_field_label("配对密钥（旧版主机或手动填写）"))
        self.remote_token = QLineEdit()
        self.remote_token.setAccessibleName("配对密钥")
        self.remote_token.setEchoMode(QLineEdit.EchoMode.Password)
        client_layout.addWidget(self.remote_token)
        self.client_status = QLabel()
        self.client_status.setObjectName("helperText")
        self.client_status.setWordWrap(True)
        client_layout.addWidget(self.client_status)
        card_layout.addWidget(self.client_group)

        divider = QFrame()
        divider.setObjectName("divider")
        card_layout.addWidget(divider)

        self.service_row = ToggleRow(
            "作为主机为其他设备翻译",
            "只在 Tailscale 地址上监听，需要配对密钥",
            "作为主机为其他设备翻译",
        )
        self.service_enabled = self.service_row.switch
        self.service_enabled.toggled.connect(self._mode_changed)
        card_layout.addWidget(self.service_row)

        self.host_group = QWidget()
        host_layout = QVBoxLayout(self.host_group)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(SIZES.space_tight)
        address_grid = QGridLayout()
        address_grid.setHorizontalSpacing(SIZES.space_row)
        address_grid.setVerticalSpacing(SIZES.space_tight)
        address_grid.addWidget(_field_label("监听地址"), 0, 0)
        address_grid.addWidget(_field_label("端口"), 0, 1)
        self.service_address = QLineEdit()
        self.service_address.setAccessibleName("监听地址")
        self.service_address.setPlaceholderText(AUTO_SERVICE_ADDRESS)
        self.service_port = QSpinBox()
        self.service_port.setAccessibleName("监听端口")
        self.service_port.setRange(1024, 65535)
        address_grid.addWidget(self.service_address, 1, 0)
        address_grid.addWidget(self.service_port, 1, 1)
        address_grid.setColumnStretch(0, 1)
        host_layout.addLayout(address_grid)

        # The host half of the code flow: press the button, read six
        # digits out loud, done. No 43-character string changes hands.
        host_layout.addWidget(_field_label("配对码"))
        offer_row = QHBoxLayout()
        offer_row.setSpacing(SIZES.space_tight)
        self.pairing_offer = QLabel("未开始配对")
        self.pairing_offer.setObjectName("pairingCode")
        self.pairing_offer.setAccessibleName("当前配对码")
        self.offer_button = QPushButton("生成配对码")
        self.offer_button.setAccessibleName("生成配对码")
        offer_row.addWidget(self.pairing_offer, 1)
        offer_row.addWidget(self.offer_button)
        host_layout.addLayout(offer_row)

        self.paired_devices = QLabel("尚无已配对设备")
        self.paired_devices.setObjectName("helperText")
        self.paired_devices.setWordWrap(True)
        host_layout.addWidget(self.paired_devices)

        host_layout.addWidget(_field_label("配对密钥（旧版设备手动复制）"))
        secret_row = QHBoxLayout()
        secret_row.setSpacing(SIZES.space_tight)
        self.service_token = QLineEdit()
        self.service_token.setAccessibleName("主机配对密钥")
        self.service_token.setReadOnly(True)
        self.generate_button = QPushButton("生成")
        self.generate_button.clicked.connect(self._generate_secret)
        self.copy_button = QPushButton("复制")
        self.copy_button.clicked.connect(self._copy_secret)
        secret_row.addWidget(self.service_token, 1)
        secret_row.addWidget(self.generate_button)
        secret_row.addWidget(self.copy_button)
        host_layout.addLayout(secret_row)

        host_layout.addWidget(_field_label("设备白名单（留空表示允许同一 tailnet 的设备）"))
        self.allowed_peers = QLineEdit()
        self.allowed_peers.setAccessibleName("设备白名单")
        self.allowed_peers.setPlaceholderText("100.101.102.103, 100.104.105.106")
        host_layout.addWidget(self.allowed_peers)
        self.host_status = QLabel()
        self.host_status.setObjectName("helperText")
        self.host_status.setWordWrap(True)
        host_layout.addWidget(self.host_status)
        card_layout.addWidget(self.host_group)

        self._update_visibility()

    def _mode_changed(self) -> None:
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self) -> None:
        remote = self.mode.currentData() == REMOTE_MODE
        self.client_group.setVisible(remote)
        # Chaining hosts is refused by ``HostService``; hide the controls so
        # the rule is visible before the user saves rather than after.
        self.service_row.setEnabled(not remote)
        self.host_group.setVisible(self.service_enabled.isChecked() and not remote)

    def show_devices(self, peers, *, error: str = "") -> None:
        """Fill the picker from the tailnet, keeping the current choice."""
        chosen = self.device_picker.currentData()
        self.device_picker.blockSignals(True)
        try:
            self.device_picker.clear()
            self.device_picker.addItem(MANUAL_DEVICE_LABEL, "")
            for peer in peers:
                self.device_picker.addItem(f"{peer.label} · {peer.describe()}", peer.address)
            index = self.device_picker.findData(chosen) if chosen else 0
            self.device_picker.setCurrentIndex(max(0, index))
        finally:
            self.device_picker.blockSignals(False)
        if error:
            self.client_status.setText(error)
        elif not peers:
            self.client_status.setText("Tailscale 上没有其他设备，请确认另一台设备已登录")

    def _device_chosen(self) -> None:
        """Turn a picked device into an address, without erasing a typed one."""
        address = self.device_picker.currentData()
        if address:
            self.remote_url.setText(f"http://{address}:{DEFAULT_SERVICE_PORT}")
        self.changed.emit()

    def show_pairing_offer(self, offer) -> None:
        """Display the open code, or why there is not one."""
        if offer is None:
            self.pairing_offer.setText("启用主机服务并保存后即可生成配对码")
            return
        self.pairing_offer.setText(offer.describe())

    def show_paired_devices(self, devices) -> None:
        if not devices:
            self.paired_devices.setText("尚无已配对设备")
            return
        # Names and addresses only; the secret is never rendered.
        self.paired_devices.setText(
            "已配对：" + "、".join(f"{item.label}（{item.address}）" for item in devices)
        )

    def _generate_secret(self) -> None:
        self.service_token.setText(generate_secret())
        self.changed.emit()

    def _copy_secret(self) -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.service_token.text())

    def load_config(self, config: Config) -> None:
        for widget in (self.mode, self.service_enabled):
            widget.blockSignals(True)
        try:
            index = self.mode.findData(config.mode)
            self.mode.setCurrentIndex(index if index >= 0 else 0)
            self.remote_url.setText(config.remote_url)
            self.remote_token.setText(config.remote_token)
            self.service_enabled.setChecked(config.service_enabled)
            self.service_address.setText(config.service_address)
            self.service_port.setValue(config.service_port)
            self.service_token.setText(config.service_token)
            self.allowed_peers.setText(", ".join(config.service_allowed_peers))
        finally:
            for widget in (self.mode, self.service_enabled):
                widget.blockSignals(False)
        self._update_visibility()

    def set_status(self, client_text: str, host_text: str) -> None:
        self.client_status.setText(client_text)
        self.host_status.setText(host_text)

    def set_editable(self, editable: bool) -> None:
        for widget in (
            self.mode,
            self.remote_url,
            self.remote_token,
            self.service_enabled,
            self.service_address,
            self.service_port,
            self.generate_button,
            self.allowed_peers,
            self.device_picker,
            self.refresh_devices_button,
            self.pairing_code,
            self.pair_button,
            self.offer_button,
        ):
            widget.setEnabled(editable)
        self._update_visibility()

    def values(self) -> dict[str, object]:
        """Validated configuration values, or :class:`ValueError` explaining why not."""
        mode = self.mode.currentData()
        remote_url = normalize_remote_url(self.remote_url.text())
        remote_token = self.remote_token.text().strip()
        if mode == REMOTE_MODE:
            if not remote_url:
                raise ValueError("请填写有效的远程主机地址，例如 http://100.101.102.103:8765")
            if not remote_token:
                raise ValueError("请填写远程主机的配对密钥")
        service_enabled = self.service_enabled.isChecked() and mode != REMOTE_MODE
        service_token = self.service_token.text().strip()
        if service_enabled and len(service_token) < MINIMUM_SECRET_CHARACTERS:
            raise ValueError("请先生成主机配对密钥")
        typed_address = self.service_address.text().strip()
        service_address = normalize_service_address(typed_address)
        if typed_address and service_address == AUTO_SERVICE_ADDRESS and typed_address != AUTO_SERVICE_ADDRESS:
            raise ValueError(f"监听地址无效：{typed_address}")
        typed_peers = [item.strip() for item in self.allowed_peers.text().split(",") if item.strip()]
        allowed_peers = normalize_allowed_peers(typed_peers)
        if len(allowed_peers) != len(typed_peers):
            raise ValueError("设备白名单必须是以逗号分隔的 IP 地址")
        return {
            "mode": mode,
            "remote_url": remote_url,
            "remote_token": remote_token,
            "service_enabled": service_enabled,
            "service_address": service_address,
            "service_port": int(self.service_port.value()),
            "service_token": service_token,
            "service_allowed_peers": allowed_peers,
        }


def runtime_fields_changed(previous: Config, current: Config) -> bool:
    """Whether the backend has to be rebuilt after a save."""
    return (previous.mode, previous.remote_url, previous.remote_token) != (
        current.mode,
        current.remote_url,
        current.remote_token,
    )


def service_fields_changed(previous: Config, current: Config) -> bool:
    """Whether the host listener has to be reconciled after a save."""
    fields: tuple[Callable[[Config], object], ...] = (
        lambda config: config.mode,
        lambda config: config.service_enabled,
        lambda config: config.service_address,
        lambda config: config.service_port,
        lambda config: config.service_token,
        lambda config: config.service_allowed_peers,
    )
    return any(read(previous) != read(current) for read in fields)
