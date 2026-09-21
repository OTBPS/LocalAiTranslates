"""Create a reproducible, language-stratified sample for teacher-data review."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

LANGUAGES = ("en", "ja", "ko")


def select_sample(rows: list[dict], per_language: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    selected = []
    for language in LANGUAGES:
        candidates = [row for row in rows if row["source_language"] == language]
        if len(candidates) < per_language:
            raise ValueError(f"not enough {language} rows for an audit sample")
        rng.shuffle(candidates)
        for row in candidates[:per_language]:
            selected.append(
                {
                    "id": row["id"],
                    "source_language": language,
                    "source_text": row["source_text"],
                    "human_reference": row["human_reference"],
                    "teacher_translation": row["teacher_translation"],
                    "automatic_chrf": row.get("chrf"),
                    "review_status": "pending",
                    "review_issue": None,
                    "review_notes": "",
                }
            )
    return sorted(selected, key=lambda row: (row["source_language"], row["id"]))


def read_rows(data_dir: Path) -> list[dict]:
    blocks = data_dir / "teacher_blocks.jsonl"
    if blocks.exists():
        return [json.loads(line) for line in blocks.read_text(encoding="utf-8").splitlines()]
    states = data_dir / "batch_state.jsonl"
    if not states.exists():
        raise FileNotFoundError("neither teacher_blocks.jsonl nor batch_state.jsonl exists")
    return [
        row
        for line in states.read_text(encoding="utf-8").splitlines()
        for row in json.loads(line)["accepted"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-language", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260925)
    args = parser.parse_args()

    sample = select_sample(read_rows(args.data_dir), args.per_language, args.seed)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sample)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "records": len(sample),
        "languages": dict(sorted(Counter(row["source_language"] for row in sample).items())),
        "seed": args.seed,
        "review_status": "pending",
        "sample_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_name("audit_sample_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
