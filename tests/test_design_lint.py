"""Machine guards against drifting back out of the token layer.

`ruff`'s rule sets (E, F, I, B, UP) have nothing for "do not write a
colour here" or "this number should be a token", so these are `ast`
walks in pytest. They look at string and number *constants* only, which
is what keeps them from firing on a comment, a docstring or a URL.

Each one exists because the thing it forbids was in the code before the
refactor, in quantity: 82 colour literals, twelve repeated
`border-radius: 0`, and three object names the stylesheet styled that no
widget set.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "screen_translator"

HEX_COLOUR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")

#: The only file allowed to name a colour.
COLOUR_HOME = "design/primitives.py"

#: Rendering a translated picture must not depend on the theme: the two
#: inks are chosen per image from measured luminance. See
#: `test_graphics_never_imports_the_design_package` for the other half.
COLOUR_EXEMPT = {"graphics.py"}


def sources():
    return sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def constants(tree, kind):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, kind):
            yield node


def test_no_colour_literals_outside_the_primitive_layer():
    offenders = []
    for path in sources():
        name = relative(path)
        if name == COLOUR_HOME or name in COLOUR_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in constants(tree, str):
            if HEX_COLOUR.match(node.value.strip()):
                offenders.append(f"{name}:{node.lineno} {node.value}")
    assert not offenders, (
        "colours belong in design/primitives.py — " + "; ".join(offenders)
    )


LAYOUT_CALLS = {
    "setContentsMargins",
    "setSpacing",
    "setHorizontalSpacing",
    "setVerticalSpacing",
    "setIconSize",
    "setFixedSize",
    "setFixedHeight",
    "setFixedWidth",
    "setMinimumHeight",
}

#: Zero is not a measurement, it is the absence of one.
ALLOWED_LAYOUT_NUMBERS = {0}

#: Files permitted to hold raw geometry, and why.
GEOMETRY_EXEMPT = {
    # The token layer is where numbers are defined.
    "design/metrics.py",
    # Painted chrome over an unknown screenshot; its geometry is pinned
    # for the same reason its palette is.
    "overlay.py",
    "design/overlay.py",
    # Renders into the output picture, not into the interface.
    "graphics.py",
}


def literal_arguments(node):
    for argument in node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, int):
            yield argument.value


def test_layout_metrics_come_from_tokens():
    offenders = []
    for path in sources():
        name = relative(path)
        if name in GEOMETRY_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = getattr(node.func, "attr", None)
            if call not in LAYOUT_CALLS:
                continue
            for value in literal_arguments(node):
                if value not in ALLOWED_LAYOUT_NUMBERS:
                    offenders.append(f"{name}:{node.lineno} {call}({value})")
    assert not offenders, (
        "spacing belongs in design/metrics.py — " + "; ".join(sorted(offenders))
    )


def object_names_set_in_code() -> set[str]:
    found = set()
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "setObjectName":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.add(argument.value)
    return found


def object_names_in_stylesheet() -> set[str]:
    from screen_translator.design import metrics, semantic, typography
    from screen_translator.design.qss import stylesheet

    sheet = stylesheet(semantic.ACTIVE, metrics.ACTIVE, typography.ACTIVE)
    # An id selector always follows a type name (`QLabel#helperText`).
    # The lookbehind is what keeps a colour value out of the result --
    # `#AEAEB2` also starts with a letter.
    return set(re.findall(r"(?<=[A-Za-z])#([A-Za-z][\w-]*)", sheet))


#: Transparent containers. They carry a name so a page can find them
#: and so a future rule has somewhere to attach, but they paint nothing
#: of their own -- their children carry the appearance.
NAMES_WITHOUT_RULES = {
    "appHeader",
    "groupRow",
    "inlineMessage",
    "noticeBanner",
    "settingRow",
}
#: Styled for a widget that a page adds without naming it in code.
RULES_WITHOUT_NAMES: set[str] = set()


def test_object_names_and_stylesheet_rules_agree():
    """Both directions. Either half alone misses the common failures.

    A rule for a name nothing sets is dead style; a name nothing styles
    is a control the author expected to look different and which does
    not. The project had three of the second kind.
    """
    in_code = object_names_set_in_code()
    in_style = object_names_in_stylesheet()

    unstyled = in_code - in_style - NAMES_WITHOUT_RULES
    assert not unstyled, f"objectName set but never styled: {sorted(unstyled)}"

    unused = in_style - in_code - RULES_WITHOUT_NAMES
    assert not unused, f"styled but no widget sets the name: {sorted(unused)}"


def test_no_widget_asks_for_a_drop_shadow():
    """ADR 0004. Per widget, software compositing, drops frames scrolling."""
    offenders = [
        relative(path)
        for path in sources()
        if "QGraphicsDropShadowEffect" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


@pytest.mark.parametrize("name", ["camera", "download", "folder", "swap", "trash"])
def test_every_tintable_icon_declares_current_colour(name):
    markup = (PACKAGE / "assets" / f"{name}.svg").read_text(encoding="utf-8")

    # A baked-in stroke is a black glyph on a dark button: present, and
    # invisible. The family had drifted to two widths and two cap styles.
    assert 'stroke="currentColor"' in markup
    assert not re.search(r'stroke="#[0-9A-Fa-f]{6}"', markup)
    assert 'stroke-width="1.5"' in markup
    assert 'stroke-linecap="round"' in markup


def test_the_stylesheet_referenced_icon_keeps_its_name():
    """`build_update.ps1` uses check.svg as its integrity sentinel.

    Renaming it makes the incremental build throw, which is why the
    dark variant is a second file rather than a rename.
    """
    assert (PACKAGE / "assets" / "check.svg").is_file()
    assert (PACKAGE / "assets" / "check-dark.svg").is_file()
    script = (ROOT / "scripts" / "build_update.ps1").read_text(encoding="utf-8")
    assert "check.svg" in script


def test_the_forwarding_shim_is_gone():
    # Kept only while the pages migrated. Leaving it would preserve two
    # names for every control.
    assert not (PACKAGE / "ui_components.py").exists()
