"""Measure inter-annotator agreement and judge validity on a gold set.

`judge_is_provisional` may only be cleared when TWO INDEPENDENT HUMAN annotators
agree well enough with each other, and the model judge agrees well enough with
their adjudicated verdict. A model — including Claude — may never stand in for
one of the two humans; this script therefore refuses annotator files that
declare a non-human annotator.

    python -m scripts.training.measure_agreement \\
        --annotations alice=...\\alice.jsonl --annotations bob=...\\bob.jsonl \\
        --judge ...\\judged_predictions.jsonl --key ...\\assignment_key.jsonl \\
        --output ...\\agreement.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Landis & Koch bands, used only as a readable label next to the number.
KAPPA_BANDS = (
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.0, "slight"),
)
DEFAULT_MIN_KAPPA = 0.6
DEFAULT_MIN_AGREEMENT = 0.85


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two binary raters. None when it is undefined."""
    total = len(pairs)
    if not total:
        return None
    observed = sum(left == right for left, right in pairs) / total
    left_true = sum(left for left, _ in pairs) / total
    right_true = sum(right for _, right in pairs) / total
    expected = left_true * right_true + (1 - left_true) * (1 - right_true)
    if expected == 1.0:
        # Both raters were constant and identical: agreement is perfect but
        # kappa is undefined (no variance to correct for).
        return None
    return (observed - expected) / (1 - expected)


def quadratic_weighted_kappa(pairs: list[tuple[int, int]], categories: int = 5) -> float | None:
    """Weighted kappa over ordinal 0-4 scores.

    The binary `usable` verdict collapses to a constant on easy sets, which
    leaves plain Cohen's kappa undefined. Graded scores usually retain enough
    variance to still measure agreement.
    """
    total = len(pairs)
    if not total:
        return None
    observed = [[0] * categories for _ in range(categories)]
    left_counts = [0] * categories
    right_counts = [0] * categories
    for left, right in pairs:
        observed[left][right] += 1
        left_counts[left] += 1
        right_counts[right] += 1
    denominator = (categories - 1) ** 2
    numerator_o = numerator_e = 0.0
    for i in range(categories):
        for j in range(categories):
            weight = ((i - j) ** 2) / denominator
            numerator_o += weight * observed[i][j]
            numerator_e += weight * left_counts[i] * right_counts[j] / total
    if numerator_e == 0:
        return None
    return 1 - (numerator_o / numerator_e)


def band(kappa: float | None) -> str:
    if kappa is None:
        return "undefined"
    for threshold, name in KAPPA_BANDS:
        if kappa >= threshold:
            return name
    return "poor"


def verdicts(rows: list[dict]) -> dict[tuple[str, str], bool]:
    """Map (task_id, candidate label) -> usable, skipping skipped items."""
    out = {}
    for row in rows:
        if row.get("skipped"):
            continue
        out[(row["task_id"], row["label"])] = bool(row["usable"])
    return out


