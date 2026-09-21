"""Merge accepted teacher blocks into a deduplicated, auditable SFT dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.translation_engine import build_translation_system_prompt
from scripts.training.generate_teacher_data import target_script_ok


def normalized_source(text: str) -> str:
    return " ".join(text.split()).casefold()


def source_key(row: dict) -> tuple[str, str]:
    return row["source_language"], normalized_source(row["source_text"])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def merge_rows(groups: list[list[dict]], prohibited: list[dict]) -> tuple[list[dict], int]:
    prohibited_keys = {source_key(row) for row in prohibited}
    unique: dict[tuple[str, str], dict] = {}
    dropped = 0
    for rows in groups:
        for row in rows:
            key = source_key(row)
            if key in prohibited_keys:
                raise ValueError(f"teacher source overlaps held-out data: {row['id']}")
            if key in unique:
                dropped += 1
                continue
            unique[key] = row
    merged = sorted(unique.values(), key=lambda row: (row["source_language"], row["id"]))
    return merged, dropped


def apply_reference_overrides(rows: list[dict], datasets: set[str]) -> tuple[list[dict], int]:
    """Use human references as SFT targets for explicitly selected datasets.

    The returned rows are copies so callers can safely reuse the original teacher
    records in another controlled experiment.
    """
    updated = []
    replaced = 0
    for row in rows:
        value = dict(row)
        dataset = row.get("provenance", {}).get("dataset")
        if dataset in datasets:
            reference = row.get("human_reference")
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError(f"missing human reference for {row.get('id', '<unknown>')}")
            reference = reference.strip()
            if target_script_ok(reference):
                value["teacher_translation"] = reference
                value["training_target_origin"] = "human_reference"
                replaced += 1
            else:
                value["training_target_origin"] = "teacher_reference_script_fallback"
        else:
            value["training_target_origin"] = "teacher"
        updated.append(value)
    return updated, replaced


def build_conversations(rows: list[dict], max_blocks: int, max_chars: int) -> list[dict]:
    conversations = []
    for language in ("en", "ja", "ko"):
        batch: list[dict] = []
        chars = 0

        def flush(current_language: str = language) -> None:
            nonlocal batch, chars
            if not batch:
                return
            source = {row["id"]: row["source_text"] for row in batch}
            target = {row["id"]: row["teacher_translation"] for row in batch}
            conversations.append(
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": build_translation_system_prompt(
                                current_language, "zh-Hans"
                            ),
                        },
                        {"role": "user", "content": json.dumps(source, ensure_ascii=False)},
                        {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
                    ],
                    "metadata": {
                        "source_language": current_language,
                        "block_ids": list(source),
                    },
                }
            )
            batch, chars = [], 0

        for row in (item for item in rows if item["source_language"] == language):
            size = len(row["source_text"])
            if batch and (len(batch) >= max_blocks or chars + size > max_chars):
                flush()
            batch.append(row)
            chars += size
        flush()
    return conversations


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, action="append", required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--use-human-reference-for-dataset",
        action="append",
        default=[],
        help="exact provenance.dataset value whose human_reference becomes the SFT target",
    )
    parser.add_argument("--max-blocks", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=2400)
    args = parser.parse_args()

    input_files = [path / "teacher_blocks.jsonl" for path in args.input_dir]
    groups = [read_jsonl(path) for path in input_files]
    prohibited = [*read_jsonl(args.evaluation), *read_jsonl(args.development)]
    rows, duplicates = merge_rows(groups, prohibited)
    override_datasets = set(args.use_human_reference_for_dataset)
    rows, reference_overrides = apply_reference_overrides(rows, override_datasets)
    reference_script_fallbacks = sum(
        row["training_target_origin"] == "teacher_reference_script_fallback" for row in rows
    )
    conversations = build_conversations(rows, args.max_blocks, args.max_chars)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    blocks_path = args.output_dir / "teacher_blocks.jsonl"
    messages_path = args.output_dir / "sft_messages.jsonl"
    rejected_path = args.output_dir / "rejected.jsonl"
    write_jsonl(blocks_path, rows)
    write_jsonl(messages_path, conversations)
    write_jsonl(rejected_path, [])
    manifest = {
        "schema_version": 1,
        "input_files": [
            {"path": str(path.resolve()), "sha256": file_sha256(path)} for path in input_files
        ],
        "accepted_blocks": len(rows),
        "conversations": len(conversations),
        "duplicate_sources_dropped": duplicates,
        "human_reference_override_datasets": sorted(override_datasets),
        "human_reference_overrides": reference_overrides,
        "human_reference_script_fallbacks": reference_script_fallbacks,
        "languages": dict(sorted(Counter(row["source_language"] for row in rows).items())),
        "datasets": dict(
            sorted(Counter(row["provenance"]["dataset"] for row in rows).items())
        ),
        "held_out_overlap": 0,
        "teacher_blocks_sha256": file_sha256(blocks_path),
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
