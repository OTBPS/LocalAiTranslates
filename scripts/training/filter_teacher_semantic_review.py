"""Build an SFT dataset from teacher rows that passed semantic review."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.training.merge_teacher_data import build_conversations


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def select_reviewed_rows(
    source_rows: list[dict], reviewed_rows: list[dict], minimum_score: int
) -> tuple[list[dict], list[dict]]:
    source_by_id = {row["id"]: row for row in source_rows}
    if len(source_by_id) != len(source_rows):
        raise ValueError("duplicate source IDs")
    reviewed_by_id = {row["id"]: row for row in reviewed_rows}
    if len(reviewed_by_id) != len(reviewed_rows):
        raise ValueError("duplicate reviewed IDs")

    accepted, rejected = [], []
    for record_id, reviewed in reviewed_by_id.items():
        if record_id not in source_by_id:
            raise ValueError(f"reviewed ID missing from source: {record_id}")
        source = source_by_id[record_id]
        if reviewed.get("translation") != source.get("teacher_translation"):
            raise ValueError(f"reviewed translation changed for {record_id}")
        score = reviewed.get("judge_score")
        issue = reviewed.get("judge_issue")
        enriched = {
            **source,
            "semantic_judge_score": score,
            "semantic_judge_issue": issue,
        }
        if isinstance(score, int) and score >= minimum_score and issue == "none":
            accepted.append(enriched)
        else:
            rejected.append({**enriched, "rejection_reasons": ["semantic_review"]})
    accepted.sort(key=lambda row: (row["source_language"], row["id"]))
    rejected.sort(key=lambda row: (row["source_language"], row["id"]))
    return accepted, rejected


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-score", type=int, default=4)
    parser.add_argument("--max-blocks", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=2400)
    args = parser.parse_args()
    if not 0 <= args.minimum_score <= 4:
        parser.error("--minimum-score must be between 0 and 4")

    source_rows = read_jsonl(args.source)
    reviewed_rows = read_jsonl(args.reviewed)
    accepted, rejected = select_reviewed_rows(
        source_rows, reviewed_rows, args.minimum_score
    )
    conversations = build_conversations(accepted, args.max_blocks, args.max_chars)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    accepted_path = args.output_dir / "teacher_blocks.jsonl"
    rejected_path = args.output_dir / "rejected.jsonl"
    messages_path = args.output_dir / "sft_messages.jsonl"
    write_jsonl(accepted_path, accepted)
    write_jsonl(rejected_path, rejected)
    write_jsonl(messages_path, conversations)
    manifest = {
        "schema_version": 1,
        "source": str(args.source.resolve()),
        "source_sha256": file_sha256(args.source),
        "reviewed": str(args.reviewed.resolve()),
        "reviewed_sha256": file_sha256(args.reviewed),
        "minimum_score": args.minimum_score,
        "reviewed_records": len(reviewed_rows),
        "accepted_blocks": len(accepted),
        "rejected_blocks": len(rejected),
        "conversations": len(conversations),
        "languages": dict(sorted(Counter(row["source_language"] for row in accepted).items())),
        "scores": dict(sorted(Counter(row["judge_score"] for row in reviewed_rows).items())),
        "issues": dict(sorted(Counter(row["judge_issue"] for row in reviewed_rows).items())),
        "teacher_blocks_sha256": file_sha256(accepted_path),
        "sft_messages_sha256": file_sha256(messages_path),
        "rejected_sha256": file_sha256(rejected_path),
        "max_blocks": args.max_blocks,
        "max_chars": args.max_chars,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
