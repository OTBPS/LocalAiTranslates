"""Build a model-selection development set isolated from train and final eval."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

LANGUAGES = ("en", "ja", "ko")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def source_key(row: dict) -> tuple[str, str]:
    return row["source_language"], " ".join(row["source_text"].split()).casefold()


def target_script_ok(text: str) -> bool:
    han = sum("\u4e00" <= char <= "\u9fff" for char in text)
    kana = sum("\u3040" <= char <= "\u30ff" for char in text)
    hangul = sum("\uac00" <= char <= "\ud7af" for char in text)
    return han > 0 and kana + hangul <= max(2, len(text) // 50)


def build(
    rejected: list[dict],
    training: list[dict],
    evaluation: list[dict],
    per_language: int,
    seed: int,
) -> list[dict]:
    prohibited = {source_key(row) for row in training} | {source_key(row) for row in evaluation}
    rng = random.Random(seed)
    selected = []
    for language in LANGUAGES:
        unique = {}
        for row in rejected:
            if row["source_language"] != language or not target_script_ok(row["human_reference"]):
                continue
            key = source_key(row)
            if key not in prohibited:
                unique.setdefault(key, row)
        candidates = list(unique.values())
        rng.shuffle(candidates)
        if len(candidates) < per_language:
            raise ValueError(f"not enough isolated {language} development records")
        for row in candidates[:per_language]:
            selected.append(
                {
                    "id": row["id"].replace("train-", "dev-", 1),
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "domain": "parallel_corpus",
                    "source_text": row["source_text"],
                    "reference_text": row["human_reference"],
                    "held_out": True,
                    "training_use_prohibited": True,
                    "provenance": row["provenance"],
                }
            )
    return sorted(selected, key=lambda row: (row["source_language"], row["id"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rejected", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-language", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()

    rows = build(
        read_jsonl(args.rejected),
        read_jsonl(args.training),
        read_jsonl(args.evaluation),
        args.per_language,
        args.seed,
    )
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "records": len(rows),
        "languages": dict(sorted(Counter(row["source_language"] for row in rows).items())),
        "dataset_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "training_use_prohibited": True,
        "seed": args.seed,
    }
    args.output.with_name("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
