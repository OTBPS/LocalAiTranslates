"""Freeze known hallucination cases as a detector regression set.

`eval-en-news-018` is a real cross-record hallucination: the 14B model emitted
a translation of an unrelated Japanese news item in its slot. Because the case
is now public it can never sit in an independent gold set, but it must never
silently stop being detected either.

The set pairs positive cases (must be flagged) with negative controls that are
badly translated yet still on topic (must NOT be flagged), so tightening or
loosening the detector both show up.

    python -m scripts.training.build_hallucination_regression
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.training.training_paths import workspace_path

# (run, record id, expected flag, why)
CASES = [
    (
        "baseline-v1/qwen3-14b-q5-k-m",
        "eval-en-news-018",
        True,
        "14B emitted an unrelated Japanese football item in a Ryder Cup slot; "
        "no source anchor (2018/16.5/10.5) survives and another record's reference explains it better",
    ),
    (
        "baseline-v1/qwen3-8b-q5-k-m",
        "eval-ja-news-016",
        False,
        "negative control: severely mistranslated but on topic (same match, players and penalty claims); "
        "anchors are lost yet no other reference explains it better",
    ),
    (
        "baseline-v1/qwen3-8b-q5-k-m",
        "eval-en-news-018",
        False,
        "negative control: the same source translated correctly by 8B",
    ),
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=workspace_path("runs"))
    parser.add_argument("--output-dir", type=Path, default=workspace_path("data/regression/hallucination-v1"))
    args = parser.parse_args(argv)

    cache: dict[str, dict[str, dict]] = {}
    records = []
    for run, record_id, expected, reason in CASES:
        if run not in cache:
            path = args.runs / run / "predictions.jsonl"
            cache[run] = {
                row["id"]: row
                for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            }
        row = cache[run].get(record_id)
        if row is None:
            raise RuntimeError(f"{record_id} not found in {run}")
        records.append(
            {
                "case_id": f"halluc-{len(records):03d}",
                "origin_run": run,
                "record_id": record_id,
                "source_language": row["source_language"],
                "target_language": row.get("target_language", "zh-Hans"),
                "domain": row["domain"],
                "source_text": row["source_text"],
                "reference_text": row["reference_text"],
                "candidate_text": row["translation"],
                "expect_semantic_unrelated": expected,
                "reason": reason,
                "provenance": row.get("provenance", {}),
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset = args.output_dir / "cases.jsonl"
    dataset.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "dataset_name": "screen-translator-hallucination-regression-v1",
        "purpose": "keep the per-sample semantic-unrelated detector honest in both directions",
        "cases": len(records),
        "positive_cases": sum(r["expect_semantic_unrelated"] for r in records),
        "negative_controls": sum(not r["expect_semantic_unrelated"] for r in records),
        "dataset_sha256": file_sha256(dataset),
        "public": True,
        "gold_use_prohibited": True,
        "gold_use_prohibited_reason": (
            "these cases are published and analysed, so they can no longer serve as blind gold items"
        ),
        "training_use_prohibited": True,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
