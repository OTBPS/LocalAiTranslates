"""The system tray presence.

The tray is the only part of the application that is always there, so it
had accumulated the menu, the tooltip, the language readout and eight
direct `showMessage` calls. Messages now go through the notice layer; what
is left is a small view that announces what was clicked and is told what to
display.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import create_app_icon


class TrayIcon(QObject):
    """Icon, menu and tooltip. Decides nothing."""

    settings_requested = Signal()
    languages_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(icon or create_app_icon(), self)
        self.menu = self._build_menu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.setToolTip("屏译")

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("设置", self.settings_requested.emit)
        menu.addSeparator()
        # No text yet: the language pair is pushed in by `describe`.
        self.language_action = menu.addAction("")
        self.language_action.triggered.connect(
            lambda _checked=False: self.languages_requested.emit()
        )
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        return menu

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.settings_requested.emit()

    def describe(self, hotkey: str, language_pair: str) -> None:
        """Show the shortcut and the language pair without opening anything."""
        self.language_action.setText(language_pair)
        self.icon.setToolTip(f"屏译 · {hotkey} · {language_pair}")

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()
