"""判官汇总必须如实记录实际运行的判官与批次参数。"""

import pytest

from scripts.training.compare_predictions import summarize as compare_summarize
from scripts.training.judge_predictions import summarize as judge_summarize


def row(record_id, language="en", domain="news_web", score=4, issue="none", target="zh-Hans"):
    return {
        "id": record_id,
        "source_language": language,
        "target_language": target,
        "domain": domain,
        "judge_score": score,
        "judge_issue": issue,
    }


def test_summary_records_the_judge_that_actually_ran():
    report = judge_summarize([row("1")], 1.0, judge_model="qwen3-8b-q5-k-m")

    assert report["judge_model"] == "qwen3-8b-q5-k-m"


def test_summary_defaults_to_the_fourteen_b_judge():
    assert judge_summarize([row("1")], 1.0)["judge_model"] == "qwen3-14b-q5-k-m"


def test_summary_records_batch_size_seed_and_shuffle_for_variance_runs():
    report = judge_summarize([row("1")], 1.0, batch_size=20, seed=7, shuffled=True)

    assert report["judge_batch_size"] == 20
    assert report["judge_seed"] == 7
    assert report["judge_shuffled"] is True


def test_provisional_stays_true_unless_explicitly_cleared():
    assert judge_summarize([row("1")], 1.0)["judge_is_provisional"] is True
    assert judge_summarize([row("1")], 1.0, provisional=False)["judge_is_provisional"] is False


def test_summary_reports_each_translation_direction_separately():
    rows = [
        row("1", language="en", target="zh-Hans", score=4),
        row("2", language="en", target="zh-Hans", score=1),
        row("3", language="zh-Hans", target="en", score=4),
        row("4", language="zh-Hans", target="en", score=4),
    ]

    report = judge_summarize(rows, 1.0)

    assert set(report["by_direction"]) == {"en->zh-Hans", "zh-Hans->en"}
    assert report["by_direction"]["en->zh-Hans"]["usable_rate"] == 0.5
    assert report["by_direction"]["zh-Hans->en"]["usable_rate"] == 1.0
    assert report["usable_rate"] == 0.75


def test_direction_falls_back_to_chinese_for_legacy_rows_without_target():
    legacy = {k: v for k, v in row("1").items() if k != "target_language"}

    assert set(judge_summarize([legacy], 1.0)["by_direction"]) == {"en->zh-Hans"}


@pytest.mark.parametrize("model", ["qwen3-8b-q5-k-m", "qwen3-4b-instruct-2507-q8-0"])
def test_paired_comparison_also_records_its_judge(model):
    rows = [
        {
            "id": "1",
            "source_language": "en",
            "domain": "news_web",
            "winner": "left",
            "left_score": 4,
            "right_score": 2,
            "left_slot": "A",
        }
    ]

    report = compare_summarize(rows, 1.0, "base", "candidate", judge_model=model)

    assert report["judge_model"] == model
    assert report["judge_is_provisional"] is True
