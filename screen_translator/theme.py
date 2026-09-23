"""Asset helpers, and a forward to the generated stylesheet.

The colour table and the stylesheet moved to `design/`, which is the
only place a colour value is written now. `UI_COLORS` is gone: nothing
reads it, and leaving a second table around invites something to start.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from .design import metrics, semantic, stylesheet, typography
from .design.resources import asset_path, resource_root

__all__ = [
    "application_stylesheet",
    "asset_path",
    "create_app_icon",
    "resource_root",
]


def create_app_icon(size: int = 64) -> QIcon:
    """Load the multi-resolution application icon."""
    del size  # Kept for API compatibility with existing callers.
    return QIcon(asset_path("app-icon.ico"))


def application_stylesheet() -> str:
    return stylesheet(semantic.ACTIVE, metrics.ACTIVE, typography.ACTIVE)
