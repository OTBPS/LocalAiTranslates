"""Build deterministic routed-model predictions from two completed evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def route_rows(primary_rows: list[dict], fallback_rows: list[dict], languages: set[str]):
    fallback_by_id = {row["id"]: row for row in fallback_rows}
    if len(fallback_by_id) != len(fallback_rows):
        raise ValueError("fallback predictions contain duplicate IDs")
    if {row["id"] for row in primary_rows} != set(fallback_by_id):
        raise ValueError("primary and fallback prediction IDs differ")

    routed = []
    for primary in primary_rows:
        fallback = fallback_by_id[primary["id"]]
        if (
            primary["source_language"] != fallback["source_language"]
            or primary["source_text"] != fallback["source_text"]
            or primary["reference_text"] != fallback["reference_text"]
        ):
            raise ValueError(f"prediction source mismatch: {primary['id']}")
        use_fallback = primary["source_language"] in languages
        selected = fallback if use_fallback else primary
        routed.append(
            {
                **selected,
                "route": "fallback" if use_fallback else "primary",
            }
        )
    return routed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True)
    parser.add_argument("--fallback-languages", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def load(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    rows = route_rows(load(args.primary), load(args.fallback), set(args.fallback_languages))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "records": len(rows),
                "primary": sum(row["route"] == "primary" for row in rows),
                "fallback": sum(row["route"] == "fallback" for row in rows),
                "fallback_languages": sorted(set(args.fallback_languages)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
