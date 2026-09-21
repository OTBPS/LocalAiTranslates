import pytest

from scripts.training.merge_teacher_data import (
    apply_reference_overrides,
    build_conversations,
    merge_rows,
)


def row(record_id, language, source, translation):
    return {
        "id": record_id,
        "source_language": language,
        "source_text": source,
        "teacher_translation": translation,
    }


def test_merge_rows_deduplicates_normalized_sources():
    first = row("a", "en", "Open  Settings", "打开设置")
    duplicate = row("b", "en", " open settings ", "开启设置")

    merged, dropped = merge_rows([[first], [duplicate]], prohibited=[])

    assert merged == [first]
    assert dropped == 1


def test_merge_rows_rejects_held_out_overlap():
    candidate = row("a", "ko", "설정을 엽니다", "打开设置")
    held_out = {"source_language": "ko", "source_text": "설정을 엽니다"}

    with pytest.raises(ValueError, match="overlaps held-out"):
        merge_rows([[candidate]], prohibited=[held_out])


def test_conversations_preserve_language_and_block_ids():
    rows = [
        row("en-1", "en", "Save", "保存"),
        row("en-2", "en", "Cancel", "取消"),
        row("ja-1", "ja", "保存", "保存"),
    ]

    conversations = build_conversations(rows, max_blocks=2, max_chars=100)

    assert [item["metadata"]["source_language"] for item in conversations] == ["en", "ja"]
    assert conversations[0]["metadata"]["block_ids"] == ["en-1", "en-2"]


def test_reference_override_is_scoped_and_does_not_mutate_input():
    aihub = {
        **row("ko-1", "ko", "안녕하세요", "教师译文"),
        "human_reference": "人工译文",
        "provenance": {"dataset": "AIHub Ko-Zh"},
    }
    other = {
        **row("ko-2", "ko", "감사합니다", "谢谢。"),
        "human_reference": "多谢。",
        "provenance": {"dataset": "Other"},
    }

    updated, count = apply_reference_overrides([aihub, other], {"AIHub Ko-Zh"})

    assert count == 1
    assert updated[0]["teacher_translation"] == "人工译文"
    assert updated[0]["training_target_origin"] == "human_reference"
    assert updated[1]["teacher_translation"] == "谢谢。"
    assert updated[1]["training_target_origin"] == "teacher"
    assert aihub["teacher_translation"] == "教师译文"


def test_reference_override_rejects_missing_reference():
    candidate = {
        **row("ko-1", "ko", "안녕하세요", "教师译文"),
        "provenance": {"dataset": "AIHub Ko-Zh"},
    }

    with pytest.raises(ValueError, match="missing human reference"):
        apply_reference_overrides([candidate], {"AIHub Ko-Zh"})


def test_reference_override_falls_back_when_reference_has_wrong_script():
    candidate = {
        **row("ko-1", "ko", "설정을 엽니다", "打开设置"),
        "human_reference": "설정을 저장했습니다.",
        "provenance": {"dataset": "AIHub Ko-Zh"},
    }

    updated, count = apply_reference_overrides([candidate], {"AIHub Ko-Zh"})

    assert count == 0
    assert updated[0]["teacher_translation"] == "打开设置"
    assert updated[0]["training_target_origin"] == "teacher_reference_script_fallback"
