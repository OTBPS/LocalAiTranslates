"""Installers must never read, write, or delete the shared model roots."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "installer.iss",
    "installer.client.iss",
    "installer.update.iss",
    "installer.common.iss",
    "installer.versioning.iss",
    "installer.shell.iss",
)
SHARED_ROOTS = (r"D:\AI\Models", r"D:\AI\Training", "AI_MODEL_ROOT", "AI_TRAINING_ROOT")


@pytest.mark.parametrize("name", SCRIPTS)
def test_installers_never_reference_the_shared_model_roots(name):
    script = (ROOT / name).read_text(encoding="utf-8")

    for marker in SHARED_ROOTS:
        assert marker not in script, f"{name} must not reference {marker}"


def test_the_incremental_package_ships_only_the_launcher_and_ui_assets():
    script = (ROOT / "installer.update.iss").read_text(encoding="utf-8")
    sources = re.findall(r'^Source: "([^"]+)"', script, re.MULTILINE)

    assert sources == [
        r"dist\ScreenTranslator\{#ProductExe}",
        r"dist\ScreenTranslator\_internal\screen_translator\assets\*",
    ]
    assert not any(source.endswith((".gguf", ".pdmodel", ".pdiparams")) for source in sources)


def test_the_incremental_build_will_not_guess_which_installs_it_can_patch():
    """`-MinimumBaseVersion` must be supplied, never defaulted.

    The patch delivers the executable and the assets directory and
    nothing else -- the Python runtime, PySide6, PaddleOCR and llama.cpp
    all stay as the base installation left them. So this value is a
    promise about which installations the patch actually fits, and the
    convention every release has followed is "the previous release".

    It used to carry a default of 0.3.0, correct when the script was
    written and stale from the next release onwards, because each build
    passed the value explicitly and nobody exercised the default again.
    Building without the flag then produced a package claiming it could
    patch an installation five releases old -- precisely the outcome the
    value exists to prevent, announced in a manifest as though it had
    been checked.
    """
    script = (ROOT / "scripts" / "build_update.ps1").read_text(encoding="utf-8")

    declaration = re.search(r"\[string\]\$MinimumBaseVersion\s*=\s*\"([^\"]*)\"", script)
    assert declaration, "the parameter is no longer declared as a string"
    assert declaration.group(1) == "", (
        f"a default of {declaration.group(1)!r} lets a bare build ship a false promise"
    )
    # An empty default only helps if something refuses it.
    assert "if (-not $MinimumBaseVersion)" in script, (
        "nothing rejects the empty value, so a bare build would write an empty manifest field"
    )


@pytest.mark.parametrize("name", ("installer.iss", "installer.update.iss"))
def test_installers_delete_nothing_outside_the_application_directory(name):
    script = (ROOT / name).read_text(encoding="utf-8")
    deletions = re.findall(r"^(Type: \S+; Name: \"[^\"]+\")", script, re.MULTILINE)

    for line in deletions:
        target = re.search(r'Name: "([^"]+)"', line).group(1)
        assert target.startswith(("{app}", "{localappdata}", "{userappdata}", "{autodesktop}", "{autoprograms}")), (
            f"{name} deletes an unexpected location: {target}"
        )


def test_the_incremental_installer_keeps_installed_apps_showing_the_real_version():
    # Updating only DisplayVersion left Installed Apps naming whichever
    # version last ran a full installer, so the list disagreed with the
    # application about what was installed.
    script = (ROOT / "installer.update.iss").read_text(encoding="utf-8")
    full = (ROOT / "installer.iss").read_text(encoding="utf-8")
    written = dict(
        re.findall(r'ValueName: "(\w+)"; ValueData: "([^"]+)"', script)
    )

    assert written["DisplayVersion"] == "{#AppVersion}"
    assert written["DisplayName"] == "{#ProductName} {#AppVersion}"
    # Must agree with what a full install would write for the same version.
    assert f"AppVerName={written['DisplayName']}" in full


def test_the_incremental_installer_does_not_create_an_uninstaller_that_could_purge_models():
    script = (ROOT / "installer.update.iss").read_text(encoding="utf-8")

    assert "Uninstallable=no" in script
    assert "CreateUninstallRegKey=no" in script


@pytest.mark.parametrize("name", ("installer.iss", "installer.update.iss"))
def test_the_installer_tells_explorer_the_icon_may_have_changed(name):
    """Otherwise the taskbar keeps the cached artwork until a sign-out.

    The v0.5.1 notes claimed this already happened; it did not. It
    started to matter when the icon was redrawn, which is the one case
    where a stale cache is visible.
    """
    script = (ROOT / name).read_text(encoding="utf-8")

    assert '#include "installer.shell.iss"' in script
    assert "RefreshShellIcons()" in script
    assert "ssPostInstall" in script


def test_the_shell_refresh_is_declared_once_and_shared():
    shared = (ROOT / "installer.shell.iss").read_text(encoding="utf-8")

    # A Win32 declaration duplicated across two scripts is a declaration
    # that will eventually disagree with itself.
    assert "SHChangeNotify@shell32.dll" in shared
    for name in ("installer.iss", "installer.update.iss"):
        script = (ROOT / name).read_text(encoding="utf-8")
        assert "shell32.dll" not in script


BUILD_SCRIPTS = {
    "build.ps1": r"dist\ScreenTranslator",
    "build_update.ps1": r"dist\ScreenTranslator",
    "build_client.ps1": r"dist\ScreenTranslatorClient",
}


@pytest.mark.parametrize(("name", "payload"), BUILD_SCRIPTS.items())
def test_the_build_refuses_to_clean_a_payload_that_is_running(name, payload):
    """--clean deletes the payload, so a running copy of it breaks the build.

    Without the guard that surfaces as a PermissionError twenty frames
    inside shutil, ending in a localised Windows message that names a
    .pyd and not the cause.
    """
    script = (ROOT / "scripts" / name).read_text(encoding="utf-8")

    assert "build.preflight.ps1" in script
    assert "Assert-PayloadNotRunning" in script
    assert payload in script
    # Before the slow work, or the guard saves nothing.
    assert script.index("Assert-PayloadNotRunning") < script.index("PyInstaller")


def test_the_preflight_only_blocks_on_the_payload_not_the_whole_repository():
    shared = (ROOT / "scripts" / "build.preflight.ps1").read_text(encoding="utf-8")

    # A test installation lives under this repository. It holds nothing
    # the build touches, so matching the project root would refuse to
    # build whenever the installed copy sat in the tray.
    assert "$projectRoot" not in shared
    assert "PayloadDirectories" in shared


@pytest.mark.parametrize("name", ("build.ps1", "build_client.ps1", "build_update.ps1", "build.preflight.ps1"))
def test_build_scripts_stay_ascii(name):
    """Windows PowerShell reads a .ps1 as ANSI unless it carries a BOM.

    A non-ASCII literal in one of these does not produce a mangled
    message, it produces a parse error -- which is how this was found.
    """
    raw = (ROOT / "scripts" / name).read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf"), "no BOM is the existing convention"
    offenders = [byte for byte in raw if byte > 0x7F]
    assert not offenders, f"{name} has {len(offenders)} non-ASCII bytes"
