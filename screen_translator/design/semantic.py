"""What each colour is for.

A role, not a shade: `accent_fill` rather than "blue 60". Everything above
this layer names roles, so changing a theme is changing this file and
nothing else.

Three themes exist during the transition. `CONSTRUCTIVIST` reproduces the
appearance shipped today, so the stylesheet generator and the component
rebuild can land without altering a single pixel; `LIGHT` and `DARK` are
the direction being moved to. See ADR 0002.
"""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import BLUE, GREEN, GREY, ORANGE, PAPER, RED


@dataclass(frozen=True)
class Theme:
    """Every colour the interface is allowed to use, named by its job."""

    name: str
    dark: bool

    bg_canvas: str
    bg_surface: str
    bg_surface_raised: str
    bg_hover: str
    bg_pressed: str
    bg_disabled: str

    text_primary: str
    text_secondary: str
    text_disabled: str
    text_on_accent: str

    stroke_separator: str
    stroke_control: str

    accent_fill: str
    accent_fill_hover: str
    accent_fill_pressed: str
    accent_text: str

    critical: str
    success: str
    caution: str

    focus: str
    selection_bg: str
    selection_text: str

    tooltip_bg: str
    tooltip_text: str

    def values(self) -> tuple[str, ...]:
        """Every colour in this theme, for the census and the QSS check."""
        return tuple(
            value
            for key, value in vars(self).items()
            if key not in ("name", "dark") and isinstance(value, str)
        )


LIGHT = Theme(
    name="light",
    dark=False,
    bg_canvas=GREY[5],
    bg_surface=GREY[0],
    bg_surface_raised=GREY[0],
    bg_hover=GREY[5],
    bg_pressed=GREY[10],
    bg_disabled=GREY[5],
    text_primary=GREY[100],
    text_secondary=GREY[60],
    text_disabled=GREY[30],
    text_on_accent=GREY[0],
    # A hairline that only separates content is decoration; a border
    # that identifies a control is not, and has to clear 3:1.
    stroke_separator=GREY[20],
    stroke_control=GREY[25],
    # Not Apple's #007AFF: white on it is 4.02:1, below AA. ADR 0006.
    accent_fill=BLUE[60],
    accent_fill_hover=BLUE[70],
    accent_fill_pressed=BLUE[80],
    # The same blue as a glyph on white, where 4.02:1 is enough because
    # the requirement for non-text and large text is 3:1.
    accent_text=BLUE[50],
    critical=RED[60],
    success=GREEN[60],
    caution=ORANGE[60],
    focus=BLUE[50],
    selection_bg=BLUE[10],
    selection_text=GREY[100],
    tooltip_bg=GREY[90],
    tooltip_text=GREY[0],
)

DARK = Theme(
    name="dark",
    dark=True,
    bg_canvas=GREY[100],
    bg_surface=GREY[90],
    bg_surface_raised=GREY[85],
    bg_hover=GREY[85],
    bg_pressed=GREY[80],
    bg_disabled=GREY[85],
    text_primary=GREY[0],
    text_secondary=GREY[40],
    text_disabled=GREY[50],
    text_on_accent=GREY[0],
    stroke_separator=GREY[80],
    stroke_control=GREY[65],
    # The same fill as the light theme: white on #0A84FF is 3.65:1,
    # which fails for the same reason #007AFF does. #0066DB still reads
    # as a distinct surface against #1C1C1E at 3.18:1.
    accent_fill=BLUE[60],
    accent_fill_hover=BLUE[50],
    accent_fill_pressed=BLUE[70],
    accent_text=BLUE["dark"],
    critical=RED["dark"],
    success=GREEN["dark"],
    caution=ORANGE["dark"],
    focus=BLUE["dark"],
    selection_bg=BLUE[70],
    selection_text=GREY[0],
    tooltip_bg=GREY[85],
    tooltip_text=GREY[0],
)

#: The appearance shipped today, expressed in the same roles. Its only
#: purpose is to let the stylesheet generator and the component rebuild
#: land with no visual change at all; the commit that flips the direction
#: deletes it. See ADR 0002.
CONSTRUCTIVIST = Theme(
    name="constructivist",
    dark=False,
    bg_canvas=PAPER["background"],
    bg_surface=PAPER["surface"],
    bg_surface_raised=PAPER["raised"],
    bg_hover=PAPER["yellow"],
    bg_pressed=PAPER["yellow_pressed"],
    bg_disabled=PAPER["disabled_fill"],
    text_primary=PAPER["ink"],
    text_secondary=PAPER["muted"],
    text_disabled=PAPER["disabled_text"],
    text_on_accent=PAPER["white"],
    stroke_separator=PAPER["ink"],
    stroke_control=PAPER["ink"],
    accent_fill=PAPER["red"],
    accent_fill_hover=PAPER["red_hover"],
    accent_fill_pressed=PAPER["red_pressed"],
    accent_text=PAPER["red"],
    critical=PAPER["danger"],
    success=PAPER["success"],
    caution=PAPER["warning"],
    focus=PAPER["red"],
    selection_bg=PAPER["red"],
    selection_text=PAPER["white"],
    tooltip_bg=PAPER["ink"],
    tooltip_text=PAPER["surface"],
)

#: What the application actually uses.
#:
#: `CONSTRUCTIVIST` stays defined: reverting the commit that changed this
#: line is the whole rollback, and ADR 0002 says so. It is also what the
#: archived before/after renders were produced with.
ACTIVE = LIGHT

THEMES = {theme.name: theme for theme in (LIGHT, DARK, CONSTRUCTIVIST)}


def theme_for(dark: bool) -> Theme:
    """The theme to use for a system appearance, once the flip has landed."""
    return DARK if dark else LIGHT
