"""Applying a shortcut must never leave the running application lying."""

from types import SimpleNamespace

import pytest

from screen_translator.hotkeys import HotkeyService


class FakeBackend:
    """Stands in for the Win32 registration."""

    def __init__(self, taken=()):
        self.current = None
        self.taken = set(taken)
        self.registered = []
        self.closed = False

    def register(self, sequence):
        if sequence == self.current:
            return
        if sequence in self.taken:
            raise ValueError("该快捷键已被系统或其他应用占用")
        self.registered.append(sequence)
        self.current = sequence

    def close(self):
        self.closed = True


def service(taken=()):
    backend = FakeBackend(taken)
    app = SimpleNamespace(installNativeEventFilter=lambda _filter: None)
    return HotkeyService(app, lambda: None, backend=backend), backend


def test_applying_a_shortcut_reports_the_change_once():
    subject, backend = service()
    seen = []
    subject.changed.connect(seen.append)

    subject.apply("Ctrl+Alt+T")
    subject.apply("Ctrl+Alt+T")

    assert backend.registered == ["Ctrl+Alt+T"]
    assert seen == ["Ctrl+Alt+T"]


def test_a_rejected_shortcut_leaves_the_current_one_in_place():
    subject, _backend = service(taken={"Ctrl+Alt+P"})
    subject.apply("Ctrl+Alt+T")

    with pytest.raises(ValueError):
        subject.apply("Ctrl+Alt+P")

    assert subject.current == "Ctrl+Alt+T"


def test_a_failure_inside_the_block_rolls_the_shortcut_back():
    subject, backend = service()
    subject.apply("Ctrl+Alt+T")

    with pytest.raises(OSError):
        with subject.pending("Ctrl+Alt+J"):
            raise OSError("disk full")

    # The whole point: the application ends up on the shortcut it actually
    # has, and the rollback raised nothing of its own to mask the failure.
    assert subject.current == "Ctrl+Alt+T"
    assert backend.registered == ["Ctrl+Alt+T", "Ctrl+Alt+J", "Ctrl+Alt+T"]


def test_a_successful_block_keeps_the_new_shortcut():
    subject, _backend = service()
    subject.apply("Ctrl+Alt+T")

    with subject.pending("Ctrl+Alt+J"):
        pass

    assert subject.current == "Ctrl+Alt+J"


def test_the_original_failure_survives_a_failed_rollback():
    subject, backend = service()
    subject.apply("Ctrl+Alt+T")

    with pytest.raises(OSError, match="disk full"):
        with subject.pending("Ctrl+Alt+J"):
            # Someone else grabs the old shortcut while we hold the new one.
            backend.taken.add("Ctrl+Alt+T")
            raise OSError("disk full")

    # A rollback that cannot complete must not replace the real error.
    assert subject.current == "Ctrl+Alt+J"


def test_closing_releases_the_registration():
    subject, backend = service()

    subject.close()

    assert backend.closed is True
