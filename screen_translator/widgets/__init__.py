"""Reusable controls, built from the design tokens.

Split out of `ui_components` so each file is small enough to read and so
the pieces that repeat -- a card, a labelled field, a grouped list, a
button -- exist once. `ui_components` remains as a forwarding shim until
every call site has moved.

Two conventions worth knowing before adding anything here:

- Buttons come from factory functions, not subclasses. Several tests
  assert over `findChildren(QPushButton)`, and a factory keeps that
  honest while a subclass would slowly make it untrue.
- Anything icon-only requires an accessible name as a mandatory
  argument, so omitting it is a `TypeError` rather than something a
  reviewer has to catch.
"""

from __future__ import annotations

from .buttons import button, danger_button, icon_button, primary_button
from .enablement import set_enabled_with_reason
from .fields import Field, FieldGrid
from .icons import themed_icon
from .inputs import ComboBox, SpinBox
from .rows import LanguageRow
from .status import InlineMessage, StatusChip, chip_palette
from .surfaces import AppHeader, Card, Divider, InsetGroup
from .toggle import ToggleRow, ToggleSwitch

__all__ = [
    "AppHeader",
    "Card",
    "ComboBox",
    "Divider",
    "Field",
    "FieldGrid",
    "InlineMessage",
    "InsetGroup",
    "LanguageRow",
    "SpinBox",
    "StatusChip",
    "ToggleRow",
    "ToggleSwitch",
    "button",
    "chip_palette",
    "danger_button",
    "icon_button",
    "primary_button",
    "set_enabled_with_reason",
    "themed_icon",
]
