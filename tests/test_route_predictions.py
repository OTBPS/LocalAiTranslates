import pytest

from scripts.training.route_predictions import route_rows


def row(record_id, language, translation):
    return {
        "id": record_id,
        "source_language": language,
        "source_text": f"source-{record_id}",
        "reference_text": f"reference-{record_id}",
        "translation": translation,
    }


def test_routes_only_configured_languages_and_preserves_order():
    primary = [row("en-1", "en", "fast"), row("ja-1", "ja", "fast-ja")]
    fallback = [row("ja-1", "ja", "quality-ja"), row("en-1", "en", "quality")]

    result = route_rows(primary, fallback, {"ja", "ko"})

    assert [item["id"] for item in result] == ["en-1", "ja-1"]
    assert [item["translation"] for item in result] == ["fast", "quality-ja"]
    assert [item["route"] for item in result] == ["primary", "fallback"]


def test_rejects_mismatched_prediction_sets():
    with pytest.raises(ValueError, match="IDs differ"):
        route_rows([row("en-1", "en", "fast")], [], {"ko"})
