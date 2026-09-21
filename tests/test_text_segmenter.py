import pytest

from screen_translator.text_segmenter import (
    MAX_INPUT_CHARACTERS,
    InputTooLong,
    Segment,
    segment_text,
)


def bodies(document):
    return [segment.text for segment in document.segments]


def prefixes(document):
    return [segment.prefix for segment in document.segments]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Hello world",
        "第一段\n\n第二段\n",
        "Line one\r\nLine two\r\n\r\nSecond paragraph\r\n",
        "  leading spaces kept\n\t tabbed line\n",
        "\n\n\nonly blank lines above\n\n\n",
        "1. First item\n2. Second item\n3. Third item\n",
        "- alpha\n- beta\n\n# HEADING\n\n> quoted line\n",
        "Trailing newline missing",
        "123\n456\n",
        "!!! ???\n",
    ],
)
def test_assemble_without_translations_reproduces_input(text):
    assert segment_text(text).assemble({}) == text


def test_blank_lines_separate_paragraphs_and_wrapped_lines_stay_together():
    document = segment_text("First line\nstill first paragraph\n\nSecond paragraph\n")

    assert bodies(document) == ["First line\nstill first paragraph", "Second paragraph"]
    assert document.segments[0].suffix == "\n\n"
    assert document.segments[1].suffix == "\n"


def test_numbered_items_become_separate_segments_and_markers_are_not_translated():
    document = segment_text("1. First item\n2) Second item\n（3）第三项\n")

    assert prefixes(document) == ["1. ", "2) ", "（3）"]
    assert bodies(document) == ["First item", "Second item", "第三项"]


def test_bullets_headings_and_quotes_start_new_segments():
    document = segment_text("# Title\nparagraph text\n- bullet one\n> quoted\n")

    assert prefixes(document) == ["# ", "", "- ", "> "]
    assert bodies(document) == ["Title", "paragraph text", "bullet one", "quoted"]


def test_indentation_is_preserved_outside_the_translated_body():
    document = segment_text("    indented paragraph\n\t- indented bullet\n")

    assert prefixes(document) == ["    ", "\t- "]
    assert bodies(document) == ["indented paragraph", "indented bullet"]


def test_numbering_survives_translation_verbatim():
    document = segment_text("1. Alpha\n2. Beta\n")
    values = {"0": "第一项", "1": "第二项"}

    assert document.assemble(values) == "1. 第一项\n2. 第二项\n"


def test_translation_values_are_applied_in_index_order_regardless_of_mapping_order():
    document = segment_text("one\n\ntwo\n\nthree\n")
    values = {"2": "三", "0": "一", "1": "二"}

    assert document.assemble(values) == "一\n\n二\n\n三\n"


def test_long_paragraph_splits_at_sentence_boundaries_without_losing_text():
    sentences = "".join(f"This is sentence number {index}. " for index in range(40))
    document = segment_text(sentences, max_characters=200)

    assert len(document.segments) > 1
    assert all(len(segment.text) <= 200 for segment in document.segments)
    assert document.assemble({}) == sentences


def test_long_paragraph_without_punctuation_is_hard_split_without_losing_text():
    text = "x" * 500
    document = segment_text(text, max_characters=120)

    assert len(document.segments) == 5
    assert document.assemble({}) == text


def test_wrapped_lines_split_before_exceeding_the_limit():
    text = "".join(f"line {index} padded with filler words\n" for index in range(12))
    document = segment_text(text, max_characters=120)

    assert len(document.segments) > 1
    assert document.assemble({}) == text


def test_segments_without_letters_are_not_sent_to_the_model():
    document = segment_text("12345\n\n!!! ???\n\nReal text\n")

    assert [segment.translatable for segment in document.segments] == [False, False, True]
    assert document.translatable_count == 1
    assert [block.block_id for block in document.blocks()] == ["2"]


def test_cjk_segments_are_translatable():
    document = segment_text("你好世界\n\nこんにちは\n\n안녕하세요\n")

    assert document.translatable_count == 3


def test_blocks_carry_one_line_per_physical_line_and_keep_the_body_text():
    document = segment_text("first line\nsecond line\n")
    block = document.blocks()[0]

    assert [line.text for line in block.lines] == ["first line", "second line"]
    assert block.text == "first line\nsecond line"
    assert block.rect == (0.0, 0.0, 100.0, 38.0)


def test_block_ids_are_unique_and_match_segment_indices():
    document = segment_text("1. a\n2. b\n\n123\n\n3. c\n")
    ids = [block.block_id for block in document.blocks()]

    assert ids == ["0", "1", "3"]
    assert len(set(ids)) == len(ids)


def test_empty_and_whitespace_only_input_produce_no_blocks():
    for text in ("", "   ", "\n\n\t\n"):
        document = segment_text(text)
        assert document.blocks() == []
        assert document.translatable_count == 0
        assert document.assemble({}) == text


def test_blank_translation_values_fall_back_to_the_source_text():
    document = segment_text("Hello\n")

    assert document.assemble({"0": "   "}) == "Hello\n"
    assert document.assemble({}) == "Hello\n"


def test_translated_values_are_trimmed_so_markers_do_not_double_space():
    document = segment_text("1. Hello\n")

    assert document.assemble({"0": "  你好  "}) == "1. 你好\n"


def test_input_above_the_limit_is_rejected():
    with pytest.raises(InputTooLong):
        segment_text("a" * (MAX_INPUT_CHARACTERS + 1))

    assert segment_text("a" * MAX_INPUT_CHARACTERS).translatable_count >= 1


def test_segment_exposes_a_string_block_id():
    segment = Segment(3, "- ", "text", "\n", True)

    assert segment.block_id == "3"
