import json

from scripts.training.generate_teacher_data import (
    build_candidates,
    exclude_existing_sources,
    held_out_indexes,
    rejection_reasons,
    target_script_ok,
)
from scripts.training.training_paths import TRAINING_ROOT


def test_candidates_never_use_held_out_ntrex_lines():
    eval_path = TRAINING_ROOT / "data/eval/v1/eval.jsonl"
    candidates = build_candidates(TRAINING_ROOT / "cache/ntrex", eval_path, 30, 7)
    excluded = held_out_indexes(eval_path)
    assert len(candidates) == 30
    assert not {row["provenance"]["line_index"] for row in candidates} & excluded


def test_target_script_filter_rejects_japanese_and_korean_outputs():
    assert target_script_ok("设置已保存。")
    assert not target_script_ok("設定を保存しました。")
    assert not target_script_ok("설정을 저장했습니다.")


def test_filter_accepts_clean_reference_translation():
    record = {
        "source_text": "Installing update… 42% complete.",
        "human_reference": "正在安装更新……已完成 42%。",
    }
    assert rejection_reasons(record, record["human_reference"]) == []


def test_incremental_teacher_data_excludes_existing_sources(tmp_path):
    excluded = tmp_path / "existing.jsonl"
    excluded.write_text(
        json.dumps({"source_text": "  Open   Settings  "}) + "\n", encoding="utf-8"
    )
    records = [
        {"source_text": "open settings"},
        {"source_text": "Save changes"},
    ]

    assert exclude_existing_sources(records, [excluded]) == [{"source_text": "Save changes"}]


def test_eval_manifest_prohibits_training_use():
    manifest = json.loads((TRAINING_ROOT / "data/eval/v1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["training_use_prohibited"] is True
