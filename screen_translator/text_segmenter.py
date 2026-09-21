"""Deterministic segmentation of manually entered text for translation.

The screenshot pipeline derives blocks from OCR geometry.  Typed or pasted text
has no geometry, so this module splits on document structure instead: blank
lines, list markers, headings and sentence boundaries.  Indentation and list
markers are kept out of the model request and restored verbatim, which makes
numbering and list structure preservation deterministic rather than a property
the model has to get right.

``assemble({})`` reproduces the original document byte for byte.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .core import OcrLine, TextBlock

MAX_INPUT_CHARACTERS = 20000
DEFAULT_MAX_CHARACTERS = 600

_LINE = re.compile(r"(?P<body>[^\r\n]*)(?P<end>\r\n|\r|\n)?")
_NEWLINE = re.compile(r"\r\n|\r|\n")
_MARKER = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>"
    r"#{1,6}[ \t]+"
    r"|>[ \t]*"
    r"|[-*+•·—–][ \t]+"
    r"|\d+[.)、．][ \t]*"
    r"|[（(]\d+[)）][ \t]*"
    r"|[a-zA-Z][.)][ \t]+"
    r"|[一二三四五六七八九十百]+[、.][ \t]*"
    r")"
)
# Split long segments after terminal punctuation so numbered clauses stay intact.
_SENTENCE_END = re.compile(r"[。．！？；.!?;]")


@dataclass(frozen=True)
class Segment:
    """One translation unit plus the literal text framing it."""

    index: int
    prefix: str
    text: str
    suffix: str
    translatable: bool

    @property
    def block_id(self) -> str:
        return str(self.index)


class InputTooLong(ValueError):
    """Raised when the pasted document exceeds the supported size."""


def is_translatable(text: str) -> bool:
    """Match the engine's own skip rule so counts agree with what is sent."""
    return any(character.isalpha() for character in text)


@dataclass(frozen=True)
class SegmentedText:
    leading: str
    segments: tuple[Segment, ...]

    @property
    def translatable_count(self) -> int:
        return sum(1 for segment in self.segments if segment.translatable)

    def blocks(self) -> list[TextBlock]:
        blocks = []
        for segment in self.segments:
            if not segment.translatable:
                continue
            lines = []
            for row, line in enumerate(_NEWLINE.split(segment.text)):
                top = float(row * 20)
                polygon = [(0.0, top), (100.0, top), (100.0, top + 18.0), (0.0, top + 18.0)]
                lines.append(OcrLine(polygon, line, 1.0))
            blocks.append(TextBlock(segment.block_id, lines))
        return blocks

    def assemble(self, values: Mapping[str, str]) -> str:
        parts = [self.leading]
        for segment in self.segments:
            replacement = values.get(segment.block_id) if segment.translatable else None
            body = replacement.strip() if isinstance(replacement, str) and replacement.strip() else segment.text
            parts.append(f"{segment.prefix}{body}{segment.suffix}")
        return "".join(parts)


class _Builder:
    """Accumulate physical lines into one segment while preserving terminators."""

    def __init__(self, prefix: str, *, closed: bool = False):
        self.prefix = prefix
        self.closed = closed
        self.rows: list[tuple[str, str]] = []

    @property
    def length(self) -> int:
        return sum(len(body) for body, _end in self.rows)

    def add(self, body: str, end: str) -> None:
        self.rows.append((body, end))

    def text(self) -> str:
        head = "".join(body + end for body, end in self.rows[:-1])
        return head + self.rows[-1][0]

    def trailing(self) -> str:
        return self.rows[-1][1]


def _iter_lines(text: str):
    position = 0
    while position < len(text):
        match = _LINE.match(text, position)
        yield match.group("body"), match.group("end") or ""
        position = match.end()


def _split_long(prefix: str, text: str, suffix: str, limit: int) -> list[tuple[str, str, str]]:
    """Split an oversized segment at sentence, then line, then hard boundaries."""
    if len(text) <= limit:
        return [(prefix, text, suffix)]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = max((match.end() for match in _SENTENCE_END.finditer(window)), default=0)
        if cut == 0:
            cut = window.rfind("\n") + 1
        if cut == 0:
            cut = limit
        pieces.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        pieces.append(remaining)
    parts: list[tuple[str, str, str]] = []
    for position, piece in enumerate(pieces):
        stripped = piece.lstrip()
        indent = piece[: len(piece) - len(stripped)]
        parts.append(
            (
                prefix + indent if position == 0 else indent,
                stripped,
                suffix if position == len(pieces) - 1 else "",
            )
        )
    return parts


def segment_text(text: str, *, max_characters: int = DEFAULT_MAX_CHARACTERS) -> SegmentedText:
    """Split ``text`` into ordered translation units without losing any character."""
    if len(text) > MAX_INPUT_CHARACTERS:
        raise InputTooLong(f"文本超过 {MAX_INPUT_CHARACTERS} 字符上限")
    if max_characters < 1:
        raise ValueError("max_characters must be positive")

    leading = ""
    raw: list[tuple[str, str, str]] = []  # prefix, text, suffix
    current: _Builder | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        raw.append((current.prefix, current.text(), current.trailing()))
        current = None

    for body, end in _iter_lines(text):
        if not body.strip():
            flush()
            if raw:
                prefix, content, suffix = raw[-1]
                raw[-1] = (prefix, content, suffix + body + end)
            else:
                leading += body + end
            continue
        marker = _MARKER.match(body)
        start = marker.end() if marker else len(body) - len(body.lstrip())
        if current is None or marker or current.closed or current.length + len(body) > max_characters:
            flush()
            # A heading owns exactly one line; wrapped list items may continue.
            heading = bool(marker) and marker.group("marker").startswith("#")
            current = _Builder(body[:start], closed=heading)
            current.add(body[start:], end)
            continue
        current.add(body, end)
    flush()

    segments: list[Segment] = []
    for prefix, content, suffix in raw:
        for part_prefix, part_text, part_suffix in _split_long(prefix, content, suffix, max_characters):
            segments.append(
                Segment(
                    len(segments),
                    part_prefix,
                    part_text,
                    part_suffix,
                    is_translatable(part_text),
                )
            )
    return SegmentedText(leading, tuple(segments))
