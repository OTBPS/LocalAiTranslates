"""Asset helpers, and a shim over the generated stylesheet.

The stylesheet and its colour table moved to `design/`, which is the only
place a colour value is written now. What is left here is the icon and
asset lookup, plus `UI_COLORS` and `application_stylesheet` as thin
forwards so existing call sites keep working while they are migrated.
Both are removed once nothing reads them.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from .design import metrics, semantic, stylesheet, typography
from .design.resources import asset_path, resource_root

__all__ = [
    "UI_COLORS",
    "application_stylesheet",
    "asset_path",
    "create_app_icon",
    "resource_root",
]


def _shipping():
    return semantic.ACTIVE, metrics.ACTIVE, typography.ACTIVE


def _colour_table() -> dict[str, str]:
    """The old names, resolved through the token layer.

    Kept because `settings.py` and `ui_components.py` still read a few of
    these directly; each is deleted as its call site moves to a token.
    """
    theme = semantic.ACTIVE
    return {
        "background": theme.bg_canvas,
        "surface": theme.bg_surface,
        "surface_muted": theme.bg_surface_raised,
        "surface_tint": theme.bg_hover,
        "text": theme.text_primary,
        "text_muted": theme.text_secondary,
        "border": theme.stroke_control,
        "separator": theme.stroke_separator,
        "primary": theme.accent_fill,
        "primary_hover": theme.accent_fill_hover,
        "primary_pressed": theme.accent_fill_pressed,
        "focus": theme.focus,
        "success": theme.success,
        "warning": theme.caution,
        "danger": theme.critical,
    }


UI_COLORS = _colour_table()


def create_app_icon(size: int = 64) -> QIcon:
    """Load the multi-resolution application icon."""
    del size  # Kept for API compatibility with existing callers.
    return QIcon(asset_path("app-icon.ico"))


def application_stylesheet() -> str:
    return stylesheet(*_shipping())
