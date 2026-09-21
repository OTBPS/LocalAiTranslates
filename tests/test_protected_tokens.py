"""protected token 指标：保护真正不可翻译的内容，不惩罚正确的本地化。

每个用例都对应 eval-v1 上一个被旧指标误判的真实记录。
"""

import pytest

from scripts.training.evaluate_models import numeric_tokens, protected_tokens, token_preservation


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/a?id=42",
        "support@example.com",
        r"C:\Users\test\config.json",
        "API_KEY_2",
        "Qwen3-8B",
        "E-104",
        "v1.2.3",
    ],
)
def test_untranslatable_tokens_are_protected(text):
    assert protected_tokens(text), f"{text} 应当被保护"


@pytest.mark.parametrize("text", ["FBI", "ATM", "BST", "NASA", "OK"])
def test_bare_all_caps_words_are_not_protected(text):
    """FBI→联邦调查局 是正确翻译，不应被判为丢失 token。"""
    assert not protected_tokens(text)


def test_abbreviation_translated_into_chinese_still_scores_full():
    # eval-en-news-009: 源 "60 FBI", 模型译出 60 但把 FBI 意译了
    assert token_preservation("60 FBI agents responded.", "60 名联邦调查局探员到场。") == 1.0
    # eval-en-news-012: 源 "26,750 ATM"
    assert token_preservation("26,750 ATM withdrawals", "26,750 笔自动取款机取款") == 1.0


def test_localised_score_format_scores_full():
    # eval-en-news-049: 源 "3-1", 中文写成 "3比1"
    assert token_preservation("They won 3-1.", "他们以 3比1 获胜。") == 1.0
    # eval-en-news-042: 源 "13-21-3"
    assert token_preservation("record of 13-21-3", "战绩为 13胜21负3平") == 1.0


def test_clock_times_are_not_compared_literally():
    # eval-en-long-005: 源 "10:15 BST"
    assert token_preservation("at 10:15 BST", "在英国夏令时上午10点15分") == 1.0
    assert not numeric_tokens("10:15")


def test_thousands_separators_normalise():
    assert token_preservation("26,750 items", "26750 件") == 1.0
    assert token_preservation("26750 items", "26,750 件") == 1.0


def test_leading_zeros_normalise():
    assert numeric_tokens("04") == numeric_tokens("4")


def test_localised_scoreline_may_collapse_repeated_digits():
    # eval-en-news-034: 源 "5-0-0"（5胜0负0平），中文习惯写"5胜0负"
    source = "one of 4 players to ever go 5-0-0 since 1979"
    reference = "自1979年以来仅有的4位取得5-0-0战绩的选手之一"
    candidate = "自1979年以来仅有的4位保持5胜0负战绩的选手之一"
    assert token_preservation(source, candidate, reference) == 1.0


def test_a_number_absent_from_the_candidate_is_still_penalised():
    # 数字按集合比较，但整类数字缺失仍必须扣分
    assert token_preservation("5 wins and 7 losses", "5 胜") == 0.5


def test_a_dropped_url_is_still_penalised():
    assert token_preservation("See https://example.com/x now", "请查看。") == 0.0


def test_a_dropped_identifier_is_still_penalised():
    assert token_preservation("Error E-104 occurred", "发生了错误。") == 0.0


def test_a_dropped_number_is_still_penalised():
    assert token_preservation("Wait 30 seconds", "请稍候。") == 0.0


def test_numbers_inside_literal_tokens_are_not_double_counted():
    # The 42 inside the URL must not also be demanded as a bare number.
    assert numeric_tokens("https://example.com/a?id=42") == {}
    assert token_preservation("https://example.com/a?id=42", "https://example.com/a?id=42") == 1.0


def test_partial_preservation_is_proportional():
    # One literal kept, one number dropped.
    assert token_preservation("API_KEY_2 expires in 30 days", "API_KEY_2 已过期。") == 0.5


def test_reference_intersection_still_suppresses_transliteration():
    assert token_preservation("President Trump spoke.", "特朗普总统发言。", "特朗普总统发言。") == 1.0
