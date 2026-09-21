from unittest.mock import Mock

import pytest

from screen_translator.core import CancellationToken, Cancelled, OcrLine, TextBlock, TranslatedBlock
from screen_translator.engines import TranslationEngine
from screen_translator.models import TRANSLATION_MODELS
from screen_translator.translation_engine import plan_translation_batches
from screen_translator.translation_quality import find_translation_issues, repair_list_number


def test_numbers_and_symbols_skip_model(tmp_path):
    engine = TranslationEngine(tmp_path)
    engine.start = Mock(side_effect=AssertionError("Model should not start"))
    blocks = [TextBlock("0", [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "123.45% + 67", 0.99)])]
    result = engine.translate(blocks, CancellationToken(), lambda _: None)
    assert result[0].text == "123.45% + 67"


def test_translation_passes_selected_language_pair(tmp_path):
    engine = TranslationEngine(tmp_path)
    engine.start = Mock()
    engine.request = Mock(return_value={"0": "Open settings"})
    blocks = [TextBlock("0", [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "設定を開く", 0.99, "ja")])]
    result = engine.translate(blocks, CancellationToken(), lambda _: None, "ja", "en")
    assert result[0].text == "Open settings"
    args = engine.request.call_args.args
    assert args[2:4] == ("ja", "en")


def test_same_language_skips_model(tmp_path):
    engine = TranslationEngine(tmp_path)
    engine.start = Mock(side_effect=AssertionError("Model should not start"))
    blocks = [TextBlock("0", [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "English", 0.99, "en")])]
    assert engine.translate(blocks, CancellationToken(), lambda _: None, "en", "en")[0].text == "English"


def test_translation_engine_uses_selected_model(tmp_path):
    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m")
    assert engine.model.filename == "Qwen3-8B-Q5_K_M.gguf"
    assert engine.parallel_slots == 2


def test_translation_engine_exposes_local_4b_mode(tmp_path):
    engine = TranslationEngine(tmp_path, model_id="qwen3-4b-instruct-2507-q8-0")
    assert engine.model.filename == "Qwen3-4B-Instruct-2507-Q8_0.gguf"
    assert engine.parallel_slots == 2


def test_8b_failure_falls_back_to_installed_14b(tmp_path):
    fallback_model = TRANSLATION_MODELS["qwen3-14b-q5-k-m"]
    (tmp_path / fallback_model.filename).write_bytes(b"installed")
    block = TextBlock(
        "0",
        [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "Open settings", 0.99)],
    )
    fallback = Mock()
    fallback.translate.return_value = [TranslatedBlock(block, "打开设置")]
    fallback_factory = Mock(return_value=fallback)
    progress = Mock()
    engine = TranslationEngine(
        tmp_path,
        model_id="qwen3-8b-q5-k-m",
        fallback_factory=fallback_factory,
    )
    engine._translate_once = Mock(side_effect=RuntimeError("primary failed"))

    result = engine.translate([block], CancellationToken(), progress, "en", "zh-Hans")

    assert result[0].text == "打开设置"
    fallback_factory.assert_called_once_with(
        tmp_path.resolve(),
        False,
        "qwen3-14b-q5-k-m",
        1,
    )
    fallback.translate.assert_called_once()
    fallback.stop.assert_called_once()
    assert "回退" in progress.call_args.args[0]


def test_cancellation_never_starts_fallback(tmp_path):
    fallback_model = TRANSLATION_MODELS["qwen3-14b-q5-k-m"]
    (tmp_path / fallback_model.filename).write_bytes(b"installed")
    fallback_factory = Mock()
    engine = TranslationEngine(
        tmp_path,
        model_id="qwen3-8b-q5-k-m",
        fallback_factory=fallback_factory,
    )
    engine._translate_once = Mock(side_effect=Cancelled())

    with pytest.raises(Cancelled):
        engine.translate([], CancellationToken(), Mock())

    fallback_factory.assert_not_called()


