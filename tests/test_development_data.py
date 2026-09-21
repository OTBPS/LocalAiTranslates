from scripts.training.build_development_set import build, source_key
from scripts.training.build_preference_mining_set import build as build_mining


def row(record_id, language, source, target="中文"):
    return {
        "id": record_id,
        "source_language": language,
        "source_text": source,
        "human_reference": target,
        "provenance": {"dataset": "fixture"},
    }


def test_development_set_excludes_training_and_evaluation_sources():
    rejected = [
        row("train-en-1", "en", "unused"),
        row("train-en-2", "en", "trained"),
        row("train-en-3", "en", "evaluated"),
        row("train-ja-1", "ja", "未使用"),
        row("train-ko-1", "ko", "사용하지 않음"),
    ]
    result = build(
        rejected,
        [row("train-x", "en", "trained")],
        [{**row("eval-x", "en", "evaluated"), "reference_text": "中文"}],
        per_language=1,
        seed=1,
    )

    assert len(result) == 3
    english = next(item for item in result if item["source_language"] == "en")
    assert english["source_text"] == "unused"
    assert english["training_use_prohibited"] is True
    assert source_key(english) not in {("en", "trained"), ("en", "evaluated")}


def test_preference_mining_subset_is_balanced():
    rows = [
        row(f"train-{language}-{index}", language, f"{language} source {index}")
        for language in ("en", "ja", "ko")
        for index in range(3)
    ]

    result = build_mining(
        rows,
        per_language=2,
        seed=3,
        excluded=[{"source_language": "en", "source_text": "en source 0"}],
    )

    assert len(result) == 6
    counts = {
        language: sum(item["source_language"] == language for item in result)
        for language in ("en", "ja", "ko")
    }
    assert counts == {"en": 2, "ja": 2, "ko": 2}
    assert all(item["held_out"] is False for item in result)
    assert all(item["source_text"] != "en source 0" for item in result)
