"""PO 解析：必须正确排除 fuzzy、未翻译、废弃和复数条目。"""

from scripts.training.po_reader import parse_po, unquote

SAMPLE = '''# Chinese translation
msgid ""
msgstr ""
"Project-Id-Version: test\\n"
"Language: zh_CN\\n"

#: editor/editor_node.cpp:123
msgid "Save Scene"
msgstr "保存场景"

#: editor/editor_node.cpp:456
#, fuzzy
msgid "Open Scene"
msgstr "打开场景"

#: editor/editor_node.cpp:789
msgid "Untranslated"
msgstr ""

#: doc/intro.rst:12 doc/intro.rst:30
msgid ""
"A long paragraph that was "
"wrapped across lines."
msgstr ""
"一个跨行折叠的"
"长段落。"

msgctxt "menu"
msgid "File"
msgstr "文件"

#, c-format
msgid "Found %d items in %s"
msgstr "在 %s 中找到 %d 个项目"

msgid "one apple"
msgid_plural "%d apples"
msgstr[0] "一个苹果"
msgstr[1] "%d 个苹果"

#~ msgid "Removed string"
#~ msgstr "已删除"
'''


def by_id(entries):
    return {entry.msgid: entry for entry in entries}


def test_header_is_not_returned_as_an_entry():
    assert all(entry.msgid.strip() for entry in parse_po(SAMPLE))


def test_plain_entry_is_parsed_with_location():
    entry = by_id(parse_po(SAMPLE))["Save Scene"]

    assert entry.msgstr == "保存场景"
    assert entry.locations == ["editor/editor_node.cpp:123"]
    assert entry.usable is True


def test_fuzzy_entry_is_flagged_and_not_usable():
    entry = by_id(parse_po(SAMPLE))["Open Scene"]

    assert entry.fuzzy is True
    assert entry.usable is False


def test_untranslated_entry_is_not_usable():
    entry = by_id(parse_po(SAMPLE))["Untranslated"]

    assert entry.translated is False
    assert entry.usable is False


def test_multiline_strings_are_concatenated():
    entry = by_id(parse_po(SAMPLE))["A long paragraph that was wrapped across lines."]

    assert entry.msgstr == "一个跨行折叠的长段落。"
    assert len(entry.locations) == 2


def test_context_is_captured():
    entry = by_id(parse_po(SAMPLE))["File"]

    assert entry.msgctxt == "menu"
    assert entry.msgstr == "文件"


def test_format_flags_are_preserved():
    entry = by_id(parse_po(SAMPLE))["Found %d items in %s"]

    assert "c-format" in entry.flags
    assert entry.usable is True


def test_plural_entries_are_excluded_from_usable():
    entry = by_id(parse_po(SAMPLE))["one apple"]

    assert entry.plural is True
    assert entry.usable is False


def test_obsolete_entries_are_dropped():
    assert "Removed string" not in by_id(parse_po(SAMPLE))


def test_escape_sequences_are_decoded():
    assert unquote(r'msgid "line1\nline2\ttab\"quote\\back"') == 'line1\nline2\ttab"quote\\back'


def test_newline_inside_a_translation_survives():
    catalog = 'msgid "a\\nb"\nmsgstr "甲\\n乙"\n'
    entry = parse_po(catalog)[0]

    assert entry.msgid == "a\nb"
    assert entry.msgstr == "甲\n乙"
