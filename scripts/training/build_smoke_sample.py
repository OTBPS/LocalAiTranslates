"""Sample a few gold tasks to rehearse the annotation workflow.

This validates the tooling only — loading tasks, filling the seven dimensions,
exporting, and running the agreement script end to end. Its results carry
`clears_provisional: false` and must never be used to lift the release block
or to characterise model quality.

    python -m scripts.training.build_smoke_sample --tasks ...\\tasks.jsonl --records 10 \\
        --output-dir ...\\tasks\\smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--records", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260922)
    args = parser.parse_args(argv)

    tasks = [json.loads(line) for line in args.tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.records > len(tasks):
        parser.error(f"only {len(tasks)} tasks available")
    # Spread the sample across categories so the rehearsal touches each layer.
    by_domain: dict[str, list[dict]] = {}
    for task in tasks:
        by_domain.setdefault(task["domain"], []).append(task)
    rng = random.Random(args.seed)
    for rows in by_domain.values():
        rng.shuffle(rows)
    domains = sorted(by_domain)
    picked: list[dict] = []
    cursor = 0
    while len(picked) < args.records and any(by_domain[d] for d in domains):
        domain = domains[cursor % len(domains)]
        if by_domain[domain]:
            picked.append(by_domain[domain].pop())
        cursor += 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample = args.output_dir / "tasks.jsonl"
    sample.write_text(
        "".join(json.dumps(task, ensure_ascii=False) + "\n" for task in picked), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "purpose": "annotation workflow smoke test",
        "records": len(picked),
        "domains": dict(sorted(Counter(task["domain"] for task in picked).items())),
        "source_tasks": str(args.tasks.resolve()),
        "source_tasks_sha256": file_sha256(args.tasks),
        "dataset_sha256": file_sha256(sample),
        "seed": args.seed,
        "clears_provisional": False,
        "note": (
            "tooling rehearsal only; results must not lift the release block, "
            "feed model comparison, or be reported as quality"
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
