"""Reading-order and semantic block analysis for OCR lines."""

from __future__ import annotations

import re
from statistics import median

from .core import OcrLine, TextBlock

_NUMBERED_ITEM = re.compile(r"^\s*\d+\s*[.)]\s*")


def _script(text: str) -> str:
    if any("\uac00" <= char <= "\ud7af" for char in text):
        return "korean"
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "japanese"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "han"
    return "latin"


def _kind(text: str) -> str:
    stripped = text.strip()
    if _NUMBERED_ITEM.match(stripped):
        return "list-item"
    letters = [char for char in stripped if char.isascii() and char.isalpha()]
    if 2 <= len(letters) <= 48 and all(not char.islower() for char in letters):
        return "heading"
    return "paragraph"


class LayoutAnalyzer:
    """Build stable semantic blocks without crossing columns or headings."""

    def __init__(self, *, max_lines: int = 8, max_characters: int = 1200):
        self.max_lines = max_lines
        self.max_characters = max_characters

    @staticmethod
    def _can_continue(block: TextBlock, line: OcrLine) -> tuple[bool, float]:
        if block.kind == "heading" or _kind(line.text) != "paragraph":
            return False, 0.0
        if _script(block.lines[-1].text) != _script(line.text):
            return False, 0.0

        x1, y1, _x2, y2 = line.rect
        previous_x1, previous_y1, _previous_x2, previous_y2 = block.lines[-1].rect
        current_height = max(1.0, y2 - y1)
        previous_height = max(1.0, previous_y2 - previous_y1)
        local_height = median(
            [
                max(1.0, existing.rect[3] - existing.rect[1])
                for existing in block.lines[-3:]
            ]
            + [current_height]
        )
        gap = y1 - previous_y2
        height_ratio = current_height / previous_height
        aligned = abs(previous_x1 - x1) <= max(10.0, 0.8 * local_height)
        vertically_close = -0.15 * local_height <= gap <= 0.8 * local_height
        compatible_height = 0.55 <= height_ratio <= 1.8
        return aligned and vertically_close and compatible_height, abs(gap)

    def analyze(self, lines: list[OcrLine]) -> list[TextBlock]:
        ordered = sorted(
            (line for line in lines if line.text.strip() and line.confidence >= 0.45),
            key=lambda line: (line.rect[1], line.rect[0]),
        )
        groups: list[TextBlock] = []
        column_starts: list[float] = []
        for line in ordered:
            candidates: list[tuple[float, TextBlock]] = []
            for block in groups:
                if len(block.lines) >= self.max_lines:
                    continue
                if len(block.text) + len(line.text) > self.max_characters:
                    continue
                allowed, distance = self._can_continue(block, line)
                if allowed:
                    candidates.append((distance, block))
            if candidates:
                min(candidates, key=lambda candidate: candidate[0])[1].lines.append(line)
                continue

            x1 = line.rect[0]
            matching_column = next(
                (index for index, start in enumerate(column_starts) if abs(start - x1) <= 32),
                None,
            )
            if matching_column is None:
                matching_column = len(column_starts)
                column_starts.append(x1)
            groups.append(TextBlock("", [line], _kind(line.text), matching_column))

        for index, block in enumerate(groups):
            block.block_id = str(index)
        return groups
