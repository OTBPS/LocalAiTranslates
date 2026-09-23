"""Icons in the colour the control they sit on wants.

The SVG family declares `stroke="currentColor"`, which Qt does not
substitute for anything: `QIcon(path)` renders it black. In a dark theme
that is a black glyph on a dark button -- present, and invisible.

`design.icons.tinted` does the substitution and caches the result. This
wrapper only picks the semantic role, so a caller asks for "the icon on
a primary button" rather than for a colour.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from ..design import icons, metrics, semantic

ROLES = ("default", "accent", "critical", "on_accent", "muted")


def _colour(role: str, theme) -> str:
    return {
        "accent": theme.accent_text,
        "critical": theme.critical,
        "on_accent": theme.text_on_accent,
        "muted": theme.text_secondary,
    }.get(role, theme.text_primary)


def themed_icon(name: str, role: str = "default", *, theme=None, size: int | None = None) -> QIcon:
    theme = theme or semantic.ACTIVE
    if name in icons.STYLESHEET_ICONS:
        # Referenced from QSS through `image: url(...)`, which cannot be
        # recoloured at all; those ship as a light and a dark file.
        return icons.plain(name)
    return icons.tinted(name, _colour(role, theme), size or metrics.ACTIVE.height_icon // 2)
