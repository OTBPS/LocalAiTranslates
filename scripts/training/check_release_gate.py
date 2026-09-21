"""Evaluate an eval run against the project release gate.

The gate lives in `model-requirements.json` and was previously declarative
only: nothing read it, so "did this adapter pass?" was answered by hand.  This
script maps the gate names onto the metric names the evaluation scripts
actually emit and returns a machine-readable verdict.

    block_alignment                 -> summary.json:semantic_block_alignment_rate
    usable_translation              -> judge_summary.json:usable_rate
    duplicate_or_hallucinated_blocks-> summary.json:cross_record_duplicate_outputs
                                     + summary.json:unexpected_repetitions

Exit code 0 means every gate passed; 1 means at least one failed or a required
metric is missing.  A provisional judge never yields a silent pass: the verdict
carries `judge_is_provisional` so callers can require a human-reviewed run.

    python scripts/training/check_release_gate.py D:\\AI\\Training\\screen-translator\\runs\\full-eval-v1\\qwen3-4b-teacher-v2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUIREMENTS = PROJECT_ROOT / "model-requirements.json"


class GateError(RuntimeError):
    """The reports cannot be evaluated against the gate."""


def load_gate(requirements: Path) -> dict:
    try:
        document = json.loads(Path(requirements).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read {requirements}: {error}") from error
    gate = document.get("release_gate")
    if not isinstance(gate, dict):
        raise GateError(f"{requirements} has no release_gate block")
    missing = {"block_alignment_min", "usable_translation_min", "duplicate_or_hallucinated_blocks_max"} - set(gate)
    if missing:
        raise GateError(f"release_gate is missing {sorted(missing)}")
    return gate


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read {path}: {error}") from error


def _number(report: dict, key: str, source: str):
    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"{source} is missing a numeric {key}"
    return float(value), None


def evaluate(summary: dict, judge: dict, gate: dict) -> dict:
    """Return a verdict for one evaluation run."""
    checks = []

    alignment, problem = _number(summary, "semantic_block_alignment_rate", "summary.json")
    checks.append(
        {
            "gate": "block_alignment",
            "metric": "semantic_block_alignment_rate",
            "value": alignment,
            "threshold": gate["block_alignment_min"],
            "comparison": ">=",
            "passed": alignment is not None and alignment >= gate["block_alignment_min"],
            "problem": problem,
        }
    )

    usable, problem = _number(judge, "usable_rate", "judge_summary.json")
    checks.append(
        {
            "gate": "usable_translation",
            "metric": "usable_rate",
            "value": usable,
            "threshold": gate["usable_translation_min"],
            "comparison": ">=",
            "passed": usable is not None and usable >= gate["usable_translation_min"],
            "problem": problem,
        }
    )

    duplicates, duplicate_problem = _number(summary, "cross_record_duplicate_outputs", "summary.json")
    repetitions, repetition_problem = _number(summary, "unexpected_repetitions", "summary.json")
    total = None if duplicates is None or repetitions is None else duplicates + repetitions
    checks.append(
        {
            "gate": "duplicate_or_hallucinated_blocks",
            "metric": "cross_record_duplicate_outputs+unexpected_repetitions",
            "value": total,
            "threshold": gate["duplicate_or_hallucinated_blocks_max"],
            "comparison": "<=",
            "passed": total is not None and total <= gate["duplicate_or_hallucinated_blocks_max"],
            "problem": duplicate_problem or repetition_problem,
        }
    )

    return {
        "passed": all(check["passed"] for check in checks),
        "records": summary.get("count"),
        "judge_records": judge.get("count"),
        "judge_model": judge.get("judge_model"),
        "judge_is_provisional": bool(judge.get("judge_is_provisional")),
        "similarity_gate_is_provisional": bool(summary.get("similarity_gate_is_provisional")),
        "checks": checks,
    }


def evaluate_run(run: Path, gate: dict, *, summary_path=None, judge_path=None) -> dict:
    run = Path(run)
    summary_path = Path(summary_path) if summary_path else run / "summary.json"
    judge_path = Path(judge_path) if judge_path else run / "judge_summary.json"
    verdict = evaluate(_read(summary_path), _read(judge_path), gate)
    verdict["run"] = str(run)
    verdict["summary"] = str(summary_path)
    verdict["judge_summary"] = str(judge_path)
    return verdict


def format_verdict(verdict: dict) -> str:
    lines = [
        f"run: {verdict.get('run', '(inline report)')}",
        f"records: {verdict['records']} (judged {verdict['judge_records']})",
    ]
    for check in verdict["checks"]:
        state = "PASS" if check["passed"] else "FAIL"
        value = "missing" if check["value"] is None else f"{check['value']:.4f}"
        lines.append(f"  [{state}] {check['gate']}: {value} {check['comparison']} {check['threshold']}")
        if check["problem"]:
            lines.append(f"         {check['problem']}")
    if verdict["judge_is_provisional"]:
        lines.append("  note: judge_is_provisional=true; a human-reviewed gold set is required before release")
    lines.append(f"result: {'PASS' if verdict['passed'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path, help="Evaluation run directory containing the reports.")
    parser.add_argument("--summary", type=Path, help="Override the summary.json path.")
    parser.add_argument("--judge-summary", type=Path, help="Override the judge_summary.json path.")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--json", action="store_true", help="Print the verdict as JSON.")
    args = parser.parse_args(argv)

    try:
        gate = load_gate(args.requirements)
        verdict = evaluate_run(args.run, gate, summary_path=args.summary, judge_path=args.judge_summary)
    except GateError as error:
        print(f"release gate error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(verdict, ensure_ascii=False, indent=2) if args.json else format_verdict(verdict))
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
