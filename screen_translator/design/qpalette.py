"""A QPalette to match the stylesheet.

A stylesheet does not reach everything. `QMessageBox`, `QToolTip`, spin
box arrows, disabled text and the native file dialog read the palette,
and in a dark theme with only QSS applied they stay light -- which shows
up as white text on a white background in exactly the places a user
cannot avoid.

The application currently sets no palette at all. That is invisible while
the theme is light; it stops being invisible the moment a dark theme
exists, so this ships with the token layer rather than with dark mode.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from .semantic import Theme


def palette(theme: Theme) -> QPalette:
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.bg_canvas,
        QPalette.ColorRole.WindowText: theme.text_primary,
        QPalette.ColorRole.Base: theme.bg_surface_raised,
        QPalette.ColorRole.AlternateBase: theme.bg_surface,
        QPalette.ColorRole.Text: theme.text_primary,
        QPalette.ColorRole.Button: theme.bg_surface,
        QPalette.ColorRole.ButtonText: theme.text_primary,
        QPalette.ColorRole.BrightText: theme.critical,
        QPalette.ColorRole.Highlight: theme.accent_fill,
        QPalette.ColorRole.HighlightedText: theme.text_on_accent,
        QPalette.ColorRole.ToolTipBase: theme.tooltip_bg,
        QPalette.ColorRole.ToolTipText: theme.tooltip_text,
        QPalette.ColorRole.PlaceholderText: theme.text_secondary,
        QPalette.ColorRole.Link: theme.accent_text,
    }
    for role, value in roles.items():
        result.setColor(role, QColor(value))
    # Set explicitly rather than left to Qt's derivation, which lightens
    # the enabled colour and produces unreadable disabled text on a dark
    # background.
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(theme.text_disabled)
        )
    return result
