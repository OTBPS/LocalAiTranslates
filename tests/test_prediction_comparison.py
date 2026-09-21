from scripts.training.compare_predictions import summarize, use_left_as_a


def test_slot_assignment_is_stable_and_balanced():
    first = [use_left_as_a(f"record-{index}") for index in range(100)]
    second = [use_left_as_a(f"record-{index}") for index in range(100)]

    assert first == second
    assert 35 <= sum(first) <= 65


def test_paired_summary_maps_quality_by_language_and_domain():
    rows = [
        {
            "source_language": "en",
            "domain": "software_ui",
            "left_slot": "A",
            "left_score": 4,
            "right_score": 3,
            "winner": "left",
        },
        {
            "source_language": "ko",
            "domain": "news_web",
            "left_slot": "B",
            "left_score": 2,
            "right_score": 4,
            "winner": "right",
        },
        {
            "source_language": "ko",
            "domain": "news_web",
            "left_slot": "A",
            "left_score": 3,
            "right_score": 3,
            "winner": "tie",
        },
    ]

    report = summarize(rows, 1.25, "old", "new")

    assert report["left_wins"] == 1
    assert report["right_wins"] == 1
    assert report["ties"] == 1
    assert report["left_usable_rate"] == 0.6667
    assert report["right_usable_rate"] == 1.0
    assert report["slot_assignment"] == {"A": 2, "B": 1}
    assert report["by_language"]["ko"]["right_wins"] == 1
    assert report["by_domain"]["news_web"]["count"] == 2
