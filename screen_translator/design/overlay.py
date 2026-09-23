"""The capture overlay's own palette, deliberately pinned.

The overlay paints on top of an unknown screenshot. Whether the
application is in light or dark mode says nothing about whether the
region the user grabbed is bright or dark, so following the theme would
be actively wrong: a dark-mode overlay drawn over a white document is
unreadable, and so is the reverse.

Pinned means pinned against *light and dark*, not against the visual
direction. The values are derived from the primitives, so the overlay
moved with the direction change; what it does not do is follow the
system appearance at run time.

This exception is stated in MASTER.md. ADR 0005 covers the one place in
the project where real glass is achievable -- the status bar -- and why
it is only that one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import BLUE, GREY, ORANGE, RED


@dataclass(frozen=True)
class OverlayPalette:
    #: RGBA. Dimming is what makes a selection legible over any wallpaper.
    dim: tuple[int, int, int, int]
    selection: str
    handle_fill: str
    handle_border: str
    #: RGBA, composited over the blurred strip behind it. Translucent on
    #: purpose: the blur below is only visible through it.
    capsule_fill: tuple[int, int, int, int]
    capsule_border: str
    capsule_text: str
    #: The other ink, for a state badge too dark to carry the first one.
    capsule_text_inverse: str
    capsule_hint: str
    #: A 1 px top stroke, the static stand-in for a specular highlight.
    #: It cannot respond to the background -- see ADR 0002.
    capsule_highlight: tuple[int, int, int, int]
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
    dim=(0, 0, 0, 122),
    selection=BLUE[50],
    handle_fill=GREY[0],
    handle_border=BLUE[50],
    # Light and translucent: dark chrome over a dark screenshot is
    # unreadable, and the bar has its own blur underneath to separate it
    # from whatever it covers.
    capsule_fill=(255, 255, 255, 214),
    capsule_border=GREY[20],
    capsule_text=GREY[100],
    capsule_text_inverse=GREY[0],
    capsule_hint=GREY[60],
    capsule_highlight=(255, 255, 255, 168),
    badge_fill=GREY[100],
    badge_text=GREY[0],
    cursor_core=BLUE[50],
    cursor_halo=GREY[0],
    state_selecting=BLUE[60],
    state_adjusting=BLUE[60],
    state_processing=ORANGE[60],
    state_result=BLUE[60],
    state_failed=RED[60],
)
