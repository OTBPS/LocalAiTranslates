"""Recompute local deterministic metrics without running model inference again."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.training.evaluate_models import (
    chrf_score,
    summarize,
    token_preservation,
    unexpected_repetitions,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="+", type=Path)
    args = parser.parse_args()
    for directory in args.directories:
        prediction_path = directory / "predictions.jsonl"
        rows = [json.loads(line) for line in prediction_path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["chrf"] = round(chrf_score(row["translation"], row["reference_text"]), 6)
            row["token_preservation"] = round(
                token_preservation(row["source_text"], row["translation"], row["reference_text"]),
                6,
            )
            row["unexpected_repetitions"] = unexpected_repetitions(
                row["translation"], row["reference_text"]
            )
        batch_stats = json.loads((directory / "batches.json").read_text(encoding="utf-8"))
        previous = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        report = summarize(rows, batch_stats)
        report.update(
            {
                key: value
                for key, value in previous.items()
                if key
                in {
                    "model",
                    "adapter",
                    "dataset",
                    "records",
                    "peak_vram_gib",
                }
            }
        )
        prediction_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        (directory / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"directory": str(directory), **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
