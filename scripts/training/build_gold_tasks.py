"""Build blind human-annotation tasks from an evaluation set and model outputs.

Candidate translations are stripped of their model identity and shuffled with a
per-task deterministic permutation, so an annotator cannot infer which system
produced which text. The label->model mapping is written to a separate key file
that the annotation UI never loads.

    python -m scripts.training.build_gold_tasks \\
        --dataset D:\\AI\\Training\\screen-translator\\data\\eval\\zh-en-v1\\eval.jsonl \\
        --predictions qwen3-8b-q5-k-m=...\\predictions.jsonl \\
        --predictions qwen3-14b-q5-k-m=...\\predictions.jsonl \\
        --output-dir D:\\AI\\Training\\screen-translator\\data\\gold\\zh-en-v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

LABELS = "ABCDEFGH"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def permutation(task_id: str, count: int) -> list[int]:
    """Deterministic per-task shuffle: reproducible, but not guessable from order."""
    digest = hashlib.sha256(task_id.encode("utf-8")).digest()
    order = list(range(count))
    for index in range(count - 1, 0, -1):
        swap = digest[index % len(digest)] % (index + 1)
        order[index], order[swap] = order[swap], order[index]
    return order


def build(dataset: list[dict], systems: dict[str, dict[str, str]], prefix: str):
    tasks, keys = [], []
    missing: Counter[str] = Counter()
    for record in dataset:
        record_id = record["id"]
        available = [(name, rows[record_id]) for name, rows in systems.items() if record_id in rows]
        for name in systems:
            if record_id not in systems[name]:
                missing[name] += 1
        if not available:
            continue
        order = permutation(f"{prefix}:{record_id}", len(available))
        shuffled = [available[index] for index in order]
        tasks.append(
            {
                "task_id": f"{prefix}-{record_id}",
                "record_id": record_id,
                "direction": f"{record['source_language']}->{record.get('target_language', 'zh-Hans')}",
                "source_language": record["source_language"],
                "target_language": record.get("target_language", "zh-Hans"),
                "domain": record["domain"],
                "source_text": record["source_text"],
                "reference_text": record["reference_text"],
                "candidates": [
                    {"label": LABELS[position], "text": text}
                    for position, (_name, text) in enumerate(shuffled)
                ],
                "provenance": record.get("provenance", {}),
            }
        )
        keys.append(
            {
                "task_id": f"{prefix}-{record_id}",
                "assignment": {
                    LABELS[position]: name for position, (name, _text) in enumerate(shuffled)
                },
            }
        )
    return tasks, keys, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--predictions",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Repeatable. The name is recorded only in the key file.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="gold")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    systems: dict[str, dict[str, str]] = {}
    system_hashes: dict[str, str] = {}
    for item in args.predictions:
        name, _, raw_path = item.partition("=")
        if not name or not raw_path:
            parser.error(f"--predictions expects NAME=PATH, got {item!r}")
        path = Path(raw_path)
        if not path.is_file():
            parser.error(f"predictions file not found: {path}")
        systems[name] = {row["id"]: row.get("translation", "") for row in read_jsonl(path)}
        system_hashes[name] = file_sha256(path)

    dataset = read_jsonl(args.dataset)
    if args.limit:
        dataset = dataset[: args.limit]
    tasks, keys, missing = build(dataset, systems, args.prefix)
    if not tasks:
        parser.error("no tasks built: the predictions do not cover any dataset record")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    tasks_path = args.output_dir / "tasks.jsonl"
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False) + "\n" for task in tasks), encoding="utf-8"
    )
    (args.output_dir / "assignment_key.jsonl").write_text(
        "".join(json.dumps(key, ensure_ascii=False) + "\n" for key in keys), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "prefix": args.prefix,
        "tasks": len(tasks),
        "candidates_per_task": sorted({len(task["candidates"]) for task in tasks}),
        "dataset": str(args.dataset.resolve()),
        "dataset_sha256": file_sha256(args.dataset),
        "systems": sorted(systems),
        "system_prediction_sha256": system_hashes,
        "missing_predictions": dict(missing),
        "domains": dict(sorted(Counter(task["domain"] for task in tasks).items())),
        "directions": dict(sorted(Counter(task["direction"] for task in tasks).items())),
        "tasks_sha256": file_sha256(tasks_path),
        "blinding": "per-task sha256 permutation; assignment_key.jsonl is not loaded by the UI",
        "usage_restriction": (
            "gold annotation only; must not inform training, prompts, hyperparameters, "
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
