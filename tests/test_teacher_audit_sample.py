import pytest

from scripts.training.sample_teacher_audit import select_sample


def make_row(language, index):
    return {
        "id": f"{language}-{index}",
        "source_language": language,
        "source_text": f"source {index}",
        "human_reference": f"reference {index}",
        "teacher_translation": f"translation {index}",
        "chrf": 0.5,
    }


def test_select_sample_is_balanced_and_reproducible():
    rows = [make_row(language, index) for language in ("en", "ja", "ko") for index in range(5)]

    first = select_sample(rows, per_language=2, seed=7)
    second = select_sample(rows, per_language=2, seed=7)

    assert first == second
    assert [sum(row["source_language"] == language for row in first) for language in ("en", "ja", "ko")] == [2, 2, 2]
    assert all(row["review_status"] == "pending" for row in first)


def test_select_sample_rejects_incomplete_language_pool():
    with pytest.raises(ValueError, match="not enough ja"):
        select_sample([make_row("en", 1)], per_language=1, seed=7)
