"""gold 标注流水线：盲测、双人工一致率与 provisional 解除条件。"""

import json

import pytest

from scripts.training.build_gold_tasks import build, permutation
from scripts.training.measure_agreement import cohens_kappa
from scripts.training.measure_agreement import main as agreement_main


def record(record_id, domain="news_web", source_language="en", target="zh-Hans"):
    return {
        "id": record_id,
        "source_language": source_language,
        "target_language": target,
        "domain": domain,
        "source_text": f"source {record_id}",
        "reference_text": f"reference {record_id}",
        "provenance": {"dataset": "test", "license": "CC-BY-SA-4.0"},
    }


def test_permutation_is_deterministic_and_complete():
    first = permutation("gold:abc", 3)
    assert first == permutation("gold:abc", 3)
    assert sorted(first) == [0, 1, 2]


def test_permutation_differs_across_tasks():
    orders = {tuple(permutation(f"gold:{index}", 3)) for index in range(40)}
    assert len(orders) > 1, "每条任务都用同一个排列就等于没有盲化"


def test_candidates_are_anonymised_and_the_key_is_separate():
    dataset = [record("r1"), record("r2")]
    systems = {
        "model-x": {"r1": "x1", "r2": "x2"},
        "model-y": {"r1": "y1", "r2": "y2"},
    }

    tasks, keys, missing = build(dataset, systems, "gold")

    assert missing == {}
    for task in tasks:
        serialised = json.dumps(task, ensure_ascii=False)
        assert "model-x" not in serialised and "model-y" not in serialised
        assert [c["label"] for c in task["candidates"]] == ["A", "B"]
    assert {k["task_id"] for k in keys} == {t["task_id"] for t in tasks}
    assert all(set(k["assignment"]) == {"A", "B"} for k in keys)
    assert all(set(k["assignment"].values()) == {"model-x", "model-y"} for k in keys)


def test_ordering_is_not_constant_across_tasks():
    dataset = [record(f"r{index}") for index in range(30)]
    systems = {
        "model-x": {f"r{index}": "x" for index in range(30)},
        "model-y": {f"r{index}": "y" for index in range(30)},
    }

    _tasks, keys, _missing = build(dataset, systems, "gold")
    first_slot = {key["assignment"]["A"] for key in keys}

    assert first_slot == {"model-x", "model-y"}, "A 槽必须在两个系统间交替，否则标注者能猜出来"


def test_records_without_predictions_are_reported_not_silently_dropped():
    dataset = [record("r1"), record("r2")]
    systems = {"model-x": {"r1": "x1"}}

    tasks, _keys, missing = build(dataset, systems, "gold")

    assert len(tasks) == 1
    assert missing == {"model-x": 1}


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        ([(True, True), (False, False)], 1.0),
        ([(True, False), (False, True)], -1.0),
    ],
)
def test_cohens_kappa_endpoints(pairs, expected):
    assert cohens_kappa(pairs) == pytest.approx(expected)


def test_cohens_kappa_is_undefined_when_both_raters_are_constant():
    assert cohens_kappa([(True, True)] * 10) is None


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def annotation(task_id, label, usable, annotator_type="human"):
    return {"task_id": task_id, "label": label, "usable": usable, "annotator_type": annotator_type}


def test_a_model_annotator_is_refused(tmp_path, capsys):
    alice = tmp_path / "alice.jsonl"
    robot = tmp_path / "robot.jsonl"
    write(alice, [annotation("t1", "A", True)])
    write(robot, [annotation("t1", "A", True, annotator_type="model")])

    with pytest.raises(SystemExit) as exit_info:
        agreement_main(["--annotations", f"alice={alice}", "--annotations", f"robot={robot}"])

    assert exit_info.value.code == 2
    assert "cannot substitute for a human" in capsys.readouterr().err


def test_a_single_annotator_is_refused(tmp_path, capsys):
    alice = tmp_path / "alice.jsonl"
    write(alice, [annotation("t1", "A", True)])

    with pytest.raises(SystemExit) as exit_info:
        agreement_main(["--annotations", f"alice={alice}"])

    assert exit_info.value.code == 2
    assert "two independent human annotators" in capsys.readouterr().err


def test_disputed_items_block_clearing_and_are_listed(tmp_path):
    alice, bob, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "r.json"
    rows_a = [annotation(f"t{i}", "A", True) for i in range(20)]
    rows_b = [annotation(f"t{i}", "A", True) for i in range(19)] + [annotation("t19", "A", False)]
    write(alice, rows_a)
    write(bob, rows_b)

    code = agreement_main(["--annotations", f"alice={alice}", "--annotations", f"bob={bob}",
                           "--output", str(out)])

    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1
    assert report["disputed_count"] == 1
    assert report["disputed_items"] == [{"task_id": "t19", "label": "A"}]
    assert report["may_clear_judge_is_provisional"] is False
    assert any("arbitration" in b for b in report["blockers"])


def test_a_degenerate_gold_set_cannot_validate_the_judge(tmp_path):
    """全部判可用的 gold 集没有区分度，必须明确拒绝而不是报告完美一致。"""
    alice, bob, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "r.json"
    rows = [annotation(f"t{i}", "A", True) for i in range(40)]
    write(alice, rows)
    write(bob, rows)

    code = agreement_main(["--annotations", f"alice={alice}", "--annotations", f"bob={bob}",
                           "--output", str(out)])

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdict_variance"]["degenerate"] is True
    assert report["human_pairwise"]["alice vs bob"]["agreement"] == 1.0
    assert report["human_pairwise"]["alice vs bob"]["cohens_kappa"] is None
    assert report["may_clear_judge_is_provisional"] is False
    assert any("discriminative power" in b for b in report["blockers"])
    assert code == 1


def test_graded_scores_give_a_weighted_kappa_when_usable_is_constant(tmp_path):
    alice, bob, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "r.json"
    rows_a, rows_b = [], []
    for index in range(20):
        score = 3 if index % 2 else 4
        rows_a.append({**annotation(f"t{index}", "A", True), "accuracy": score})
        rows_b.append({**annotation(f"t{index}", "A", True), "accuracy": score})
    write(alice, rows_a)
    write(bob, rows_b)

    agreement_main(["--annotations", f"alice={alice}", "--annotations", f"bob={bob}",
                    "--output", str(out)])

    entry = json.loads(out.read_text(encoding="utf-8"))["human_pairwise"]["alice vs bob"]
    assert entry["accuracy_items"] == 20
    assert entry["accuracy_quadratic_kappa"] == 1.0


def test_clearing_requires_the_model_judge_to_agree_too(tmp_path):
    alice, bob, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "r.json"
    # Perfectly agreeing humans with a real split of usable/unusable.
    rows = [annotation(f"t{i}", "A", i % 2 == 0) for i in range(20)]
    write(alice, rows)
    write(bob, rows)

    code = agreement_main(["--annotations", f"alice={alice}", "--annotations", f"bob={bob}",
                           "--output", str(out)])

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["human_pairwise"]["alice vs bob"]["cohens_kappa"] == 1.0
    # Humans agree, but without judge data provisional stays.
    assert report["may_clear_judge_is_provisional"] is False
    assert code == 1
