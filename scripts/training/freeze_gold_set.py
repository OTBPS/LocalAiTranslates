"""Merge the gold layers into one frozen set per direction.

Verifies the mutually exclusive category quota, re-checks exact and
approximate duplication across every layer, records a digest per source
dataset plus one for the merged file, and keeps public-benchmark records
(FLORES) separable from open-source localisation records so their scores are
never reported as one number.

The merged set stays `release_gold: false` until two independent human
annotations, arbitration and an agreement measurement exist.

    python -m scripts.training.freeze_gold_set --direction en-zh \\
        --part D:\\...\\calibration-v0\\en-zh\\gold.jsonl \\
        --part D:\\...\\layers-v0\\en-zh\\layers.jsonl \\
        --output-dir D:\\...\\gold\\v1\\en-zh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

EXPECTED = {
    "general_flores": 40,
    "long_document": 20,
    "software_ui": 15,
    "game_dialogue": 10,
    "adversarial_format": 15,
}
PUBLIC_BENCHMARK_CORPORA = {"FLORES-200"}


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def shingles(text: str, size: int = 5) -> set[str]:
    key = normalize(text)
    if len(key) <= size:
        return {key} if key else set()
    return {key[index : index + size] for index in range(len(key) - size + 1)}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def corpus_of(record: dict) -> str:
    provenance = record.get("provenance", {})
    return provenance.get("corpus") or provenance.get("dataset") or "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--direction", required=True)
    parser.add_argument("--part", action="append", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--similarity", type=float, default=0.8)
    parser.add_argument("--expect", type=int, default=100)
    args = parser.parse_args(argv)

    records: list[dict] = []
    parts = []
    for path in args.part:
        rows = read_jsonl(path)
        parts.append({"path": str(path.resolve()), "records": len(rows), "sha256": file_sha256(path)})
        records.extend(rows)

    counts = Counter(record["domain"] for record in records)
    if dict(counts) != EXPECTED:
        parser.error(f"category quota mismatch: got {dict(counts)}, expected {EXPECTED}")
    if len(records) != args.expect:
        parser.error(f"expected {args.expect} records, got {len(records)}")

    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        parser.error("duplicate record ids across parts")

    seen_exact: set[str] = set()
    pool: list[set[str]] = []
    for record in records:
        key = normalize(record["source_text"])
        if key in seen_exact:
            parser.error(f"exact duplicate source text in {record['id']}")
        candidate = shingles(record["source_text"])
        for other in pool:
            overlap = len(candidate & other)
            if overlap and overlap / len(candidate | other) >= args.similarity:
                parser.error(f"near-duplicate source text in {record['id']}")
        seen_exact.add(key)
        pool.append(candidate)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    dataset = args.output_dir / "gold.jsonl"
    dataset.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8"
    )

    public = [r for r in records if corpus_of(r) in PUBLIC_BENCHMARK_CORPORA]
    manifest = {
        "schema_version": 1,
        "dataset_name": f"screen-translator-gold-{args.direction}-v1",
        "direction": args.direction,
        "records": len(records),
        "categories": dict(sorted(counts.items())),
        "category_exclusivity": "each record has exactly one primary category plus free-form analysis tags",
        "dataset_sha256": file_sha256(dataset),
        "parts": parts,
        "licenses": dict(sorted(Counter(r["provenance"].get("license", "?") for r in records).items())),
        "corpora": dict(sorted(Counter(corpus_of(r) for r in records).items())),
        "reporting_groups": {
            "public_benchmark": {
                "records": len(public),
                "corpora": sorted({corpus_of(r) for r in public}),
                "note": "report separately; pretraining contamination can inflate these",
            },
            "open_source_localisation": {
                "records": len(records) - len(public),
                "corpora": sorted({corpus_of(r) for r in records if corpus_of(r) not in PUBLIC_BENCHMARK_CORPORA}),
                "note": "report separately from both the public benchmark and the product evaluation sets",
            },
        },
        "analysis_tags": dict(
            sorted(Counter(tag for r in records for tag in r.get("analysis_tags", [])).items())
        ),
        "held_out": True,
        "training_use_prohibited": True,
        "release_gold": False,
        "judge_is_provisional": True,
        "frozen": True,
        "unblock_requirements": [
            "two independent human annotations (no model may substitute)",
            "arbitration of every disputed item",
            "inter-annotator agreement and Cohen's kappa above threshold",
            "model judge agreement with the adjudicated verdict above threshold",
        ],
        "usage_restriction": (
            "gold evaluation only; must not inform training, prompts, hyperparameters, "
            "error-driven data construction or candidate selection"
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
