import json
from pathlib import Path

from scripts.training.audit_training_data import audit


def write_jsonl(path: Path, rows: list[dict]):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def test_audit_accepts_clean_minimal_dataset(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    record = {
        "id": "train-en-1",
        "source_language": "en",
        "source_text": "Save settings.",
        "human_reference": "保存设置。",
        "teacher_translation": "保存设置。",
        "token_preservation": 1.0,
        "chrf": 1.0,
        "provenance": {"dataset": "fixture"},
    }
    write_jsonl(data / "teacher_blocks.jsonl", [record])
    write_jsonl(data / "rejected.jsonl", [])
    write_jsonl(
        data / "sft_messages.jsonl",
        [
            {
                "messages": [
                    {"role": "system", "content": "translate"},
                    {"role": "user", "content": '{"train-en-1": "Save settings."}'},
                    {"role": "assistant", "content": '{"train-en-1": "保存设置。"}'},
                ],
                "metadata": {"block_ids": ["train-en-1"]},
            }
        ],
    )
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, [{"source_text": "Different held-out text."}])
    assert audit(data, eval_path)["passed"] is True
