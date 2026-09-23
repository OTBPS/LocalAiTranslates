"""Forwarding shim. The controls live in `widgets/`.

Kept so the three pages can migrate one at a time rather than as one
unreviewable change. Deleted once nothing imports it.

`ConstructivistHero` is gone rather than forwarded: the banner is
replaced by `widgets.AppHeader`, and the painted decoration it
positioned at `width() - 108` ran off the edge at the minimum window
size and at high DPI. That defect disappears with the component.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout

from .design.resources import asset_path
from .widgets import (
    Card,
    LanguageRow,
    ToggleRow,
    ToggleSwitch,
    set_enabled_with_reason,
)

__all__ = [
    "LanguageRow",
    "ToggleRow",
    "ToggleSwitch",
    "asset_path",
    "make_card",
    "make_language_row",
    "set_enabled_with_reason",
]


def make_card(title: str, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """The old two-value form. New code builds a `Card` and calls `add`."""
    card = Card(title, subtitle or "")
    return card, card.body


def make_language_row(source_languages, target_languages, names, swap_icon_path=None):
    """The old four-value form. New code uses `widgets.LanguageRow`."""
    del swap_icon_path  # The icon is a token now, not a caller's concern.
    row = LanguageRow(source_languages, target_languages, names)
    return row, row.source, row.swap, row.target
