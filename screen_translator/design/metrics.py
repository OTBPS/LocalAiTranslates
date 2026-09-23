"""Geometry: radii, spacing, borders, control heights.

Separate from colour so the direction flip is two data files rather than
one large one, and so a layout question can be answered without reading
the palette.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Everything is a multiple of this. Liquid Glass biases large, so the
#: chosen multiples are bigger than the constructivist ones were.
BASE = 4


def concentric(outer: int, padding: int) -> int:
    """The radius a shape inset by `padding` needs to look concentric.

    A rounded shape inside another one only looks right when the inner
    radius is the outer radius minus the gap between them. Writing the
    two numbers independently is the single easiest way to make the
    geometry look subtly wrong, so this is a function and not a table.
    """
    return max(0, outer - padding)


@dataclass(frozen=True)
class Metrics:
    name: str

    radius_card: int
    radius_group_row: int
    radius_control: int
    radius_small: int
    #: Large enough that Qt's circular corners read as a capsule.
    radius_pill: int

    border: int
    #: Declared in the resting state too, so `:focus` only changes the
    #: colour. Equal to `border` on purpose: that is what keeps focus
    #: from shifting the layout.
    focus_border: int
    #: Structural rules -- a footer edge, a section divider -- which are
    #: heavier than a control border in the flat direction and lighter in
    #: the rounded one.
    rule: int

    space_hair: int
    space_tight: int
    space_row: int
    space_card: int
    space_section: int
    space_page: int

    height_primary: int
    height_control: int
    height_icon: int
    height_tab: int

    def padding_for(self, height: int, content: int) -> int:
        return max(0, (height - content) // 2)


#: What ships today: square corners, 2 px rules, 44 px everywhere.
FLAT = Metrics(
    name="flat",
    radius_card=0,
    radius_group_row=0,
    radius_control=0,
    radius_small=0,
    radius_pill=0,
    border=2,
    focus_border=2,
    rule=3,
    space_hair=2,
    space_tight=6,
    space_row=7,
    space_card=14,
    space_section=14,
    space_page=26,
    height_primary=48,
    height_control=44,
    height_icon=44,
    height_tab=40,
)

#: The direction being moved to. Radii are concentric: a 20 px card
#: padding inside a 16 px card gives an inner radius of 0, so inset rows
#: use 10 and sit on a 6 px inset. Heights follow ADR 0003.
ROUNDED = Metrics(
    name="rounded",
    radius_card=16,
    radius_group_row=10,
    radius_control=10,
    radius_small=8,
    radius_pill=999,
    #: One pixel, because depth comes from hairlines rather than weight.
    border=1,
    #: Still 2, and declared at rest: :focus must never change geometry.
    focus_border=2,
    rule=1,
    space_hair=1,
    space_tight=8,
    space_row=12,
    space_card=16,
    space_section=20,
    space_page=24,
    height_primary=44,
    height_control=36,
    height_icon=40,
    height_tab=36,
)

#: Flipped together with `semantic.ACTIVE`; see ADR 0002.
ACTIVE = FLAT

METRICS = {item.name: item for item in (FLAT, ROUNDED)}
