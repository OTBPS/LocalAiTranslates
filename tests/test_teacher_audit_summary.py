import pytest

from scripts.training.summarize_teacher_audit import apply_decisions, summarize


def reviewed(record_id, language, status, issue=None):
    return {
        "id": record_id,
        "source_language": language,
        "review_status": status,
        "review_issue": issue,
    }


def test_summary_requires_every_review_to_be_completed():
    with pytest.raises(ValueError, match="pending"):
        summarize([reviewed("a", "en", "pending")])


def test_summary_reports_language_rates_and_issues():
    report = summarize(
        [
            reviewed("a", "en", "pass"),
            reviewed("b", "en", "fail", "mistranslation"),
            reviewed("c", "ja", "pass"),
            reviewed("d", "ko", "pass"),
        ]
    )

    assert report["pass_rate"] == 0.75
    assert report["issues"] == {"mistranslation": 1}
    assert report["languages"]["en"]["pass_rate"] == 0.5


def test_failed_review_requires_issue():
    with pytest.raises(ValueError, match="review_issue"):
        summarize([reviewed("a", "ko", "fail")])


def test_apply_decisions_requires_exact_id_coverage():
    rows = [reviewed("a", "en", "pending"), reviewed("b", "ja", "pending")]
    decisions = [reviewed("a", "en", "pass"), reviewed("b", "ja", "fail", "omission")]

    result = apply_decisions(rows, decisions)

    assert [row["review_status"] for row in result] == ["pass", "fail"]
    with pytest.raises(ValueError, match="exactly once"):
        apply_decisions(rows, decisions[:1])
