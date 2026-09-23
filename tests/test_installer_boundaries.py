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
