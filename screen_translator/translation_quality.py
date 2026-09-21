"""Content-free validation of structured translation results."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .core import TextBlock

_LEADING_NUMBER = re.compile(r"^\s*(\d+)\s*[.)、．]")
_IGNORED = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalized(text: str) -> str:
    return _IGNORED.sub("", text).casefold()


def repair_list_number(block: TextBlock, target: str) -> tuple[str, bool]:
    """Repair a list marker deterministically instead of spending a model retry."""
    source_number = _LEADING_NUMBER.match(block.text)
    if not source_number:
        return target, False
    target_number = _LEADING_NUMBER.match(target)
    if target_number and target_number.group(1) == source_number.group(1):
        return target, False
    remainder = target[target_number.end() :] if target_number else target
    return f"{source_number.group(1)}. {remainder.lstrip()}", True


def find_translation_issues(
    blocks: Sequence[TextBlock], values: Mapping[str, str]
) -> dict[str, set[str]]:
    """Return suspicious block IDs and reason codes without exposing content."""
    issues: dict[str, set[str]] = {}

    def flag(block_id: str, reason: str) -> None:
        issues.setdefault(block_id, set()).add(reason)

    normalized: list[tuple[TextBlock, str]] = []
    for block in blocks:
        target = values.get(block.block_id, "")
        source_number = _LEADING_NUMBER.match(block.text)
        target_number = _LEADING_NUMBER.match(target)
        if source_number and not target_number:
            flag(block.block_id, "number-missing")
        elif source_number and target_number and source_number.group(1) != target_number.group(1):
            flag(block.block_id, "number-mismatch")

        source_length = len(_normalized(block.text))
        target_length = len(_normalized(target))
        if source_length >= 40 and (target_length < source_length * 0.03 or target_length > source_length * 8):
            flag(block.block_id, "length-outlier")
        normalized.append((block, _normalized(target)))

    for (left_block, left), (right_block, right) in zip(normalized, normalized[1:], strict=False):
        if min(len(left), len(right)) < 12:
            continue
        if left == right:
            flag(left_block.block_id, "adjacent-duplicate")
            flag(right_block.block_id, "adjacent-duplicate")
        elif right in left:
            flag(left_block.block_id, "contains-neighbor")
        elif left in right:
            flag(right_block.block_id, "contains-neighbor")
    return issues
