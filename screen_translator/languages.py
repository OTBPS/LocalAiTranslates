"""The language pair, and what is known about the text on screen.

Two facts belong together and used to be three attributes and five methods
on the controller: the configured pair, and the language OCR actually
detected when the source is set to automatic. Reading one without the
other is how the tray, the overlay and the settings window managed to
disagree about what was being translated.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from .config_store import ConfigStore
from .core import (
    LANGUAGE_NAMES,
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
    swap_language_pair,
)
from .feedback import Occupancy


class LanguageService(QObject):
    """The configured pair plus the detected source, as one readable state."""

    changed = Signal()
    # The OCR weights are per-language, so a new source invalidates them.
    source_changed = Signal()

    def __init__(
        self,
        configuration: ConfigStore,
        occupancy: Callable[[], Occupancy] = Occupancy,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._configuration = configuration
        self._occupancy = occupancy
        self.detected: str | None = None

    @property
    def _config(self):
        return self._configuration.current

    def describe(self) -> str:
        """The pair in words, naming the detected language when there is one."""
        source = LANGUAGE_NAMES[self._config.source_language]
        if self._config.source_language == "auto" and self.detected:
            source += f"（{LANGUAGE_NAMES[self.detected]}）"
        return f"{source} → {LANGUAGE_NAMES[self._config.target_language]}"

    def detect(self, language: str) -> bool:
        if language not in TARGET_LANGUAGES:
            return False
        self.detected = language
        self.changed.emit()
        return True

    def set_pair(self, source_language: str, target_language: str) -> bool:
        if self._occupancy().busy:
            return False
        if source_language not in SOURCE_LANGUAGES or target_language not in TARGET_LANGUAGES:
            return False
        if (
            source_language == self._config.source_language
            and target_language == self._config.target_language
        ):
            return True
        source_was = self._config.source_language
        # The store announces the change; nothing reloads a whole form to
        # stay in step, which used to discard every unsaved edit in it.
        self._configuration.update(
            source_language=source_language, target_language=target_language
        )
        if source_language != source_was:
            self.detected = None
            self.source_changed.emit()
        self.changed.emit()
        return True

    def swappable(self) -> tuple[str, str] | None:
        """The reversed pair, or None when reversing makes no sense.

        Automatic detection has nothing to reverse until one capture has
        told us what the source actually was.
        """
        return swap_language_pair(
            self._config.source_language, self._config.target_language, self.detected
        )

    def swap(self) -> bool:
        pair = self.swappable()
        return bool(pair) and self.set_pair(*pair)
