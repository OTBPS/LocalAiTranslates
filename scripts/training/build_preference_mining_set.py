"""Select a small train-only subset for student-error preference mining."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

LANGUAGES = ("en", "ja", "ko")


def source_key(row: dict) -> tuple[str, str]:
    return row["source_language"], " ".join(row["source_text"].split()).casefold()


def build(
    rows: list[dict],
    per_language: int,
    seed: int,
    excluded: list[dict] | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    excluded_keys = {source_key(row) for row in (excluded or [])}
    selected = []
    for language in LANGUAGES:
        unique = {}
        for row in rows:
            if row["source_language"] != language:
                continue
            key = source_key(row)
            if key not in excluded_keys:
                unique.setdefault(key, row)
        candidates = list(unique.values())
        rng.shuffle(candidates)
        if len(candidates) < per_language:
            raise ValueError(f"not enough {language} mining records")
        for row in candidates[:per_language]:
            selected.append(
                {
                    "id": row["id"],
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "domain": "preference_mining",
                    "source_text": row["source_text"],
                    "reference_text": row["human_reference"],
                    "held_out": False,
                    "provenance": row["provenance"],
                }
            )
    return sorted(selected, key=lambda row: (row["source_language"], row["id"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-language", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--exclude", type=Path)
    args = parser.parse_args()

    source_rows = [
        json.loads(line) for line in args.source.read_text(encoding="utf-8").splitlines()
    ]
    excluded_rows = (
        [json.loads(line) for line in args.exclude.read_text(encoding="utf-8").splitlines()]
        if args.exclude
        else None
    )
    rows = build(source_rows, args.per_language, args.seed, excluded_rows)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "records": len(rows),
        "languages": dict(sorted(Counter(row["source_language"] for row in rows).items())),
        "dataset_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "training_only": True,
        "seed": args.seed,
    }
    args.output.with_name("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
