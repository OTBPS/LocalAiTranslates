import json

import pytest

from screen_translator.core import (
    CancellationToken,
    Cancelled,
    Config,
    OcrLine,
    merge_lines,
    parse_translation,
    swap_language_pair,
)


def line(x, y, text="Hello", confidence=0.99):
    return OcrLine([(x, y), (x + 100, y), (x + 100, y + 20), (x, y + 20)], text, confidence)


def test_merge_columns_and_low_confidence():
    blocks = merge_lines(
        [line(220, 0), line(0, 28, "world"), line(0, 0), line(220, 28), line(0, 60, confidence=0.1)]
    )
    assert len(blocks) == 2
    assert blocks[0].text == "Hello\nworld"
    assert len(blocks[1].lines) == 2


@pytest.mark.parametrize(
    "raw", ['{"0":"x","0":"y"}', '{"1":"x"}', '{"0":1}', '{"0":""}', '<think>x</think>{"0":"x"}']
)
def test_reject_bad_translation(raw):
    with pytest.raises(ValueError):
        parse_translation(raw, ["0"])


def test_translation():
    assert parse_translation('{"0":"你好"}', ["0"]) == {"0": "你好"}


def test_config_migration(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"hotkey":"Ctrl+Shift+T","old":true}')
    config = Config.load(path)
    assert config.version == 3 and config.hotkey == "Ctrl+Shift+T"
    assert config.source_language == "auto" and config.target_language == "zh-Hans"
    assert config.translation_model == "qwen3-14b-q5-k-m"
    config.save(path)
    assert "old" not in json.loads(path.read_text())


def test_config_normalizes_unsupported_languages(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"version":1,"source_language":"fr","target_language":"xx"}')
    config = Config.load(path)
    assert (config.source_language, config.target_language) == ("auto", "zh-Hans")


def test_version_two_config_adds_translation_model(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"version":2,"source_language":"en","target_language":"zh-Hans"}')
    config = Config.load(path)
    assert config.version == 3
    assert config.translation_model == "qwen3-14b-q5-k-m"


def test_corrupt_config_is_backed_up_and_defaults_are_loaded(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    config = Config.load(path)
    assert config == Config()
    assert not path.exists()
    assert len(list(tmp_path.glob("config.corrupt-*.json"))) == 1


def test_config_normalizes_invalid_field_types(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "hotkey": 123,
                "model_dir": [],
                "startup": "yes",
                "allow_cpu": 1,
                "log_level": "TRACE",
            }
        ),
        encoding="utf-8",
    )
    config = Config.load(path)
    defaults = Config()
    assert config.hotkey == defaults.hotkey
    assert config.model_dir == defaults.model_dir
    assert config.startup is False and config.allow_cpu is False
    assert config.log_level == "WARNING"


def test_swap_language_pair():
    assert swap_language_pair("en", "zh-Hans") == ("zh-Hans", "en")
    assert swap_language_pair("auto", "zh-Hans") is None
    assert swap_language_pair("auto", "zh-Hans", "ja") == ("zh-Hans", "ja")
    assert swap_language_pair("auto", "zh-Hans", "zh-Hans") is None


def test_cancel():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        token.check()


def test_language_boundaries_and_block_size():
    assert len(merge_lines([line(0, 0, "Hello"), line(0, 28, "設定を開く"), line(0, 56, "설정")])) == 3
    assert [len(b.lines) for b in merge_lines([line(0, i * 28) for i in range(9)])] == [8, 1]


def test_numbered_items_and_headings_start_new_blocks():
    blocks = merge_lines(
        [
            line(0, 0, "SEARCH PROCESS"),
            line(0, 28, "1. First item starts here"),
            line(0, 56, "and continues on this wrapped line."),
            line(0, 84, "2. Second item"),
        ]
    )

    assert [block.text for block in blocks] == [
        "SEARCH PROCESS",
        "1. First item starts here\nand continues on this wrapped line.",
        "2. Second item",
    ]
    assert [block.kind for block in blocks] == ["heading", "list-item", "list-item"]
    assert [block.block_id for block in blocks] == ["0", "1", "2"]


def test_numbered_item_continues_at_inclusive_height_boundary():
    first = OcrLine([(21, 451), (747, 451), (747, 469), (21, 469)], "3. First line and", 0.99)
    continuation = OcrLine(
        [(18, 475), (748, 475), (748, 502), (18, 502)],
        "continues on the next OCR line.",
        0.99,
    )

    blocks = merge_lines([continuation, first])

    assert len(blocks) == 1
    assert blocks[0].text == "3. First line and\ncontinues on the next OCR line."
    assert blocks[0].kind == "list-item"


def test_layout_never_merges_aligned_rows_across_columns():
    blocks = merge_lines(
        [
            line(0, 0, "Left first"),
            line(260, 0, "Right first"),
            line(0, 27, "Left continuation"),
            line(260, 27, "Right continuation"),
        ]
    )

    assert [block.text for block in blocks] == [
        "Left first\nLeft continuation",
        "Right first\nRight continuation",
    ]
    assert blocks[0].column_index != blocks[1].column_index
