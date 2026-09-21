from scripts.training.judge_predictions import aggregate, groups


def test_groups_keeps_order_and_remainder():
    assert list(groups(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def test_aggregate_uses_score_three_as_usable():
    rows = [
        {"judge_score": 4, "judge_issue": "none"},
        {"judge_score": 3, "judge_issue": "none"},
        {"judge_score": 2, "judge_issue": "omission"},
    ]
    report = aggregate(rows)
    assert report["usable_rate"] == 0.6667
    assert report["mean_score"] == 3.0
    assert report["issues"] == {"none": 2, "omission": 1}