def accuracy_scores(rows: list[dict]) -> dict[tuple[str, str], int]:
    """Map (task_id, label) -> accuracy 0-4, for the weighted-kappa fallback."""
    out = {}
    for row in rows:
        if row.get("skipped"):
            continue
        value = row.get("accuracy")
        if value is None or value == "":
            continue
        try:
            score = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= score <= 4:
            out[(row["task_id"], row["label"])] = score
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--annotations", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--judge", type=Path, help="judged_predictions.jsonl from the model judge.")
    parser.add_argument("--key", type=Path, help="assignment_key.jsonl, needed to align the judge.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-kappa", type=float, default=DEFAULT_MIN_KAPPA)
    parser.add_argument("--min-agreement", type=float, default=DEFAULT_MIN_AGREEMENT)
    args = parser.parse_args(argv)

    annotators: dict[str, list[dict]] = {}
    for item in args.annotations:
        name, _, raw = item.partition("=")
        if not name or not raw:
            parser.error(f"--annotations expects NAME=PATH, got {item!r}")
        rows = read_jsonl(Path(raw))
        for row in rows:
            kind = str(row.get("annotator_type", "human")).lower()
            if kind != "human":
                parser.error(
                    f"annotator {name!r} declares annotator_type={kind!r}; "
                    "a model judge cannot substitute for a human annotator"
                )
        annotators[name] = rows
    if len(annotators) < 2:
        parser.error("two independent human annotators are required to clear judge_is_provisional")

    names = sorted(annotators)
    tables = {name: verdicts(rows) for name, rows in annotators.items()}
    shared = set.intersection(*(set(table) for table in tables.values()))
    report: dict = {
        "schema_version": 1,
        "annotators": names,
        "annotated_items": {name: len(table) for name, table in tables.items()},
        "shared_items": len(shared),
        "thresholds": {"min_kappa": args.min_kappa, "min_agreement": args.min_agreement},
    }
    if not shared:
        parser.error("the annotators have no overlapping items to compare")

    scores = {name: accuracy_scores(rows) for name, rows in annotators.items()}
    pairwise = {}
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            pairs = [(tables[left][key], tables[right][key]) for key in sorted(shared)]
            agreement = sum(a == b for a, b in pairs) / len(pairs)
            kappa = cohens_kappa(pairs)
            entry = {
                "items": len(pairs),
                "agreement": round(agreement, 4),
                "cohens_kappa": None if kappa is None else round(kappa, 4),
                "kappa_band": band(kappa),
            }
            graded = sorted(set(scores[left]) & set(scores[right]))
            if graded:
                score_pairs = [(scores[left][key], scores[right][key]) for key in graded]
                weighted = quadratic_weighted_kappa(score_pairs)
                entry["accuracy_items"] = len(score_pairs)
                entry["accuracy_quadratic_kappa"] = None if weighted is None else round(weighted, 4)
                entry["accuracy_agreement"] = round(
                    sum(a == b for a, b in score_pairs) / len(score_pairs), 4
                )
            pairwise[f"{left} vs {right}"] = entry
    report["human_pairwise"] = pairwise

    # A gold set on which every verdict is identical cannot validate anything.
    verdict_values = {value for table in tables.values() for value in table.values()}
    report["verdict_variance"] = {
        "distinct_human_verdicts": sorted(verdict_values),
        "degenerate": len(verdict_values) < 2,
    }

    disputed = sorted(key for key in shared if len({table[key] for table in tables.values()}) > 1)
    report["disputed_items"] = [{"task_id": t, "label": ll} for t, ll in disputed]
    report["disputed_count"] = len(disputed)
    # Only undisputed items form the adjudicated truth; the rest need arbitration.
    adjudicated = {key: tables[names[0]][key] for key in sorted(shared) if key not in set(disputed)}
    report["adjudicated_items"] = len(adjudicated)

    if args.judge and args.key:
        key_rows = {row["task_id"]: row["assignment"] for row in read_jsonl(args.key)}
        judge_rows = {row["id"]: bool(row["judge_score"] >= 3) for row in read_jsonl(args.judge)}
        pairs, unmatched = [], 0
        for (task_id, label), human in adjudicated.items():
            assignment = key_rows.get(task_id, {})
            if label not in assignment:
                unmatched += 1
                continue
            record_id = task_id.split("-", 1)[1] if "-" in task_id else task_id
            if record_id not in judge_rows:
                unmatched += 1
                continue
            pairs.append((human, judge_rows[record_id]))
        if pairs:
            agreement = sum(a == b for a, b in pairs) / len(pairs)
            kappa = cohens_kappa(pairs)
            report["judge_vs_human"] = {
                "items": len(pairs),
                "unmatched": unmatched,
                "agreement": round(agreement, 4),
                "cohens_kappa": None if kappa is None else round(kappa, 4),
                "kappa_band": band(kappa),
                "human_usable_rate": round(sum(a for a, _ in pairs) / len(pairs), 4),
                "judge_usable_rate": round(sum(b for _, b in pairs) / len(pairs), 4),
            }
        else:
            report["judge_vs_human"] = {"items": 0, "unmatched": unmatched}

    human_ok = all(
        entry["agreement"] >= args.min_agreement
        and entry["cohens_kappa"] is not None
        and entry["cohens_kappa"] >= args.min_kappa
        for entry in pairwise.values()
    )
    judge_entry = report.get("judge_vs_human") or {}
    judge_ok = bool(
        judge_entry.get("items")
        and judge_entry.get("agreement", 0) >= args.min_agreement
        and judge_entry.get("cohens_kappa") is not None
        and judge_entry["cohens_kappa"] >= args.min_kappa
    )
    blockers = []
    if not human_ok:
        blockers.append("human inter-annotator agreement below threshold")
    if not judge_ok:
        blockers.append("model judge agreement with adjudicated humans below threshold")
    if disputed:
        blockers.append(f"{len(disputed)} disputed items await arbitration")
    if report["verdict_variance"]["degenerate"]:
        blockers.append(
            "every human verdict is identical: this gold set has no discriminative power "
            "and cannot validate the judge; add harder layers"
        )
    report["may_clear_judge_is_provisional"] = not blockers
    report["blockers"] = blockers

    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    counts = Counter(len({table[key] for table in tables.values()}) for key in shared)
    print(f"# 一致 {counts.get(1, 0)} 项，分歧 {counts.get(2, 0)} 项", flush=True)
    return 0 if report["may_clear_judge_is_provisional"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
