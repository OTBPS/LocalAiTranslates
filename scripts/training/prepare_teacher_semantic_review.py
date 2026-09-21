"""Create a balanced, held-out-safe sample for semantic teacher-data review."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.training.merge_teacher_data import normalized_source


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sample_balanced(rows: list[dict], per_language: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    selected = []
    for language in ("en", "ja", "ko"):
        candidates = [row for row in rows if row["source_language"] == language]
        if len(candidates) < per_language:
            raise ValueError(
                f"not enough {language} rows: requested {per_language}, found {len(candidates)}"
            )
        rng.shuffle(candidates)
        selected.extend(candidates[:per_language])
    return sorted(selected, key=lambda row: (row["source_language"], row["id"]))


def assert_no_held_out_overlap(rows: list[dict], held_out: list[dict]) -> None:
    held_out_keys = {
        (row["source_language"], normalized_source(row["source_text"])) for row in held_out
    }
    overlap = [
        row["id"]
        for row in rows
        if (row["source_language"], normalized_source(row["source_text"])) in held_out_keys
    ]
    if overlap:
        raise ValueError(f"teacher semantic sample overlaps held-out data: {overlap[0]}")


def to_predictions(rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "domain": "teacher_semantic_review",
            "reference_text": row["human_reference"],
            "translation": row["teacher_translation"],
        }
        for row in rows
    ]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-language", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260927)
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    held_out = [*read_jsonl(args.evaluation), *read_jsonl(args.development)]
    selected = sample_balanced(rows, args.per_language, args.seed)
    assert_no_held_out_overlap(selected, held_out)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    predictions_path = args.output_dir / "predictions.jsonl"
    write_jsonl(predictions_path, to_predictions(selected))
    manifest = {
        "schema_version": 1,
        "input": str(args.input.resolve()),
        "input_sha256": file_sha256(args.input),
        "records": len(selected),
        "per_language": args.per_language,
        "languages": dict(sorted(Counter(row["source_language"] for row in selected).items())),
        "seed": args.seed,
        "held_out_overlap": 0,
        "predictions_sha256": file_sha256(predictions_path),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
