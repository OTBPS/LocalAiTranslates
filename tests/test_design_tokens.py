"""The design token layer, which nothing imports yet.

It lands unused on purpose: the stylesheet generator and the component
rebuild can then be verified to change nothing, and only after that does
the visual direction flip. See ADR 0002.

The contrast test is the highest-value thing in this file. It is eight
lines of WCAG arithmetic and it converts "4.5:1" from a sentence in a
document into something the build refuses to violate — with no exemption
list, which is the whole reason ADR 0006 picked a different blue rather
than granting the first exception.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from screen_translator.design import components, metrics, primitives, semantic, typography
from screen_translator.design.primitives import contrast_ratio
from screen_translator.design.qss import stylesheet

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "screen_translator"
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")

AA_NORMAL = 4.5
AA_LARGE = 3.0
AA_NON_TEXT = 3.0


# -- contrast ----------------------------------------------------------


def text_pairs(theme: semantic.Theme):
    """Every combination of text colour and the surface it sits on."""
    surfaces = (theme.bg_canvas, theme.bg_surface, theme.bg_surface_raised)
    for surface in surfaces:
        for role in ("text_primary", "text_secondary", "critical", "success", "caution"):
            yield f"{role} on {surface}", getattr(theme, role), surface
    yield "text_on_accent on accent_fill", theme.text_on_accent, theme.accent_fill
    yield "selection_text on selection_bg", theme.selection_text, theme.selection_bg
    yield "tooltip_text on tooltip_bg", theme.tooltip_text, theme.tooltip_bg


@pytest.mark.parametrize("theme", [semantic.LIGHT, semantic.DARK], ids=lambda t: t.name)
def test_contrast_ratios_meet_wcag_aa(theme):
    failures = []
    for label, foreground, background in text_pairs(theme):
        ratio = contrast_ratio(foreground, background)
        if ratio < AA_NORMAL:
            failures.append(f"{label}: {foreground} on {background} = {ratio:.2f}")
    assert not failures, "below 4.5:1 — " + "; ".join(failures)


@pytest.mark.parametrize("theme", [semantic.LIGHT, semantic.DARK], ids=lambda t: t.name)
def test_control_boundaries_and_focus_meet_the_non_text_threshold(theme):
    # A border the user cannot see is not a boundary.
    for role in ("stroke_control", "focus", "accent_fill"):
        ratio = contrast_ratio(getattr(theme, role), theme.bg_surface)
        assert ratio >= AA_NON_TEXT, f"{role} = {ratio:.2f} on {theme.bg_surface}"


def test_the_accent_text_colour_is_only_claimed_for_large_and_non_text():
    # #007AFF on white is 4.02:1 — fine as a glyph or a boundary, not as
    # body text. ADR 0006 is the reason there are two blues.
    ratio = contrast_ratio(semantic.LIGHT.accent_text, semantic.LIGHT.bg_surface)
    assert AA_LARGE <= ratio < AA_NORMAL
    assert contrast_ratio(semantic.LIGHT.text_on_accent, semantic.LIGHT.accent_fill) >= AA_NORMAL


def test_the_contrast_formula_agrees_with_known_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    # The published figure for Apple's system blue, which is why it is
    # not used as a fill behind white text.
    assert contrast_ratio("#FFFFFF", "#007AFF") == pytest.approx(4.02, abs=0.01)


# -- direction ---------------------------------------------------------


def design_modules():
    return sorted((PACKAGE / "design").glob("*.py"))


def test_the_design_package_imports_nothing_from_the_application():
    """Structural: a circular import cannot be introduced here."""
    offenders = []
    for path in design_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # level > 1 escapes the package; level 1 is a sibling.
                if node.level and node.level > 1:
                    offenders.append(f"{path.name}: relative import above design/")
                if node.module and node.module.startswith("screen_translator"):
                    offenders.append(f"{path.name}: {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("screen_translator"):
                        offenders.append(f"{path.name}: {alias.name}")
    assert not offenders, offenders


def test_the_token_layers_only_depend_downwards():
    """primitives knows nothing; semantic knows primitives; and so on."""
    allowed = {
        "primitives": set(),
        "resources": set(),
        "semantic": {"primitives"},
        "metrics": set(),
        "typography": set(),
        "overlay": {"primitives"},
        "components": {"primitives", "semantic", "metrics"},
        "qss": {"primitives", "semantic", "metrics", "typography", "components", "resources"},
        "qpalette": {"primitives", "semantic"},
        "icons": {"resources"},
    }
    for path in design_modules():
        name = path.stem
        if name == "__init__":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        siblings = {
            (node.module or alias.name).lstrip(".")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 1
            for alias in node.names
        }
        extra = siblings - allowed.get(name, set()) - {""}
        assert not extra, f"{name} imports {sorted(extra)}"


# -- the generated stylesheet ------------------------------------------


THEMES = [semantic.LIGHT, semantic.DARK, semantic.CONSTRUCTIVIST]


@pytest.mark.parametrize("theme", THEMES, ids=lambda t: t.name)
@pytest.mark.parametrize("sizes", [metrics.FLAT, metrics.ROUNDED], ids=lambda m: m.name)
def test_every_colour_in_the_stylesheet_comes_from_the_theme(theme, sizes):
    sheet = stylesheet(theme, sizes, typography.ACTIVE)
    used = {value.upper() for value in HEX.findall(sheet)}
    declared = {value.upper() for value in theme.values()}

    # A stray colour cannot survive review by being one character
    # different from the right one.
    assert used <= declared, sorted(used - declared)


@pytest.mark.parametrize("theme", THEMES, ids=lambda t: t.name)
def test_focus_rules_never_change_geometry(theme):
    """The most fragile rule in the old stylesheet, made impossible.

    Focus used to thicken the border and subtract a pixel of padding to
    compensate. Every restyle broke the compensation somewhere.
    """
    sheet = stylesheet(theme, metrics.ROUNDED, typography.ACTIVE)
    for block in re.findall(r":focus[^{]*\{([^}]*)\}", sheet):
        for forbidden in ("padding", "margin", "border-width", "min-height"):
            assert forbidden not in block, f":focus changes {forbidden}: {block.strip()}"
        assert "border:" not in block, f":focus redeclares the border: {block.strip()}"


def test_the_resting_state_already_declares_the_focus_border_width():
    field = components.text_field(semantic.LIGHT, metrics.ROUNDED)

    # This is what lets :focus change only the colour.
    assert field.border_width == metrics.ROUNDED.focus_border


def test_the_stylesheet_uses_no_font_weight_a_cjk_family_cannot_supply():
    sheet = stylesheet(semantic.LIGHT, metrics.ROUNDED, typography.APPLE)
    weights = {int(value) for value in re.findall(r"font-weight:\s*(\d+)", sheet)}

    # YaHei has Light, Regular and Bold. 900 makes Qt stroke the outline
    # outward, which at 96 dpi is mush -- and is what the old heroTitle did.
    assert weights <= set(typography.ALLOWED_WEIGHTS), sorted(weights)


def test_latin_families_come_before_the_cjk_fallback():
    stack = typography.APPLE.family(14)

    assert stack.index("Segoe UI Variable Text") < stack.index("Microsoft YaHei UI")


# -- geometry ----------------------------------------------------------


@pytest.mark.parametrize(
    ("outer", "padding", "expected"), [(16, 6, 10), (16, 16, 0), (10, 2, 8), (8, 20, 0)]
)
def test_concentric_radii_are_computed_rather_than_guessed(outer, padding, expected):
    assert metrics.concentric(outer, padding) == expected


def test_the_rounded_metrics_are_concentric_with_themselves():
    sizes = metrics.ROUNDED

    # A row inset inside a card has to lose exactly the inset.
    inset = sizes.radius_card - sizes.radius_group_row
    assert inset > 0
    assert metrics.concentric(sizes.radius_card, inset) == sizes.radius_group_row


def test_the_primary_button_keeps_its_full_hit_area():
    # ADR 0003: inputs drop to 36, the primary action does not drop.
    assert metrics.ROUNDED.height_primary == 44
    assert metrics.ROUNDED.height_control >= 24, "WCAG 2.5.8 AA minimum"


# -- the transition ----------------------------------------------------


def test_the_active_theme_is_still_the_one_that_ships_today():
    """Until the flip lands, the token layer must change nothing.

    Delete this test in the same commit that changes the direction; it
    is here to make an accidental early flip loud.
    """
    assert semantic.ACTIVE is semantic.CONSTRUCTIVIST
    assert metrics.ACTIVE is metrics.FLAT
    assert typography.ACTIVE is typography.CONSTRUCTIVIST


def test_the_overlay_palette_is_pinned_rather_than_themed():
    from screen_translator.design import overlay

    # It paints on an unknown screenshot; the application's light or dark
    # mode says nothing about the region the user grabbed.
    assert overlay.PINNED.selection == primitives.PAPER["red"]
    assert not hasattr(overlay, "theme_for")


def test_the_token_document_matches_the_code():
    """A token table that can drift is worse than none: it is confidently wrong."""
    from scripts.generate_tokens_doc import OUTPUT, render

    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "run scripts/generate_tokens_doc.py"
    )


def test_the_master_document_is_versioned_with_the_application():
    from screen_translator.version import __version__

    master = (ROOT / "design-system" / "screen-translator" / "MASTER.md").read_text(
        encoding="utf-8"
    )
    declared = re.search(r"\*\*Version:\*\*\s*([\d.]+)", master)

    assert declared, "MASTER.md must declare a version"
    # Documentation drift is not detectable by reading; this makes it a
    # build failure instead.
    assert declared.group(1) == __version__


def test_every_adr_referenced_by_the_master_document_exists():
    base = ROOT / "design-system" / "screen-translator"
    master = (base / "MASTER.md").read_text(encoding="utf-8")

    for link in re.findall(r"\]\((decisions/[\w-]+\.md)\)", master):
        assert (base / link).is_file(), link
