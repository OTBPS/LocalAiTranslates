"""Generate the checked-in Windows icon from the constructivist master artwork."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "screen_translator" / "assets"
CANVAS = 1024
INK = "#151515"
RED = "#C51D23"
YELLOW = "#E8BC35"
PAPER = "#F8F1E2"


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size, index=0)
    raise FileNotFoundError("Microsoft YaHei is required to generate the application icon")


def render() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rectangle((48, 48, 976, 976), fill=RED, outline=INK, width=40)
    draw.polygon(((540, 68), (956, 68), (956, 956), (272, 956)), fill=INK)
    draw.ellipse((638, 100, 902, 364), fill=YELLOW, outline=INK, width=28)

    for rectangle in (
        (150, 174, 198, 350),
        (150, 174, 326, 222),
        (698, 174, 874, 222),
        (826, 174, 874, 350),
        (150, 674, 198, 850),
        (150, 802, 326, 850),
        (698, 802, 874, 850),
        (826, 674, 874, 850),
    ):
        draw.rectangle(rectangle, fill=PAPER)

    font = _font(476)
    glyph = "译"
    bounds = draw.textbbox((0, 0), glyph, font=font, stroke_width=18)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    position = ((CANVAS - width) / 2 - bounds[0], 512 - height / 2 - bounds[1] + 18)
    draw.text(position, glyph, font=font, fill=PAPER, stroke_width=18, stroke_fill=INK)
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = render()
    image.save(ASSETS / "app-icon.png", optimize=True)
    image.save(
        ASSETS / "app-icon.ico",
        format="ICO",
        sizes=((16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)),
    )


if __name__ == "__main__":
    main()
