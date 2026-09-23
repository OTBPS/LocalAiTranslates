"""Generate the checked-in Windows icon from the master artwork.

One idea per icon: the 译 glyph on a rounded blue tile. The retired
constructivist mark carried five -- a red field, a black diagonal, a
yellow disc, four crop brackets and the glyph -- and at 16 px that is
not a mark, it is a smudge.

**Each size is rendered at its own scale rather than downsampled from
one master.** 译 has thirteen strokes; shrinking a 1024 px render to
16 px turns them into grey. Small tiles therefore give the glyph more of
the square and drop the highlight, which is below a pixel down there
anyway. Pillow's ICO writer uses a provided image whose size matches
exactly and only downsamples when one is missing, so supplying all nine
means none of them are guesses.

Colours come from `design.primitives`, so the icon and the interface
cannot drift apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from screen_translator.design.primitives import BLUE, GREY, mix  # noqa: E402

ASSETS = ROOT / "screen_translator" / "assets"

#: Every size Windows asks for, from the notification area to the
#: extra-large Explorer view.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
#: The PNG beside the ICO, for documentation and the repository.
MASTER = 1024

#: Rendered this much larger and then reduced, so the glyph edges are
#: properly antialiased instead of aliased at the target size.
SUPERSAMPLE = 8

GLYPH = "译"

#: Roughly the iOS corner as Pillow can draw it. Qt and Pillow both have
#: circular corners only; at this radius the absence of a continuous
#: curve is not visible.
RADIUS_RATIO = 0.2237
#: A hair of transparent margin so the rounded corners are not clipped
#: by whatever the shell composites the icon onto.
INSET_RATIO = 0.015

TOP = BLUE[50]
BOTTOM = BLUE[70]
INK = GREY[0]


def _font(pixels: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=pixels, index=0)
    raise FileNotFoundError("Microsoft YaHei is required to generate the application icon")


def glyph_ratio(size: int) -> float:
    """How much of the tile the character takes, by target size.

    Optical sizing, in the same spirit as the Display and Text cuts of
    the interface font. A small tile has fewer pixels to spend on
    thirteen strokes, so it spends proportionally more of them.
    """
    if size <= 24:
        return 0.80
    if size <= 48:
        return 0.72
    return 0.62


def tile(size: int) -> Image.Image:
    """One icon, rendered for one target size."""
    scale = size * SUPERSAMPLE
    image = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = round(scale * INSET_RATIO)
    box = (inset, inset, scale - inset - 1, scale - inset - 1)
    radius = round((scale - inset * 2) * RADIUS_RATIO)

    # A vertical gradient, painted as rows and then masked to the
    # rounded square. Pillow has no gradient fill.
    gradient = Image.new("RGBA", (scale, scale))
    painter = ImageDraw.Draw(gradient)
    for y in range(scale):
        painter.line(((0, y), (scale, y)), fill=mix(TOP, BOTTOM, y / max(1, scale - 1)))
    mask = Image.new("L", (scale, scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    image.paste(gradient, (0, 0), mask)

    # The specular stand-in from the visual direction: a light stroke
    # along the top edge only. Sub-pixel on a small tile, so skipped.
    if size >= 48:
        highlight = round(scale * 0.012)
        draw.rounded_rectangle(
            box,
            radius=radius,
            outline=(255, 255, 255, 64),
            width=max(1, highlight),
        )

    pixels = round(scale * glyph_ratio(size))
    font = _font(pixels)
    bounds = draw.textbbox((0, 0), GLYPH, font=font)
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    draw.text(
        ((scale - width) / 2 - bounds[0], (scale - height) / 2 - bounds[1]),
        GLYPH,
        font=font,
        fill=INK,
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    tile(MASTER).save(ASSETS / "app-icon.png", optimize=True)
    frames = [tile(size) for size in sorted(SIZES, reverse=True)]
    frames[0].save(
        ASSETS / "app-icon.ico",
        format="ICO",
        sizes=tuple((size, size) for size in SIZES),
        append_images=frames[1:],
    )
    print(ASSETS / "app-icon.ico")


if __name__ == "__main__":
    main()
