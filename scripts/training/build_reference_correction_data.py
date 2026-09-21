"""Build balanced high-confidence correction SFT using human references."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.translation_engine import build_translation_system_prompt

LANGUAGES = ("en", "ja", "ko")


def make_conversations(rows: list[dict], max_blocks: int, max_chars: int) -> list[dict]:
    conversations = []
    for language in LANGUAGES:
        batch, chars = [], 0
        for row in (item for item in rows if item["source_language"] == language):
            size = len(row["source_text"])
            if batch and (len(batch) >= max_blocks or chars + size > max_chars):
                conversations.append(make_conversation(language, batch))
                batch, chars = [], 0
            batch.append(row)
            chars += size
        if batch:
            conversations.append(make_conversation(language, batch))
    return conversations


def make_conversation(language: str, rows: list[dict]) -> dict:
    source = {row["id"]: row["source_text"] for row in rows}
    target = {row["id"]: row["human_reference"] for row in rows}
    return {
        "messages": [
            {"role": "system", "content": build_translation_system_prompt(language, "zh-Hans")},
            {"role": "user", "content": json.dumps(source, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ],
        "metadata": {
            "source_language": language,
            "block_ids": list(source),
            "target_kind": "human_reference",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-teacher-chrf", type=float, default=0.2)
    parser.add_argument("--per-language", type=int, default=1300)
    parser.add_argument("--max-blocks", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()

    source_rows = [
        json.loads(line)
        for line in (args.source_dir / "teacher_blocks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    selected = []
    rng = random.Random(args.seed)
    for language in LANGUAGES:
        candidates = [
            row
            for row in source_rows
            if row["source_language"] == language and row["chrf"] >= args.min_teacher_chrf
        ]
        rng.shuffle(candidates)
        selected.extend(candidates[: args.per_language])
    rng.shuffle(selected)
    # Re-sort only by language so the within-language sampling remains randomized.
    selected.sort(key=lambda row: LANGUAGES.index(row["source_language"]))
    conversations = make_conversations(selected, args.max_blocks, args.max_chars)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "teacher_blocks.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected),
        encoding="utf-8",
    )
    (args.output_dir / "rejected.jsonl").write_text("", encoding="utf-8")
    (args.output_dir / "sft_messages.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in conversations),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "source": str(args.source_dir.resolve()),
        "target_kind": "human_reference",
        "min_teacher_chrf": args.min_teacher_chrf,
        "per_language_limit": args.per_language,
        "blocks": len(selected),
        "conversations": len(conversations),
        "languages": dict(sorted(Counter(row["source_language"] for row in selected).items())),
        "training_use_prohibited_eval_overlap": 0,
        "seed": args.seed,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
