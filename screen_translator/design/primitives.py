"""Raw colour. The only module in the project allowed to write a hex value.

Stored as ramps rather than single colours, because that is what makes a
dark theme almost free: the same role reads a different step of the same
ramp instead of needing its own hand-picked value.

`test_no_colour_literals_outside_the_primitive_layer` enforces the rule.
Nothing here knows what a colour is *for*; that is `semantic`.
"""

from __future__ import annotations

#: Apple's neutral ramp, light end first. 0 is paper, 100 is ink.
GREY = {
    0: "#FFFFFF",
    5: "#F2F2F7",
    10: "#E5E5EA",
    15: "#D1D1D6",
    20: "#C6C6C8",
    #: Light enough to read as a hairline, dark enough that a control
    #: border clears WCAG 1.4.11's 3:1 on both the card and the canvas.
    #: Apple's own #C6C6C8 is 1.7:1 and would not.
    25: "#8A8A8E",
    30: "#AEAEB2",
    40: "#98989F",
    50: "#8E8E93",
    60: "#6C6C70",
    #: The dark-theme counterpart of GREY[25], for the same reason.
    65: "#7C7C80",
    70: "#48484A",
    80: "#38383A",
    85: "#2C2C2E",
    90: "#1C1C1E",
    100: "#000000",
}

#: System blue. 60 is the fill used behind white text; see ADR 0006 for
#: why it is not Apple's own #007AFF.
BLUE = {
    10: "#D6E9FF",
    40: "#409CFF",
    50: "#007AFF",
    60: "#0066DB",
    70: "#0055B8",
    80: "#00408C",
    #: The dark-mode system blue, which already clears AA on #1C1C1E.
    "dark": "#0A84FF",
}

RED = {
    50: "#FF3B30",
    60: "#D70015",
    70: "#A3000F",
    # Apple's dark-mode red is #FF453A, which is 4.09:1 on the raised
    # surface -- below AA. Lightened until it passes there too.
    "dark": "#FF6961",
}

GREEN = {
    50: "#34C759",
    # Apple's own dark green is #248A3D, which is 4.40:1 on white and
    # 3.94:1 on the canvas -- both below AA. Darkened until it passes on
    # both, which is a change of shade nobody will notice.
    60: "#1F7A35",
    "dark": "#30D158",
}

ORANGE = {
    50: "#FF9500",
    60: "#8F5A00",
    "dark": "#FFD60A",
}

# ---------------------------------------------------------------------
# The retired constructivist palette.
#
# Kept so the generated stylesheet can reproduce the current appearance
# exactly while the component layer is rebuilt. That separation is the
# point of the sequence: if the interface breaks during the component
# work, it is the components, not the colours. Removed by the commit that
# flips the visual direction. See ADR 0002.
# ---------------------------------------------------------------------
PAPER = {
    "background": "#E9DFC8",
    "surface": "#F8F1E2",
    "raised": "#FFFDFC",
    "white": "#FFFFFF",
    "ink": "#151515",
    "muted": "#514B40",
    "disabled_text": "#766F62",
    "disabled_fill": "#D6CCB8",
    "red": "#C51D23",
    "red_hover": "#AA171C",
    "red_pressed": "#821116",
    "danger": "#B4161B",
    "yellow": "#E8BC35",
    "yellow_pressed": "#D2A525",
    "success": "#343A24",
    "warning": "#7A2C16",
}


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _channel(value: int) -> float:
    fraction = value / 255
    return fraction / 12.92 if fraction <= 0.03928 else ((fraction + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    """WCAG 2.1 relative luminance."""
    red, green, blue = (_channel(part) for part in rgb(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 2.1 contrast ratio, between 1 and 21.

    Eight lines that turn "4.5:1" from a sentence in a document into
    something the build can refuse to violate.
    """
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def mix(first: str, second: str, weight: float) -> str:
    """Blend two colours. `weight` is how much of `second` to use."""
    parts = (
        round(one + (other - one) * weight)
        for one, other in zip(rgb(first), rgb(second), strict=True)
    )
    return "#" + "".join(f"{part:02X}" for part in parts)
