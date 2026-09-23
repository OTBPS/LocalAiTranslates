"""Font families, sizes and weights.

Two rules here are not preferences.

Latin families come **first** in every stack, so CJK characters fall
through to Microsoft YaHei UI naturally. The stylesheet used to lead with
Arial, which is the same mistake with a worse outcome: Arial has no CJK
coverage, so the fallback happened anyway, just unpredictably.

Weights stop at 700. Microsoft YaHei ships Light, Regular and Bold only,
so asking for 900 makes Qt synthesise the weight by stroking the outline
outward. At 96 dpi that renders as mush, which is what the retired
900-weight `heroTitle` did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Qt takes the first family it can resolve, so unavailable ones are free.
#: Segoe UI Variable has optical sizes (Display / Text / Small); it is the
#: closest thing Windows has to SF Pro, which cannot be redistributed.
APPLE_DISPLAY = ("Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI")
APPLE_TEXT = ("Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI")

CONSTRUCTIVIST_DISPLAY = ("Arial Black", "Microsoft YaHei UI")
CONSTRUCTIVIST_TEXT = ("Arial", "Microsoft YaHei UI", "Segoe UI")

#: Anything outside this set is refused. See the module docstring.
ALLOWED_WEIGHTS = (400, 500, 600, 700)

#: Below this, use the Text optical size rather than Display.
DISPLAY_THRESHOLD = 20


@dataclass(frozen=True)
class Typography:
    name: str
    display: tuple[str, ...]
    text: tuple[str, ...]

    size_title: int = 28
    size_section: int = 17
    size_body: int = 14
    size_label: int = 12
    size_small: int = 12

    weight_body: int = 400
    weight_medium: int = 500
    weight_label: int = 600
    weight_heading: int = 700

    overrides: dict[str, int] = field(default_factory=dict)

    def family(self, size: int) -> str:
        """The stack for a size, as QSS wants it: quoted and comma joined."""
        names = self.display if size >= DISPLAY_THRESHOLD else self.text
        return ", ".join(f'"{name}"' for name in names)

    def weights(self) -> tuple[int, ...]:
        return (
            self.weight_body,
            self.weight_medium,
            self.weight_label,
            self.weight_heading,
        )


APPLE = Typography(name="apple", display=APPLE_DISPLAY, text=APPLE_TEXT)

#: What ships today. The weights are deliberately the same as APPLE's
#: rather than the 900 currently in the stylesheet: synthesised CJK bold
#: is a defect, not part of the direction, and fixing it does not have to
#: wait for the visual flip.
CONSTRUCTIVIST = Typography(
    name="constructivist",
    display=CONSTRUCTIVIST_DISPLAY,
    text=CONSTRUCTIVIST_TEXT,
)

ACTIVE = CONSTRUCTIVIST

TYPOGRAPHY = {item.name: item for item in (APPLE, CONSTRUCTIVIST)}
