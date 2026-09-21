import pytest

from screen_translator.translation_engine import build_translation_system_prompt


def test_training_prompt_is_strict_and_disables_thinking():
    prompt = build_translation_system_prompt("ja", "zh-Hans")
    assert "source language is Japanese" in prompt
    assert "Simplified Chinese" in prompt
    assert "ONLY" in prompt
    assert "/no_think" in prompt


def test_repair_prompt_requires_each_id_once():
    prompt = build_translation_system_prompt("en", "zh-Hans", repair=True)
    assert "Every ID must appear exactly once" in prompt


def test_prompt_rejects_unsupported_languages():
    with pytest.raises(ValueError):
        build_translation_system_prompt("fr", "zh-Hans")
