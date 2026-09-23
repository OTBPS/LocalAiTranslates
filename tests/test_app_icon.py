"""The application icon, at every size Windows asks for.

The retired mark carried five ideas -- a red field, a black diagonal, a
yellow disc, four crop brackets and the glyph -- and below 32 px that is
not a mark, it is a smudge. These tests pin the two properties that made
it one: every size is rendered rather than downsampled, and the glyph
occupies enough of the small tiles to survive.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "screen_translator" / "assets"
ICON = ASSETS / "app-icon.ico"

SIZES = ((16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256))


def frame(size: int) -> Image.Image:
    icon = Image.open(ICON)
    icon.size = (size, size)
    return icon.convert("RGBA")


def ink_box(image: Image.Image):
    """The bounding box of the light glyph inside the tile."""
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha > 200 and min(red, green, blue) > 200:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def test_the_icon_covers_every_windows_size():
    assert sorted(Image.open(ICON).ico.sizes()) == sorted(SIZES)


@pytest.mark.parametrize("size", [item[0] for item in SIZES])
def test_every_size_is_rendered_rather_than_downsampled(size):
    """Pillow only downsamples a size it was not given.

    The generator supplies all nine, so a small tile is drawn for its
    own pixel count instead of being a shrunk 256.
    """
    image = frame(size)

    assert image.size == (size, size)
    assert image.getextrema()[3][1] == 255, "the tile has to be opaque somewhere"


@pytest.mark.parametrize("size", [16, 20, 24, 32, 48, 64, 128, 256])
def test_the_glyph_stays_legible_at_every_size(size):
    box = ink_box(frame(size))

    assert box is not None, f"no glyph at {size}px"
    width = box[2] - box[0] + 1
    # Optical sizing: a small tile spends proportionally more of itself
    # on the character, because thirteen strokes need the pixels.
    floor = 0.66 if size <= 24 else 0.5
    assert width / size >= floor, f"{size}px glyph is {width / size:.2f} of the tile"
    # And not so large it touches the edge, which reads as clipping.
    assert width / size <= 0.9


@pytest.mark.parametrize("size", [16, 32, 64, 256])
def test_the_glyph_is_centred(size):
    box = ink_box(frame(size))

    left, right = box[0], size - 1 - box[2]
    top, bottom = box[1], size - 1 - box[3]
    assert abs(left - right) <= 2, f"{size}px: {left} vs {right}"
    assert abs(top - bottom) <= 2, f"{size}px: {top} vs {bottom}"


def test_the_corners_are_rounded_and_transparent():
    image = frame(256)

    # A square tile would be wrong for the direction, and the shell
    # composites the icon onto whatever is behind it.
    for x, y in ((0, 0), (255, 0), (0, 255), (255, 255)):
        assert image.getpixel((x, y))[3] == 0, f"corner {(x, y)} is opaque"
    assert image.getpixel((128, 128))[3] == 255


def test_the_icon_uses_the_accent_colour_and_not_the_retired_one():
    from screen_translator.design.primitives import BLUE, PAPER, rgb

    image = frame(256)
    # Sample the tile away from the glyph.
    sampled = image.getpixel((40, 128))[:3]
    top, bottom = rgb(BLUE[50]), rgb(BLUE[70])

    for channel, high, low in zip(sampled, top, bottom, strict=True):
        assert min(low, high) - 8 <= channel <= max(low, high) + 8, sampled
    assert sampled != rgb(PAPER["red"])


def test_the_master_artwork_matches_the_generated_icon():
    markup = (ASSETS / "app-icon.svg").read_text(encoding="utf-8")

    # The SVG is the reference an editor opens; a stale one is worse
    # than none, because it looks authoritative.
    assert "#007AFF" in markup and "#0055B8" in markup
    assert "译" in markup
    assert "#C51D23" not in markup, "the retired field colour is still in the master"
    assert re.search(r'rx="\d+"', markup), "the tile has to be rounded"


def test_the_generator_takes_its_colours_from_the_design_package():
    source = (ROOT / "scripts" / "generate_app_icon.py").read_text(encoding="utf-8")

    # Otherwise the icon and the interface drift, which is how the
    # previous one outlived the direction it was drawn for.
    assert "from screen_translator.design.primitives import" in source
    assert not re.search(r'"#[0-9A-Fa-f]{6}"', source)


@pytest.mark.parametrize(
    "script", ("build.ps1", "build_client.ps1", "build_update.ps1")
)
def test_the_release_build_never_reuses_a_cached_executable(script):
    """A regenerated icon at the same path does not invalidate the cache.

    PyInstaller's staleness check for the EXE stage compares paths, not
    contents. Without --clean, changing the icon updates the payload
    beside the exe and leaves the icon embedded *in* the exe as it was,
    so Explorer and the taskbar keep drawing the old one. Found by
    reading the exe's RT_ICON resources after a rebuild appeared to
    succeed.
    """
    source = (ROOT / "scripts" / script).read_text(encoding="utf-8")

    assert "-m PyInstaller --noconfirm --clean" in source
