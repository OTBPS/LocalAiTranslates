"""Constructivist Qt design tokens, icon helpers, and global stylesheet."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

UI_COLORS = {
    "background": "#E9DFC8",
    "surface": "#F8F1E2",
    "surface_muted": "#FFFDFC",
    "surface_tint": "#E8BC35",
    "text": "#151515",
    "text_muted": "#514B40",
    "border": "#151515",
    "separator": "#151515",
    "primary": "#C51D23",
    "primary_hover": "#AA171C",
    "primary_pressed": "#821116",
    "focus": "#C51D23",
    "success": "#343A24",
    "warning": "#7A2C16",
    "danger": "#B4161B",
}


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def asset_path(name: str) -> str:
    return (_resource_root() / "screen_translator" / "assets" / name).as_posix()


def create_app_icon(size: int = 64) -> QIcon:
    """Load the multi-resolution constructivist application icon."""
    del size  # Kept for API compatibility with existing callers.
    return QIcon(asset_path("app-icon.ico"))


def application_stylesheet() -> str:
    c = UI_COLORS
    check_icon = asset_path("check.svg")
    return f"""
        QWidget {{
            background: {c["background"]};
            color: {c["text"]};
            font-family: "Arial", "Microsoft YaHei UI", "Segoe UI";
            font-size: 14px;
        }}
        QWidget#scrollContent, QScrollArea, QScrollArea > QWidget > QWidget {{
            background: {c["background"]};
            border: none;
        }}
        QFrame#card {{
            background: {c["surface"]};
            border: 2px solid {c["border"]};
            border-radius: 0;
        }}
        QFrame#footerBar {{
            background: {c["surface"]};
            border-top: 3px solid {c["separator"]};
        }}
        QFrame#divider {{
            background: {c["separator"]};
            border: none;
            min-height: 2px;
            max-height: 2px;
        }}
        QLabel {{ background: transparent; }}
        QLabel#heroTitle {{ color: white; font-family: "Arial Black", "Microsoft YaHei UI"; font-size: 28px; font-weight: 900; }}
        QLabel#heroMark {{
            color: white;
            background: #E8BC35;
            border: 2px solid #151515;
            border-radius: 0;
            font-size: 25px;
            font-weight: 900;
        }}
        QLabel#sectionTitle {{ font-family: "Arial Black", "Microsoft YaHei UI"; font-size: 17px; font-weight: 900; color: {c["text"]}; }}
        QLabel#fieldLabel {{ font-size: 12px; font-weight: 700; color: {c["text_muted"]}; }}
        QLabel#pageSubtitle, QLabel#helperText, QLabel#rowSubtitle {{ color: {c["text_muted"]}; }}
        QLabel#rowTitle {{ color: {c["text"]}; font-size: 14px; font-weight: 700; }}
        QLabel#rowSubtitle {{ font-size: 12px; }}
        QLineEdit, QKeySequenceEdit, QComboBox {{
            min-height: 44px;
            padding: 0 13px;
            background: {c["surface_muted"]};
            border: 2px solid {c["border"]};
            border-radius: 0;
            selection-background-color: {c["primary"]};
        }}
        QLineEdit:hover, QKeySequenceEdit:hover, QComboBox:hover {{
            background: #FFFFFF;
            border-color: {c["primary"]};
        }}
        QLineEdit:focus, QKeySequenceEdit:focus, QComboBox:focus {{
            background: #FFFFFF;
            border: 3px solid {c["focus"]};
            padding: 0 11px;
        }}
        QComboBox::drop-down {{ border: none; width: 34px; }}
        QComboBox QAbstractItemView {{
            background: {c["surface"]};
            border: 2px solid {c["border"]};
            border-radius: 0;
            selection-background-color: #E8BC35;
            selection-color: {c["text"]};
            padding: 6px;
            outline: 0;
        }}
        QPushButton {{
            min-height: 42px;
            padding: 0 17px;
            background: {c["surface_muted"]};
            border: 2px solid {c["border"]};
            border-radius: 0;
            font-weight: 700;
        }}
        QPushButton:hover {{ background: #E8BC35; border-color: #151515; }}
        QPushButton:pressed {{ background: #D2A525; }}
        QPushButton:focus {{ border: 3px solid {c["focus"]}; padding: 0 16px; }}
        QPushButton:disabled {{ color: #766F62; background: #D6CCB8; border-color: #766F62; }}
        QPushButton#primaryButton {{
            min-height: 48px;
            background: {c["primary"]};
            color: white;
            border: 2px solid #151515;
            border-radius: 0;
            font-size: 15px;
        }}
        QPushButton#primaryButton:hover {{ background: {c["primary_hover"]}; border-color: {c["primary_hover"]}; }}
        QPushButton#primaryButton:pressed {{ background: {c["primary_pressed"]}; border-color: {c["primary_pressed"]}; }}
        QPushButton#iconButton {{ min-width: 44px; max-width: 44px; padding: 0; background: #E8BC35; }}
        QPushButton#dangerButton {{ color: {c["danger"]}; background: {c["surface"]}; border-color: #151515; }}
        QPushButton#dangerButton:hover {{ color: white; background: {c["danger"]}; border-color: #151515; }}
        QCheckBox {{ spacing: 10px; background: transparent; min-height: 44px; }}
        QCheckBox::indicator {{ width: 20px; height: 20px; border: 2px solid #151515; border-radius: 0; background: white; }}
        QCheckBox::indicator:hover {{ border-color: {c["primary"]}; }}
        QCheckBox::indicator:checked {{ background: {c["primary"]}; border-color: {c["primary"]}; image: url("{check_icon}"); }}
        QCheckBox::indicator:disabled {{ background: #D6CCB8; border-color: #766F62; }}
        QCheckBox:focus {{ color: {c["primary"]}; }}
        QProgressBar {{ min-height: 10px; max-height: 10px; border: 2px solid #151515; border-radius: 0; background: #FFFDFC; text-align: center; color: transparent; }}
        QProgressBar::chunk {{ background: {c["primary"]}; border-radius: 0; }}
        QMenu {{ background: {c["surface"]}; border: 2px solid {c["border"]}; border-radius: 0; padding: 6px; }}
        QMenu::item {{ min-height: 30px; padding: 7px 28px 7px 12px; border-radius: 0; }}
        QMenu::item:selected {{ background: #E8BC35; color: {c["text"]}; }}
        QMenu::separator {{ height: 2px; background: {c["separator"]}; margin: 6px 8px; }}
        QToolTip {{ color: #F8F1E2; background: #151515; border: 1px solid #F8F1E2; border-radius: 0; padding: 7px; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: #151515; border-radius: 0; min-height: 32px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """
