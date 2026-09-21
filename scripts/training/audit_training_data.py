"""Audit generated SFT data before allowing a training run."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from scripts.training.training_paths import workspace_path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.training.evaluate_models import chrf_score, token_preservation, unexpected_repetitions
from scripts.training.generate_teacher_data import target_script_ok


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def audit(data_dir: Path, eval_path: Path) -> dict:
    accepted = read_jsonl(data_dir / "teacher_blocks.jsonl")
    rejected = read_jsonl(data_dir / "rejected.jsonl")
    conversations = read_jsonl(data_dir / "sft_messages.jsonl")
    evaluation = read_jsonl(eval_path)

    ids = [row["id"] for row in accepted]
    source_keys = [
        (row["source_language"], fingerprint(row["source_text"])) for row in accepted
    ]
    eval_fingerprints = {fingerprint(row["source_text"]) for row in evaluation}
    train_fingerprints = {value for _, value in source_keys}

    invalid_conversations = 0
    conversation_blocks = 0
    actual_targets = {}
    for conversation in conversations:
        try:
            messages = conversation["messages"]
            source = json.loads(messages[1]["content"])
            target = json.loads(messages[2]["content"])
            metadata_ids = conversation["metadata"]["block_ids"]
            if (
                len(messages) != 3
                or set(source) != set(target)
                or set(source) != set(metadata_ids)
                or any(not isinstance(value, str) or not value.strip() for value in target.values())
            ):
                invalid_conversations += 1
            actual_targets.update(target)
            conversation_blocks += len(source)
        except (KeyError, TypeError, json.JSONDecodeError):
            invalid_conversations += 1

    report = {
        "schema_version": 1,
        "teacher_blocks_sha256": file_sha256(data_dir / "teacher_blocks.jsonl"),
        "sft_messages_sha256": file_sha256(data_dir / "sft_messages.jsonl"),
        "accepted_blocks": len(accepted),
        "rejected_blocks": len(rejected),
        "conversations": len(conversations),
        "conversation_blocks": conversation_blocks,
        "duplicate_ids": len(ids) - len(set(ids)),
        "duplicate_language_sources": len(source_keys) - len(set(source_keys)),
        "eval_source_overlap": len(train_fingerprints & eval_fingerprints),
        "invalid_conversations": invalid_conversations,
        "target_script_failures": sum(
            not target_script_ok(actual_targets.get(row["id"], "")) for row in accepted
        ),
        "unexpected_repetitions": sum(
            unexpected_repetitions(actual_targets.get(row["id"], ""), row["human_reference"])
            for row in accepted
        ),
        "minimum_token_preservation": min(
            (
                token_preservation(
                    row["source_text"],
                    actual_targets.get(row["id"], ""),
                    row["human_reference"],
                )
                for row in accepted
            ),
            default=0.0,
        ),
        "mean_training_target_chrf": round(
            sum(
                chrf_score(actual_targets.get(row["id"], ""), row["human_reference"])
                for row in accepted
            )
            / max(1, len(accepted)),
            4,
        ),
        "languages": dict(sorted(Counter(row["source_language"] for row in accepted).items())),
        "datasets": dict(
            sorted(Counter(row["provenance"]["dataset"] for row in accepted).items())
        ),
    }
    report["passed"] = all(
        report[key] == 0
        for key in (
            "duplicate_ids",
            "duplicate_language_sources",
            "eval_source_overlap",
            "invalid_conversations",
            "target_script_failures",
            "unexpected_repetitions",
        )
    ) and report["minimum_token_preservation"] == 1.0
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--eval", type=Path, default=workspace_path("data/eval/v1/eval.jsonl"))
    args = parser.parse_args()
    report = audit(args.data_dir, args.eval)
    (args.data_dir / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
