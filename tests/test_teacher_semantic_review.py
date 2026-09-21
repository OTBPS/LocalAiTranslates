import pytest

from scripts.training.filter_teacher_semantic_review import select_reviewed_rows
from scripts.training.prepare_teacher_semantic_review import (
    assert_no_held_out_overlap,
    sample_balanced,
    to_predictions,
)


def teacher_row(record_id, language, source="source"):
    return {
        "id": record_id,
        "source_language": language,
        "target_language": "zh-Hans",
        "source_text": source,
        "human_reference": "人工参考",
        "teacher_translation": "教师译文",
        "provenance": {"dataset": "fixture"},
    }


def test_balanced_sample_is_stable_and_predictions_use_teacher_translation():
    rows = [
        teacher_row(f"{language}-{index}", language, f"{language} {index}")
        for language in ("en", "ja", "ko")
        for index in range(4)
    ]

    first = sample_balanced(rows, per_language=2, seed=42)
    second = sample_balanced(rows, per_language=2, seed=42)
    predictions = to_predictions(first)

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert len(first) == 6
    assert all(row["translation"] == "教师译文" for row in predictions)
    assert all(row["reference_text"] == "人工参考" for row in predictions)


def test_balanced_sample_rejects_short_language_pool():
    with pytest.raises(ValueError, match="not enough en rows"):
        sample_balanced([teacher_row("en-1", "en")], per_language=2, seed=1)


def test_semantic_sample_rejects_held_out_overlap():
    rows = [teacher_row("en-1", "en", "Open settings")]
    held_out = [{"source_language": "en", "source_text": " open   SETTINGS "}]

    with pytest.raises(ValueError, match="overlaps held-out"):
        assert_no_held_out_overlap(rows, held_out)


def test_filter_keeps_only_unchanged_score_four_rows():
    source = [teacher_row("a", "en"), teacher_row("b", "ja")]
    reviewed = [
        {"id": "a", "translation": "教师译文", "judge_score": 4, "judge_issue": "none"},
        {
            "id": "b",
            "translation": "教师译文",
            "judge_score": 3,
            "judge_issue": "mistranslation",
        },
    ]

    accepted, rejected = select_reviewed_rows(source, reviewed, minimum_score=4)

    assert [row["id"] for row in accepted] == ["a"]
    assert [row["id"] for row in rejected] == ["b"]


def test_filter_rejects_changed_translation():
    source = [teacher_row("a", "en")]
    reviewed = [
        {"id": "a", "translation": "被修改", "judge_score": 4, "judge_issue": "none"}
    ]

    with pytest.raises(ValueError, match="translation changed"):
        select_reviewed_rows(source, reviewed, minimum_score=4)
