from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_full_installer_shortcuts_explicitly_open_settings():
    script = (ROOT / "installer.iss").read_text(encoding="utf-8")
    shortcut_lines = [line for line in script.splitlines() if line.startswith("Name: \"")]
    app_shortcuts = [line for line in shortcut_lines if "{#ProductExe}" in line]
    assert len(app_shortcuts) == 2
    assert all('Parameters: "--show-settings"' in line for line in app_shortcuts)
    assert all(r'IconFilename: "{app}\{#ProductIcon}"' in line for line in app_shortcuts)
    assert "ChangesAssociations=yes" in script


def test_incremental_installer_updates_shortcuts_without_forcing_desktop_icon():
    script = (ROOT / "installer.update.iss").read_text(encoding="utf-8")
    assert 'Parameters: "--show-settings"' in script
    desktop_line = next(
        line for line in script.splitlines() if line.startswith('Name: "{autodesktop}')
    )
    assert "Check: ExistingDesktopShortcut" in desktop_line
    assert r'IconFilename: "{app}\{#ProductIcon}"' in desktop_line
    assert "ChangesAssociations=yes" in script
    assert "function ExistingDesktopShortcut(): Boolean;" in script
