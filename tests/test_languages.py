"""The language pair, and the detection that only makes sense beside it.

Changing the pair used to reload the whole settings form to keep two combo
boxes in step, which quietly discarded every unsaved edit in the window.
The pair is stored in one place now and announced; nothing reloads.
"""

import os
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from screen_translator.config_store import ConfigStore
from screen_translator.core import Config
from screen_translator.feedback import Occupancy
from screen_translator.languages import LanguageService


def service(source="auto", target="zh-Hans", occupancy=Occupancy):
    written = []
    store = ConfigStore(
        Config(source_language=source, target_language=target), writer=written.append
    )
    return LanguageService(store, occupancy), store, written


def test_the_pair_reaches_disk_without_a_separate_save_step():
    languages, store, written = service()
    changed = Mock()
    languages.changed.connect(changed)

    assert languages.set_pair("zh-Hans", "en") is True

    assert (store.current.source_language, store.current.target_language) == (
        "zh-Hans",
        "en",
    )
    assert len(written) == 1
    changed.assert_called_once()


def test_a_new_source_language_discards_the_previous_detection():
    languages, _store, _written = service()
    languages.detect("ja")
    cold = Mock()
    languages.source_changed.connect(cold)

    languages.set_pair("en", "zh-Hans")

    # A detection describes the last capture, not the next one, and the OCR
    # weights are per-language.
    assert languages.detected is None
    cold.assert_called_once()


def test_changing_only_the_target_keeps_the_engine_warm():
    languages, _store, _written = service(source="en")
    cold = Mock()
    languages.source_changed.connect(cold)

    languages.set_pair("en", "ja")

    cold.assert_not_called()


def test_the_pair_cannot_change_while_a_capture_is_running():
    busy = Occupancy(True, "截图翻译正在进行")
    languages, store, written = service(occupancy=lambda: busy)

    assert languages.set_pair("zh-Hans", "en") is False

    assert store.current.source_language == "auto"
    assert written == []


def test_an_unchanged_pair_is_accepted_without_writing_anything():
    languages, _store, written = service(source="en", target="ja")

    assert languages.set_pair("en", "ja") is True

    assert written == []


def test_an_unknown_language_is_refused():
    languages, _store, written = service()

    assert languages.set_pair("klingon", "zh-Hans") is False
    assert languages.set_pair("en", "auto") is False, "auto is not a target"
    assert written == []


def test_the_detected_language_is_named_beside_the_automatic_source():
    languages, _store, _written = service()

    assert languages.describe() == "自动识别 → 简体中文"

    languages.detect("ja")

    # Without this the tray says "自动识别" for the whole session and the
    # user cannot tell whether detection worked.
    assert languages.describe() == "自动识别（日语） → 简体中文"


def test_a_detection_outside_the_supported_languages_is_ignored():
    languages, _store, _written = service()

    assert languages.detect("klingon") is False
    assert languages.detected is None


def test_swapping_reverses_the_pair():
    languages, store, _written = service(source="en", target="zh-Hans")

    assert languages.swap() is True

    assert (store.current.source_language, store.current.target_language) == (
        "zh-Hans",
        "en",
    )


def test_swapping_an_automatic_source_needs_a_detection_first():
    languages, _store, _written = service()

    assert languages.swappable() is None
    assert languages.swap() is False

    languages.detect("ja")

    # The detected language becomes the target; the old target the source.
    assert languages.swappable() == ("zh-Hans", "ja")


def test_swapping_an_identical_pair_is_refused():
    languages, _store, _written = service(source="en", target="en")

    assert languages.swap() is False
