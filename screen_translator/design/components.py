"""Per-component values, as functions over a theme.

Functions rather than constants, for one specific reason: QSS cannot
reach a widget that paints itself. `ToggleSwitch.paintEvent` draws its own
track and knob, so six colours are currently written into it by hand and
drift from the stylesheet whenever one side changes. A function is
callable from both.

Nothing here builds a widget or emits QSS. It answers "what does a button
look like in this theme", and `qss` and the painted widgets both ask.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import Metrics
from .semantic import Theme


@dataclass(frozen=True)
class ButtonTokens:
    fill: str
    fill_hover: str
    fill_pressed: str
    text: str
    border: str
    height: int
    radius: int


def primary_button(theme: Theme, metrics: Metrics) -> ButtonTokens:
    return ButtonTokens(
        fill=theme.accent_fill,
        fill_hover=theme.accent_fill_hover,
        fill_pressed=theme.accent_fill_pressed,
        text=theme.text_on_accent,
        border=theme.accent_fill if metrics.border <= 1 else theme.stroke_control,
        height=metrics.height_primary,
        radius=metrics.radius_control,
    )


def secondary_button(theme: Theme, metrics: Metrics) -> ButtonTokens:
    return ButtonTokens(
        fill=theme.bg_surface_raised,
        fill_hover=theme.bg_hover,
        fill_pressed=theme.bg_pressed,
        text=theme.text_primary,
        border=theme.stroke_control,
        height=metrics.height_control,
        radius=metrics.radius_control,
    )


def danger_button(theme: Theme, metrics: Metrics) -> ButtonTokens:
    """Outlined at rest, filled on hover: destructive, not decorative."""
    return ButtonTokens(
        fill=theme.bg_surface,
        fill_hover=theme.critical,
        fill_pressed=theme.critical,
        text=theme.critical,
        border=theme.stroke_control,
        height=metrics.height_control,
        radius=metrics.radius_control,
    )


@dataclass(frozen=True)
class ToggleTokens:
    """Read by `ToggleSwitch.paintEvent`, which QSS cannot style."""

    track_off: str
    track_on: str
    track_border: str
    knob: str
    knob_border: str
    disabled_track: str
    radius: int
    height: int
    width: int

    @property
    def knob_radius(self) -> int:
        return (self.height - 8) // 2


def toggle(theme: Theme, metrics: Metrics) -> ToggleTokens:
    return ToggleTokens(
        track_off=theme.bg_surface_raised,
        track_on=theme.accent_fill,
        track_border=theme.stroke_control,
        knob=theme.bg_surface_raised,
        knob_border=theme.stroke_control,
        disabled_track=theme.bg_disabled,
        radius=metrics.radius_pill,
        height=28,
        width=50,
    )


@dataclass(frozen=True)
class SurfaceTokens:
    fill: str
    border: str
    radius: int
    border_width: int
    padding: int


def card(theme: Theme, metrics: Metrics) -> SurfaceTokens:
    return SurfaceTokens(
        fill=theme.bg_surface,
        border=theme.stroke_separator,
        radius=metrics.radius_card,
        border_width=metrics.border,
        padding=metrics.space_card,
    )


def inset_group_row(theme: Theme, metrics: Metrics) -> SurfaceTokens:
    """A row inside a grouped list: concentric with the card around it."""
    return SurfaceTokens(
        fill=theme.bg_surface,
        border=theme.stroke_separator,
        radius=metrics.radius_group_row,
        border_width=metrics.space_hair,
        padding=metrics.space_row,
    )


@dataclass(frozen=True)
class FieldTokens:
    fill: str
    fill_hover: str
    text: str
    border: str
    border_focus: str
    border_width: int
    radius: int
    height: int
    padding: int
    selection_bg: str
    selection_text: str


def text_field(theme: Theme, metrics: Metrics) -> FieldTokens:
    return FieldTokens(
        fill=theme.bg_surface_raised,
        fill_hover=theme.bg_surface_raised,
        text=theme.text_primary,
        border=theme.stroke_control,
        border_focus=theme.focus,
        # The resting border is already the focus width, so :focus changes
        # colour only. Thickening it on focus and subtracting a pixel of
        # padding to compensate was the most fragile rule in the old
        # stylesheet, and it broke every time a control was restyled.
        border_width=metrics.focus_border,
        radius=metrics.radius_control,
        height=metrics.height_control,
        padding=13,
        selection_bg=theme.selection_bg,
        selection_text=theme.selection_text,
    )


STATUS_ROLES = ("neutral", "success", "warning", "critical")


def status_chip(theme: Theme, role: str) -> tuple[str, str]:
    """Fill and text for a status chip. Colour is never the only signal."""
    return {
        "success": (theme.bg_surface, theme.success),
        "warning": (theme.bg_surface, theme.caution),
        "critical": (theme.bg_surface, theme.critical),
    }.get(role, (theme.bg_surface, theme.text_secondary))
