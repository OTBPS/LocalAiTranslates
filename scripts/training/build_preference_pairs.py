"""Build train-only chosen/rejected pairs from judged student errors."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.translation_engine import build_translation_system_prompt


def normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def source_key(row: dict) -> tuple[str, str]:
    return row["source_language"], normalized(row["source_text"])


def build(rows: list[dict], prohibited: list[dict]) -> list[dict]:
    prohibited_keys = {source_key(row) for row in prohibited}
    pairs = []
    for row in rows:
        if source_key(row) in prohibited_keys:
            raise ValueError(f"preference source overlaps held-out data: {row['id']}")
        chosen = row["reference_text"].strip()
        rejected = row["translation"].strip()
        if (
            row.get("judge_score", 4) >= 4
            or row.get("judge_issue") == "none"
            or not chosen
            or not rejected
            or normalized(chosen) == normalized(rejected)
        ):
            continue
        record_id = row["id"]
        prompt = [
            {
                "role": "system",
                "content": build_translation_system_prompt(
                    row["source_language"], row["target_language"]
                ),
            },
            {
                "role": "user",
                "content": json.dumps({record_id: row["source_text"]}, ensure_ascii=False),
            },
        ]
        pairs.append(
            {
                "id": record_id,
                "source_language": row["source_language"],
                "prompt": prompt,
                "chosen": json.dumps({record_id: chosen}, ensure_ascii=False),
                "rejected": json.dumps({record_id: rejected}, ensure_ascii=False),
                "judge_score": row["judge_score"],
                "judge_issue": row["judge_issue"],
            }
        )
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judged", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.judged.read_text(encoding="utf-8").splitlines()]
    prohibited = [
        json.loads(line)
        for path in (args.evaluation, args.development)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    pairs = build(rows, prohibited)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "pairs": len(pairs),
        "languages": dict(sorted(Counter(row["source_language"] for row in pairs).items())),
        "issues": dict(sorted(Counter(row["judge_issue"] for row in pairs).items())),
        "scores": dict(sorted(Counter(str(row["judge_score"]) for row in pairs).items())),
        "pairs_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "held_out_overlap": 0,
    }
    args.output.with_name("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
