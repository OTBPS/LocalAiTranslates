"""A configuration written by a newer version has to say so.

Refusing it was already right: loading defaults over someone's settings,
or renaming their file aside, is the silent downgrade the version check
exists to prevent. What was wrong is that the refusal was an unhandled
`ValueError` from inside `Controller.__init__`, so the application died
before `configure_logging` had run -- no window, no dialog, no log line.
For a mechanism whose only job is to say "upgrade the application",
silence is the worst available outcome.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.core import CURRENT_CONFIG_VERSION, Config, ConfigTooNew


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def write(path, **fields):
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_newer_configuration_is_refused_by_name(tmp_path):
    path = write(
        tmp_path / "config.json",
        version=CURRENT_CONFIG_VERSION + 1,
        hotkey="Ctrl+Alt+Q",
    )

    with pytest.raises(ConfigTooNew) as raised:
        Config.load(path)

    assert raised.value.found == CURRENT_CONFIG_VERSION + 1
    assert raised.value.supported == CURRENT_CONFIG_VERSION


def test_the_newer_file_is_left_exactly_where_it_was(tmp_path):
    """The point of refusing. Someone's settings are in that file."""
    path = write(tmp_path / "config.json", version=CURRENT_CONFIG_VERSION + 3, hotkey="Ctrl+Alt+P")
    before = path.read_bytes()

    with pytest.raises(ConfigTooNew):
        Config.load(path)

    assert path.exists(), "the file must not be moved aside"
    assert path.read_bytes() == before, "the file must not be rewritten"
    assert not list(tmp_path.glob("*.corrupt-*")), "this is not corruption"


def test_the_message_names_both_versions_and_what_to_do(tmp_path):
    path = write(tmp_path / "config.json", version=CURRENT_CONFIG_VERSION + 1)

    with pytest.raises(ConfigTooNew) as raised:
        Config.load(path)

    message = str(raised.value)
    assert f"v{CURRENT_CONFIG_VERSION + 1}" in message
    assert f"v{CURRENT_CONFIG_VERSION}" in message
    # An error that states the problem without the remedy leaves the
    # reader stuck, which is the same rule the notice layer follows.
    assert "升级" in message and "备份" in message


def test_it_is_still_a_value_error_for_callers_that_predate_the_name():
    assert issubclass(ConfigTooNew, ValueError)


def test_a_json_decode_error_is_not_mistaken_for_a_future_version(tmp_path):
    # JSONDecodeError subclasses ValueError; ConfigTooNew does too. The
    # two must not be confused in either direction.
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")

    config = Config.load(path)

    assert config.version == CURRENT_CONFIG_VERSION
    assert list(tmp_path.glob("*.corrupt-*")), "damage is backed up and replaced"


@pytest.mark.parametrize("version", ["abc", 0, -1, None, True, 1.5])
def test_a_nonsense_version_is_repaired_rather_than_fatal(tmp_path, version):
    """The other ValueError in `_migrate`, which also used to escape.

    A version that is not a positive integer is damage, not the future,
    so it takes the corruption path instead of stopping the
    application.
    """
    path = write(tmp_path / "config.json", version=version, hotkey="Ctrl+Alt+Q")

    config = Config.load(path)

    assert config.version == CURRENT_CONFIG_VERSION
    assert list(tmp_path.glob("*.corrupt-*"))


def test_the_current_version_still_loads_normally(tmp_path):
    path = write(tmp_path / "config.json", version=CURRENT_CONFIG_VERSION, hotkey="Ctrl+Alt+P")

    config = Config.load(path)

    assert config.hotkey == "Ctrl+Alt+P"
    assert not list(tmp_path.glob("*.corrupt-*"))


def test_startup_reports_the_refusal_instead_of_dying_silently(tmp_path, monkeypatch, qt_app):
    """The half that was missing: somebody has to catch it and speak.

    Driven through the real `main` with a real QApplication, because a
    stand-in crashed inside Qt's font loading -- which is itself a
    reminder that this path is only worth testing end to end.
    """
    from screen_translator import app as application

    path = write(tmp_path / "config.json", version=CURRENT_CONFIG_VERSION + 1)
    monkeypatch.setattr(Config, "path", staticmethod(lambda: path))
    # A second QApplication aborts the process; reuse the fixture's.
    monkeypatch.setattr(application, "QApplication", lambda _argv: qt_app)
    monkeypatch.setattr(application.sys, "argv", ["ScreenTranslator.exe"])

    shown = []
    monkeypatch.setattr(
        application.QMessageBox,
        "critical",
        lambda _parent, title, text: shown.append((title, text)),
    )
    # Reaching any of these would mean the guard came too late.
    monkeypatch.setattr(
        application,
        "InstanceCoordinator",
        lambda _dir: pytest.fail("the single-instance lock must not be taken"),
    )

    assert application.main() == 1

    assert shown, "the user was told nothing at all"
    title, text = shown[0]
    assert title == "屏译"
    assert f"v{CURRENT_CONFIG_VERSION + 1}" in text


def test_a_usable_configuration_does_not_trip_the_guard(tmp_path, monkeypatch, qt_app):
    from screen_translator import app as application

    path = write(tmp_path / "config.json", version=CURRENT_CONFIG_VERSION)
    monkeypatch.setattr(Config, "path", staticmethod(lambda: path))
    monkeypatch.setattr(application, "QApplication", lambda _argv: qt_app)
    monkeypatch.setattr(application.sys, "argv", ["ScreenTranslator.exe"])
    monkeypatch.setattr(
        application.QMessageBox,
        "critical",
        lambda *_args: pytest.fail("a current configuration must not be refused"),
    )
    # Stop right after the guard rather than starting the application.
    monkeypatch.setattr(
        application,
        "InstanceCoordinator",
        lambda _dir: _DeclineSecondInstance(),
    )

    assert application.main() == 0


class _DeclineSecondInstance:
    """Behaves like another copy already holding the lock, so `main`
    returns without building a controller."""

    def acquire_or_notify(self, _command):
        return False
