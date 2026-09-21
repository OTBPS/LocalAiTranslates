"""Validate completed teacher-data reviews and emit an auditable summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def apply_decisions(rows: list[dict], decisions: list[dict]) -> list[dict]:
    by_id = {row["id"]: row for row in decisions}
    if len(by_id) != len(decisions):
        raise ValueError("duplicate audit decision id")
    sample_ids = {row["id"] for row in rows}
    if set(by_id) != sample_ids:
        raise ValueError("audit decisions must cover every sampled id exactly once")
    reviewed = []
    for row in rows:
        decision = by_id[row["id"]]
        reviewed.append(
            {
                **row,
                "review_status": decision["review_status"],
                "review_issue": decision.get("review_issue"),
                "review_notes": decision.get("review_notes", ""),
            }
        )
    return reviewed


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("audit sample is empty")
    pending = [row["id"] for row in rows if row.get("review_status") == "pending"]
    if pending:
        raise ValueError(f"audit sample still has {len(pending)} pending reviews")
    invalid = [
        row["id"] for row in rows if row.get("review_status") not in {"pass", "fail"}
    ]
    if invalid:
        raise ValueError(f"invalid review status for {len(invalid)} records")
    failures_without_issue = [
        row["id"]
        for row in rows
        if row["review_status"] == "fail" and not row.get("review_issue")
    ]
    if failures_without_issue:
        raise ValueError("failed reviews must include review_issue")

    passed = sum(row["review_status"] == "pass" for row in rows)
    languages = {}
    for language in sorted({row["source_language"] for row in rows}):
        subset = [row for row in rows if row["source_language"] == language]
        language_passed = sum(row["review_status"] == "pass" for row in subset)
        languages[language] = {
            "records": len(subset),
            "passed": language_passed,
            "pass_rate": round(language_passed / len(subset), 4),
        }
    return {
        "records": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": round(passed / len(rows), 4),
        "issues": dict(
            sorted(
                Counter(
                    row["review_issue"]
                    for row in rows
                    if row["review_status"] == "fail"
                ).items()
            )
        ),
        "languages": languages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--reviewed-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.reviewed.read_text(encoding="utf-8").splitlines()]
    reviewed_path = args.reviewed
    if args.decisions:
        if not args.reviewed_output:
            raise ValueError("--reviewed-output is required with --decisions")
        decisions = [
            json.loads(line)
            for line in args.decisions.read_text(encoding="utf-8").splitlines()
        ]
        rows = apply_decisions(rows, decisions)
        args.reviewed_output.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        reviewed_path = args.reviewed_output
    report = {
        "schema_version": 1,
        "reviewed_file": str(reviewed_path.resolve()),
        "reviewed_sha256": hashlib.sha256(reviewed_path.read_bytes()).hexdigest(),
        **summarize(rows),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
