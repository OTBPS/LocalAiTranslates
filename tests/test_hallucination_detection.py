"""逐样本语义无关/幻觉检测：必须抓住真串块，且不误伤"翻得差但内容相关"。

正例来自真实的 eval-en-news-018（14B 在莱德杯条目里输出了无关的日语足球新闻）。
"""

import json
from pathlib import Path

import pytest

from scripts.training.evaluate_models import (
    semantic_anchors,
    semantic_unrelated,
    semantic_unrelated_ids,
)

REGRESSION = Path(r"D:\AI\Training\screen-translator\data\regression\hallucination-v1\cases.jsonl")


def row(record_id, source, translation, reference):
    return {
        "id": record_id,
        "source_text": source,
        "translation": translation,
        "reference_text": reference,
    }


def test_anchors_combine_literals_and_numbers():
    anchors = semantic_anchors("Team Europe won the 2018 Ryder Cup 16.5 to 10.5")

    assert set(anchors) == {"2018", "16.5", "10.5"}


def test_a_faithful_translation_is_not_flagged():
    assert not semantic_unrelated(
        "Team Europe won the 2018 Ryder Cup 16.5 to 10.5.",
        "欧洲队以16.5比10.5赢得2018年莱德杯。",
        "欧洲队以16.5比10.5赢得2018年莱德杯。",
    )


def test_text_without_anchors_is_never_screened():
    assert not semantic_unrelated("Save the file.", "完全无关的内容。", "保存文件。")


def test_screen_fires_when_every_anchor_is_lost():
    assert semantic_unrelated(
        "Team Europe won the 2018 Ryder Cup 16.5 to 10.5.",
        "利文斯顿的球门不断被射入，点球申诉被驳回。",
        "欧洲队以16.5比10.5赢得2018年莱德杯。",
    )


def test_a_swapped_block_is_flagged_against_the_whole_set():
    predictions = [
        row("a", "Team Europe won the 2018 Ryder Cup 16.5 to 10.5.",
            "利文斯顿球门前险情不断，两次点球申诉被驳回。",
            "欧洲队以16.5比10.5赢得2018年莱德杯。"),
        row("b", "Crosses came into the Livingston box and penalty claims were waved away.",
            "欧洲队以16.5比10.5赢得2018年莱德杯。",
            "利文斯顿球门前险情不断，两次点球申诉被驳回。"),
    ]

    # Only "a" is reachable: the detector needs content anchors in the source,
    # and "b" has none. This is the documented limit of the method, not a bug.
    assert semantic_unrelated_ids(predictions) == ["a"]


def test_a_source_without_anchors_cannot_be_checked():
    """已知局限：源文没有数字/标识符时，本方法无法判断译文是否跑题。"""
    predictions = [
        row("a", "Crosses came into the box and claims were waved away.",
            "一段完全无关的烹饪说明。", "传中球进入禁区，申诉被驳回。"),
    ]

    assert semantic_unrelated_ids(predictions) == []


def test_a_bad_but_on_topic_translation_is_not_flagged():
    """翻得很差、锚点全丢，但没有别的参考更能解释它——不算幻觉。"""
    predictions = [
        row("a", "Two penalty claims in the 1st and 2nd half were dismissed.",
            "克罗斯进入利文斯顿的盒子，一直保持清晰，罚分申诉被驳回。",
            "上下半场两次点球判罚请求被拒。"),
        row("b", "Completely different topic about cooking rice.",
            "一篇关于烹饪的文章。", "一篇关于煮米饭的完全不同的文章。"),
    ]

    assert "a" not in semantic_unrelated_ids(predictions)


def test_records_sharing_one_reference_do_not_trigger_each_other():
    """eval 集里同一条新闻有三个源语言版本、共用一份中文参考。"""
    shared = "利文斯顿球门前险情不断。"
    predictions = [
        row("en", "Crosses came into the box in the 1st and 2nd half.", "完全跑题的内容。", shared),
        row("ja", "クロスがボックスに入ってきた。", "完全跑题的内容。", shared),
    ]

    assert semantic_unrelated_ids(predictions) == []


@pytest.mark.skipif(not REGRESSION.is_file(), reason="regression 集尚未生成")
def test_frozen_regression_cases_still_behave():
    cases = [json.loads(line) for line in REGRESSION.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert cases, "regression 集为空"
    for case in cases:
        screened = semantic_unrelated(
            case["source_text"], case["candidate_text"], case["reference_text"]
        )
        if case["expect_semantic_unrelated"]:
            assert screened, f"{case['case_id']} 应被初筛命中：{case['reason']}"
        # 负例允许通过初筛，但必须在全局确认阶段被排除；见下一个测试。


@pytest.mark.skipif(not REGRESSION.is_file(), reason="regression 集尚未生成")
def test_regression_negative_controls_survive_the_global_check():
    cases = [json.loads(line) for line in REGRESSION.read_text(encoding="utf-8").splitlines() if line.strip()]
    predictions = [
        {
            "id": case["case_id"],
            "source_text": case["source_text"],
            "translation": case["candidate_text"],
            "reference_text": case["reference_text"],
        }
        for case in cases
    ]
    flagged = set(semantic_unrelated_ids(predictions))
    for case in cases:
        if case["expect_semantic_unrelated"]:
            assert case["case_id"] in flagged, f"漏检 {case['case_id']}"
        else:
            assert case["case_id"] not in flagged, f"误报 {case['case_id']}：{case['reason']}"