@pytest.mark.parametrize(
    ("source_language", "detected_language"),
    [("ko", None), ("auto", "ko")],
)
def test_smaller_models_route_korean_to_installed_14b(
    tmp_path, source_language, detected_language
):
    fallback_model = TRANSLATION_MODELS["qwen3-14b-q5-k-m"]
    (tmp_path / fallback_model.filename).write_bytes(b"installed")
    block = TextBlock(
        "0",
        [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "설정 열기", 0.99, "ko")],
    )
    fallback = Mock()
    fallback.translate.return_value = [TranslatedBlock(block, "打开设置")]
    fallback_factory = Mock(return_value=fallback)
    engine = TranslationEngine(
        tmp_path,
        model_id="qwen3-4b-instruct-2507-q8-0",
        fallback_factory=fallback_factory,
    )
    engine._translate_once = Mock(side_effect=AssertionError("4B should not run for Korean"))

    result = engine.translate(
        [block],
        CancellationToken(),
        Mock(),
        source_language,
        "zh-Hans",
        detected_language,
    )

    assert result[0].text == "打开设置"
    fallback.translate.assert_called_once()
    fallback.stop.assert_called_once()


def test_korean_uses_selected_model_when_14b_is_not_installed(tmp_path):
    engine = TranslationEngine(tmp_path, model_id="qwen3-4b-instruct-2507-q8-0")
    engine._translate_once = Mock(return_value=[])

    assert engine.translate([], CancellationToken(), Mock(), "ko", "zh-Hans") == []
    engine._translate_once.assert_called_once()


def test_long_documents_use_small_batches_to_prevent_cross_block_drift():
    blocks = [
        TextBlock(
            str(index),
            [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "x" * 250, 0.99)],
        )
        for index in range(9)
    ]

    batches = plan_translation_batches(blocks)

    assert [len(batch) for batch in batches] == [5, 4]
    assert all(sum(len(block.text) for block in batch) <= 1400 for batch in batches)


def test_short_screens_keep_the_low_overhead_batch_size():
    blocks = [
        TextBlock(
            str(index),
            [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "Open settings", 0.99)],
        )
        for index in range(8)
    ]

    assert [len(batch) for batch in plan_translation_batches(blocks)] == [8]


def test_quality_validator_flags_only_block_that_contains_neighbor():
    blocks = [
        TextBlock("0", [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "3. First item", 0.99)]),
        TextBlock("1", [OcrLine([(0, 25), (50, 25), (50, 45), (0, 45)], "continued policy", 0.99)]),
    ]
    values = {
        "0": "3. 第一项内容以及需要被错误提前翻译的完整政策说明内容",
        "1": "需要被错误提前翻译的完整政策说明内容",
    }

    assert find_translation_issues(blocks, values) == {"0": {"contains-neighbor"}}


def test_list_number_is_repaired_without_model_retry():
    block = TextBlock(
        "7",
        [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "12. Accept an offer", 0.99)],
    )

    assert repair_list_number(block, "接受录用通知") == ("12. 接受录用通知", True)
    assert repair_list_number(block, "12. 接受录用通知") == ("12. 接受录用通知", False)


def test_suspicious_translation_is_retried_as_one_block(tmp_path):
    blocks = [
        TextBlock("0", [OcrLine([(0, 0), (50, 0), (50, 20), (0, 20)], "3. First item", 0.99)]),
        TextBlock("1", [OcrLine([(0, 25), (50, 25), (50, 45), (0, 45)], "continued policy", 0.99)]),
    ]
    engine = TranslationEngine(tmp_path)
    engine.start = Mock()
    engine.request = Mock(
        side_effect=[
            {
                "0": "3. 第一项内容以及需要被错误提前翻译的完整政策说明内容",
                "1": "需要被错误提前翻译的完整政策说明内容",
            },
            {"0": "3. 第一项内容"},
        ]
    )

    result = engine._translate_once(blocks, CancellationToken(), Mock(), "en", "zh-Hans")

    assert [item.text for item in result] == ["3. 第一项内容", "需要被错误提前翻译的完整政策说明内容"]
    assert engine.request.call_count == 2
    assert engine.request.call_args_list[1].args[0] == [blocks[0]]
    assert engine.last_metrics["quality_retries"] == 1


def test_parallel_batches_restore_original_batch_order(tmp_path):
    engine = TranslationEngine(tmp_path, parallel_slots=2)
    batches = [
        [TextBlock("0", [OcrLine([(0, 0), (10, 0), (10, 10), (0, 10)], "A", 0.99)])],
        [TextBlock("1", [OcrLine([(0, 0), (10, 0), (10, 10), (0, 10)], "B", 0.99)])],
    ]
    engine.request = Mock(side_effect=lambda batch, *_args: {batch[0].block_id: batch[0].text})

    values = engine._request_batches(batches, CancellationToken(), "en", "zh-Hans")

    assert values == [{"0": "A"}, {"1": "B"}]
