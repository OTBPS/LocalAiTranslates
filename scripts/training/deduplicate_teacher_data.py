"""Remove normalized duplicate sources from resumable teacher batch state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()


def deduplicate(states: list[dict]) -> tuple[list[dict], list[str]]:
    seen = set()
    removed = []
    for state in sorted(states, key=lambda item: item["stats"]["batch"]):
        kept = []
        for row in state["accepted"]:
            key = (row["source_language"], fingerprint(row["source_text"]))
            if key in seen:
                removed.append(row["id"])
                rejected = dict(row)
                rejected["rejection_reasons"] = sorted(
                    set(rejected.get("rejection_reasons", [])) | {"duplicate_source"}
                )
                state["rejected"].append(rejected)
            else:
                seen.add(key)
                kept.append(row)
        if len(kept) == len(state["accepted"]):
            continue
        state["accepted"] = kept
        state["stats"]["accepted"] = len(kept)
        if kept:
            source_payload = {row["id"]: row["source_text"] for row in kept}
            target_payload = {row["id"]: row["teacher_translation"] for row in kept}
            state["conversation"]["messages"][1]["content"] = json.dumps(
                source_payload, ensure_ascii=False
            )
            state["conversation"]["messages"][2]["content"] = json.dumps(
                target_payload, ensure_ascii=False
            )
            state["conversation"]["metadata"]["block_ids"] = list(source_payload)
        else:
            state["conversation"] = None
    return states, removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    state_path = args.data_dir / "batch_state.jsonl"
    states = [json.loads(line) for line in state_path.read_text(encoding="utf-8").splitlines()]
    states, removed = deduplicate(states)
    state_path.write_text(
        "".join(json.dumps(state, ensure_ascii=False) + "\n" for state in states),
        encoding="utf-8",
    )
    print(json.dumps({"removed": removed, "count": len(removed)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
