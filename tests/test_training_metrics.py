from scripts.training.evaluate_models import (
    chrf_score,
    protected_tokens,
    semantic_alignment_flags,
    token_preservation,
    unexpected_repetitions,
)


def test_chrf_is_one_for_identical_text():
    assert chrf_score("设置已保存。", "设置已保存。") == 1.0


def test_chrf_detects_unrelated_or_empty_text():
    assert chrf_score("天气很好。", "文件已保存。") < 0.2
    assert chrf_score("", "文件已保存。") == 0.0


def test_protected_token_preservation():
    source = "Open https://example.com/a?id=42 with API_KEY on 2026-09-20."
    candidate = "使用 API_KEY 在 2026-09-20 打开 https://example.com/a?id=42。"
    assert token_preservation(source, candidate) == 1.0
    assert protected_tokens(source)["API_KEY"] == 1


def test_missing_protected_token_is_penalized():
    assert token_preservation("Error E-104 at 75%", "错误发生在 75%") == 0.5


def test_transliterated_reference_token_is_not_required_verbatim():
    assert token_preservation("President Trump spoke.", "特朗普总统发言。", "特朗普总统发言。") == 1.0


def test_numbers_adjacent_to_chinese_are_preserved():
    source = "The temperature is 80 degrees, 10 above average."
    reference = "温度为80度，比平均值高10度。"
    assert token_preservation(source, reference, reference) == 1.0


def test_unexpected_repetition_counts_only_excess():
    assert unexpected_repetitions("保存完成。保存完成。", "保存完成。") == 1
    assert unexpected_repetitions("重试。重试。重试。", "重试。重试。重试。") == 0


def test_expected_repetition_allows_an_equivalent_paraphrase():
    assert unexpected_repetitions("重新尝试。重新尝试。重新尝试。", "重试。重试。重试。") == 0


def test_semantic_alignment_flags_swapped_batch_outputs():
    predictions = [
        {"id": "a", "translation": "第二句话完全不同。", "reference_text": "第一句话。"},
        {"id": "b", "translation": "第一句话。", "reference_text": "第二句话完全不同。"},
    ]
    flags = semantic_alignment_flags(predictions, [{"records": 2}])
    assert flags == {"a": False, "b": False}
