"""Icons, coloured at run time from a semantic role.

The SVG family currently hard-codes its stroke colour, so an icon cannot
follow a theme and every variant needs another file. Normalised icons use
`stroke="currentColor"`; this substitutes the real colour and caches the
result, so a role and a size are all a caller needs.

`check.svg` is the exception and stays one: QSS references it through
`image: url(...)`, which cannot be recoloured at all, so dark mode gets a
second file. Keeping the original name matters for a reason unrelated to
design -- `scripts/build_update.ps1` uses `check.svg` as the integrity
sentinel for incremental packages, and renaming it makes that build
throw.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QPixmap

from .resources import asset_path

PLACEHOLDER = "currentColor"
#: Referenced from QSS, so it cannot be tinted; see the module docstring.
STYLESHEET_ICONS = ("check.svg",)


@lru_cache(maxsize=64)
def _source(name: str) -> str:
    with open(asset_path(name), encoding="utf-8") as handle:
        return handle.read()


@lru_cache(maxsize=256)
def tinted(name: str, colour: str, size: int = 24) -> QIcon:
    """The icon in `colour`. Cached: this runs during every repaint path."""
    markup = _source(name).replace(PLACEHOLDER, colour)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(markup.encode("utf-8")), "SVG")
    if pixmap.isNull():
        return QIcon(asset_path(name))
    return QIcon(pixmap.scaled(size, size))


def plain(name: str) -> QIcon:
    return QIcon(asset_path(name))
