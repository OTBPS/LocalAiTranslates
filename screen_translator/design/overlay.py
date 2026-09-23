"""The capture overlay's own palette, deliberately pinned.

The overlay paints on top of an unknown screenshot. Whether the
application is in light or dark mode says nothing about whether the
region the user grabbed is bright or dark, so following the theme would
be actively wrong: a dark-mode overlay drawn over a white document is
unreadable, and so is the reverse.

The values are derived from the primitives so there is still one source
of colour, and then fixed. This exception is stated in MASTER.md; see
also ADR 0005 for why the status bar -- and only the status bar -- can
have real glass.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import PAPER


@dataclass(frozen=True)
class OverlayPalette:
    dim: tuple[int, int, int, int]
    selection: str
    handle_fill: str
    handle_border: str
    capsule_fill: tuple[int, int, int, int]
    capsule_border: str
    capsule_text: str
    #: The other ink, for a state badge too dark to carry the first one.
    capsule_text_inverse: str
    capsule_hint: str
    badge_fill: str
    badge_text: str
    cursor_core: str
    cursor_halo: str

    state_selecting: str
    state_adjusting: str
    state_processing: str
    state_result: str
    state_failed: str


PINNED = OverlayPalette(
    # Dimming is what makes the selection legible over any wallpaper.
    dim=(21, 21, 21, 138),
    selection=PAPER["red"],
    handle_fill=PAPER["yellow"],
    handle_border=PAPER["ink"],
    capsule_fill=(243, 233, 210, 246),
    capsule_border=PAPER["ink"],
    capsule_text=PAPER["ink"],
    capsule_text_inverse=PAPER["white"],
    capsule_hint=PAPER["muted"],
    badge_fill=PAPER["yellow"],
    badge_text=PAPER["ink"],
    cursor_core=PAPER["yellow"],
    cursor_halo=PAPER["yellow_pale"],
    state_selecting=PAPER["red"],
    state_adjusting=PAPER["red"],
    state_processing=PAPER["yellow"],
    state_result=PAPER["red"],
    state_failed=PAPER["red"],
)
