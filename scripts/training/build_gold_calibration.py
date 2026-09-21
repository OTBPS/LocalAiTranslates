"""Build the gold calibration set used to validate the automatic judge.

This is **not a release gold set**. It currently carries only the general-text
layer, drawn from FLORES-200. The application, long-document and adversarial
layers still need licensed material with existing human references (or a human
source text translated independently by a second human), and until they exist
the set stays `provisional` and cannot lift the production release block.

Because FLORES-200 is a public benchmark, its results are reported under their
own key so pretraining contamination cannot inflate a headline number.

    python -m scripts.training.build_gold_calibration --direction en-zh --records 40 \\
        --output-dir D:\\AI\\Training\\screen-translator\\data\\gold\\calibration-v0\\en-zh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from scripts.training.training_paths import workspace_path

FLORES = "FLORES-200"
FLORES_LICENSE = "CC-BY-SA-4.0"
DIRECTIONS = {"en-zh": ("en", "zh-Hans"), "zh-en": ("zh-Hans", "en")}
# Layers this builder cannot fill yet; recorded so the gap is never implicit.
PENDING_LAYERS = {
    "application_ui_game_dialogue": 20,
    "long_document_continuous": 20,
    "adversarial_format": 20,
}


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_flores(cache: Path) -> list[dict]:
    """Return aligned en/zh rows with their FLORES metadata."""
    rows = []
    for split, suffix in (("dev", "dev"), ("devtest", "devtest")):
        english = (cache / split / f"eng_Latn.{suffix}").read_text(encoding="utf-8").splitlines()
        chinese = (cache / split / f"zho_Hans.{suffix}").read_text(encoding="utf-8").splitlines()
        meta_lines = (cache / f"metadata_{split}.tsv").read_text(encoding="utf-8").splitlines()
        header = meta_lines[0].split("\t")
        meta = [dict(zip(header, line.split("\t"), strict=False)) for line in meta_lines[1:]]
        if not (len(english) == len(chinese) == len(meta)):
            raise RuntimeError(f"FLORES {split} is not aligned with its metadata")
        for index, (en, zh, info) in enumerate(zip(english, chinese, meta, strict=True)):
            if en.strip() and zh.strip():
                rows.append(
                    {
                        "split": split,
                        "line_index": index,
                        "en": en.strip(),
                        "zh-Hans": zh.strip(),
                        "url": info.get("URL", ""),
                        "flores_domain": info.get("domain", ""),
                        "topic": info.get("topic", ""),
                    }
                )
    return rows


def existing_texts(root: Path) -> set[str]:
    seen: set[str] = set()
    patterns = ("data/eval/*/*.jsonl", "data/dev/*/*.jsonl", "data/train/*/teacher_blocks.jsonl",
                "fixtures/*.json")
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                for case in json.loads(text):
                    for value in case.values():
                        if isinstance(value, str) and len(normalize(value)) >= 12:
                            seen.add(normalize(value))
                continue
            for line in text.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                for key in ("source_text", "reference_text"):
                    value = row.get(key)
                    if isinstance(value, str):
                        for piece in value.split("\n"):
                            if len(normalize(piece)) >= 12:
                                seen.add(normalize(piece))
    return seen


def build(args) -> tuple[list[dict], dict]:
    source_language, target_language = DIRECTIONS[args.direction]
    pool = load_flores(args.flores_dir)
    taken = existing_texts(args.workspace)
    for path in args.exclude:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                for key in ("source_text", "reference_text"):
                    if isinstance(row.get(key), str):
                        taken.add(normalize(row[key]))

    usable = [
        row for row in pool
        if normalize(row["en"]) not in taken and normalize(row["zh-Hans"]) not in taken
    ]
    # Balance across the three FLORES domains so one genre cannot dominate.
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for row in usable:
        by_domain[row["flores_domain"]].append(row)
    rng = random.Random(args.seed)
    for rows in by_domain.values():
        rng.shuffle(rows)

    domains = sorted(by_domain)
    selected: list[dict] = []
    cursor = 0
    while len(selected) < args.records and any(by_domain[d] for d in domains):
        domain = domains[cursor % len(domains)]
        if by_domain[domain]:
            selected.append(by_domain[domain].pop())
        cursor += 1

    records = []
    for ordinal, row in enumerate(selected):
        records.append(
            {
                "id": f"goldcal-{args.direction}-flores-{ordinal:03d}",
                "source_language": source_language,
                "target_language": target_language,
                "domain": "general_flores",
                "source_text": row[source_language],
                "reference_text": row[target_language],
                "held_out": True,
                "training_use_prohibited": True,
                "provenance": {
                    "dataset": FLORES,
                    "license": FLORES_LICENSE,
                    "split": row["split"],
                    "original_id": f"{row['split']}:{row['line_index']}",
                    "line_index": row["line_index"],
                    "url": row["url"],
                    "flores_domain": row["flores_domain"],
                    "topic": row["topic"],
                },
            }
        )

    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate record ids")
    for record in records:
        if normalize(record["source_text"]) in taken:
            raise RuntimeError(f"{record['id']} overlaps an existing dataset")

    manifest = {
        "schema_version": 1,
        "dataset_name": f"screen-translator-gold-calibration-{args.direction}",
        "purpose": "validate the automatic judge against human annotation",
        "release_gold": False,
        "provisional": True,
        "provisional_reason": (
            "only the general-text layer exists; application, continuous long-document and "
            "adversarial layers still need licensed material with human references"
        ),
        "direction": args.direction,
        "source_language": source_language,
        "target_language": target_language,
        "records": len(records),
        "requested_records": args.records,
        "seed": args.seed,
        "held_out": True,
        "training_use_prohibited": True,
        "usage_restriction": (
            "gold calibration only; must not inform training, prompts, hyperparameters, "
            "error-driven data construction or candidate selection"
        ),
        "licenses": sorted({record["provenance"]["license"] for record in records}),
        "layers_present": {"general_flores": len(records)},
        "layers_pending": PENDING_LAYERS,
        "reporting_note": (
            "FLORES-200 is a public benchmark; report its numbers separately from product "
            "evaluation sets because pretraining contamination can inflate them"
        ),
        "flores_domains": dict(sorted(Counter(r["provenance"]["flores_domain"] for r in records).items())),
        "source_manifest": str((args.flores_dir / "manifest.json").resolve()),
        "excluded_from": "data/eval/*, data/dev/*, data/train/*/teacher_blocks.jsonl, fixtures/*.json",
    }
    return records, manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--direction", choices=tuple(DIRECTIONS), required=True)
    parser.add_argument("--records", type=int, default=40)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--flores-dir", type=Path, default=workspace_path("cache/flores200"))
    parser.add_argument("--workspace", type=Path, default=workspace_path(""))
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    records, manifest = build(args)
    if len(records) < args.records:
        manifest["shortfall"] = args.records - len(records)
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=False)
    dataset_path = args.output_dir / "gold.jsonl"
    dataset_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8"
    )
    manifest["dataset_sha256"] = file_sha256(dataset_path)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
