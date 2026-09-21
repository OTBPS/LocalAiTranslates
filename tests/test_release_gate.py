import json
from pathlib import Path

import pytest

from screen_translator.models import SUPPORTED_ADAPTERS
from scripts.training.check_release_gate import (
    DEFAULT_REQUIREMENTS,
    GateError,
    evaluate,
    evaluate_run,
    format_verdict,
    load_gate,
    main,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def gate():
    return load_gate(DEFAULT_REQUIREMENTS)


def summary(**overrides):
    report = {
        "count": 300,
        "semantic_block_alignment_rate": 1.0,
        "cross_record_duplicate_outputs": 0,
        "unexpected_repetitions": 0,
        "similarity_gate_is_provisional": True,
    }
    report.update(overrides)
    return report


def judge(**overrides):
    report = {
        "count": 300,
        "usable_rate": 0.9433,
        "judge_model": "qwen3-14b-q5-k-m",
        "judge_is_provisional": True,
    }
    report.update(overrides)
    return report


def write_run(root, summary_report, judge_report):
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(summary_report), encoding="utf-8")
    (root / "judge_summary.json").write_text(json.dumps(judge_report), encoding="utf-8")
    return root


def test_project_gate_values_are_the_documented_thresholds():
    assert gate() == {
        "block_alignment_min": 0.895,
        "usable_translation_min": 0.94,
        "duplicate_or_hallucinated_blocks_max": 0,
    }


def test_a_run_meeting_every_threshold_passes():
    verdict = evaluate(summary(), judge(), gate())

    assert verdict["passed"] is True
    assert [check["gate"] for check in verdict["checks"]] == [
        "block_alignment",
        "usable_translation",
        "duplicate_or_hallucinated_blocks",
    ]


@pytest.mark.parametrize(
    ("summary_report", "judge_report", "failing"),
    [
        (summary(), judge(usable_rate=0.9367), "usable_translation"),
        (summary(semantic_block_alignment_rate=0.8), judge(), "block_alignment"),
        (summary(cross_record_duplicate_outputs=1), judge(), "duplicate_or_hallucinated_blocks"),
        (summary(unexpected_repetitions=2), judge(), "duplicate_or_hallucinated_blocks"),
    ],
)
def test_each_threshold_can_fail_independently(summary_report, judge_report, failing):
    verdict = evaluate(summary_report, judge_report, gate())

    assert verdict["passed"] is False
    failed = [check["gate"] for check in verdict["checks"] if not check["passed"]]
    assert failed == [failing]


def test_the_boundary_value_passes():
    assert evaluate(summary(semantic_block_alignment_rate=0.895), judge(usable_rate=0.94), gate())["passed"]


@pytest.mark.parametrize("value", [None, "0.95", True])
def test_a_missing_or_non_numeric_metric_fails_instead_of_passing(value):
    verdict = evaluate(summary(), judge(usable_rate=value), gate())

    check = verdict["checks"][1]
    assert verdict["passed"] is False
    assert check["value"] is None and "usable_rate" in check["problem"]


def test_a_provisional_judge_is_surfaced_in_the_verdict():
    verdict = evaluate(summary(), judge(), gate())

    assert verdict["judge_is_provisional"] is True
    assert "human-reviewed gold set" in format_verdict(verdict)


def test_the_best_trained_adapter_still_fails_the_gate(tmp_path):
    """qwen3-4b-teacher-v2 on the immutable 300-record set: 0.8367 usable."""
    run = write_run(tmp_path / "full-eval-v1", summary(), judge(usable_rate=0.8367))

    verdict = evaluate_run(run, gate())

    assert verdict["passed"] is False
    assert verdict["checks"][1]["value"] == pytest.approx(0.8367)


def test_evaluate_run_reads_both_reports_from_a_run_directory(tmp_path):
    run = write_run(tmp_path / "run", summary(), judge())

    verdict = evaluate_run(run, gate())

    assert verdict["passed"] is True
    assert verdict["summary"].endswith("summary.json")
    assert verdict["judge_summary"].endswith("judge_summary.json")


def test_missing_reports_are_reported_as_gate_errors(tmp_path):
    with pytest.raises(GateError, match="cannot read"):
        evaluate_run(tmp_path / "absent", gate())


def test_a_requirements_file_without_a_gate_is_rejected(tmp_path):
    path = tmp_path / "model-requirements.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    with pytest.raises(GateError, match="no release_gate"):
        load_gate(path)

    path.write_text(json.dumps({"release_gate": {"block_alignment_min": 0.9}}), encoding="utf-8")
    with pytest.raises(GateError, match="missing"):
        load_gate(path)


def test_cli_exit_codes_distinguish_pass_fail_and_error(tmp_path, capsys):
    passing = write_run(tmp_path / "pass", summary(), judge())
    failing = write_run(tmp_path / "fail", summary(), judge(usable_rate=0.5))

    assert main([str(passing)]) == 0
    assert "result: PASS" in capsys.readouterr().out
    assert main([str(failing), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False
    assert main([str(tmp_path / "absent")]) == 2


def test_shipped_adapter_allow_list_matches_the_project_declaration():
    document = json.loads((PROJECT_ROOT / "model-requirements.json").read_text(encoding="utf-8"))
    declared = {item["base_model_id"]: item["model_id"] for item in document.get("adapters", [])}

    assert declared == SUPPORTED_ADAPTERS
