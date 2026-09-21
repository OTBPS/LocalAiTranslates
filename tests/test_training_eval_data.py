import json
from collections import Counter

from scripts.training.build_eval_set import choose_application_records, validate
from scripts.training.training_paths import TRAINING_ROOT


def test_application_fixture_expands_to_three_languages():
    records = choose_application_records(TRAINING_ROOT / "fixtures/screen_translation_eval.json")
    assert len(records) == 90
    assert Counter(record["source_language"] for record in records) == {"en": 30, "ja": 30, "ko": 30}
    assert all(record["held_out"] for record in records)


def test_full_eval_contract_accepts_expected_distribution():
    records = choose_application_records(TRAINING_ROOT / "fixtures/screen_translation_eval.json")
    for language in ("en", "ja", "ko"):
        for index in range(70):
            records.append({"id": f"eval-{language}-generated-{index}", "source_language": language, "target_language": "zh-Hans", "domain": "long_document" if index < 20 else "news_web", "source_text": "source", "reference_text": "reference", "held_out": True})
    validate(records)


def test_fixture_is_valid_json_and_has_required_keys():
    data = json.loads((TRAINING_ROOT / "fixtures/screen_translation_eval.json").read_text(encoding="utf-8"))
    assert len(data) == 30
    assert all({"domain", "en", "ja", "ko", "zh-Hans"} <= row.keys() for row in data)
