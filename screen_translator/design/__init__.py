"""Design tokens and the stylesheet generated from them.

Three layers. `primitives` holds raw colour and is the only module in the
project permitted to contain a hex value. `semantic` names roles.
`components` answers per-component questions as functions, so that the
stylesheet and the widgets that paint themselves read the same numbers --
`ToggleSwitch.paintEvent` cannot be reached by QSS, which is why six of
its colours used to be written in by hand.

**This package imports nothing else from `screen_translator`.** A test
enforces it. That makes a circular import structurally impossible and
lets the whole package be exercised without an application.
"""

from __future__ import annotations

from . import components, icons, metrics, overlay, primitives, semantic, typography
from .metrics import Metrics, concentric
from .primitives import contrast_ratio
from .qss import stylesheet
from .semantic import Theme, theme_for
from .typography import Typography

__all__ = [
    "Metrics",
    "Theme",
    "Typography",
    "apply",
    "components",
    "concentric",
    "contrast_ratio",
    "icons",
    "metrics",
    "overlay",
    "primitives",
    "semantic",
    "stylesheet",
    "theme_for",
    "typography",
]


def apply(app, theme=None, sizes=None, fonts=None) -> None:
    """The single mounting point: style, palette and application font.

    Replaces the five lines in `app.main` that set a font, a stylesheet
    and a window icon independently of each other, which is how the font
    ended up declared in two places that could disagree.
    """
    from PySide6.QtGui import QFont

    from .qpalette import palette

    theme = theme or semantic.ACTIVE
    sizes = sizes or metrics.ACTIVE
    fonts = fonts or typography.ACTIVE
    app.setStyle("Fusion")
    app.setPalette(palette(theme))
    font = QFont()
    font.setFamilies(list(fonts.text))
    font.setPixelSize(fonts.size_body)
    app.setFont(font)
    app.setStyleSheet(stylesheet(theme, sizes, fonts))
