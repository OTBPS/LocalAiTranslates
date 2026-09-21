"""Minimal gettext PO reader.

Written by hand rather than adding a `polib` dependency: the three localisation
corpora this project uses are plain PO catalogs, and the parts that matter here
(context, flags, source locations, multi-line strings) are a small subset of
the format.

Obsolete entries (`#~`) are skipped. Fuzzy and untranslated entries are
returned with their flags intact so callers can reject them explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass
class PoEntry:
    msgid: str
    msgstr: str
    msgctxt: str | None = None
    locations: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    line_number: int = 0
    plural: bool = False

    @property
    def fuzzy(self) -> bool:
        return "fuzzy" in self.flags

    @property
    def translated(self) -> bool:
        return bool(self.msgstr.strip())

    @property
    def usable(self) -> bool:
        """A real, reviewed, singular translation."""
        return self.translated and not self.fuzzy and not self.plural and bool(self.msgid.strip())


def unquote(line: str) -> str:
    """Decode one quoted PO string literal."""
    match = re.search(r'"(.*)"\s*$', line)
    if not match:
        return ""
    raw = match.group(1)
    out, index = [], 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            nxt = raw[index + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_po(text: str) -> list[PoEntry]:
    entries: list[PoEntry] = []
    locations: list[str] = []
    flags: list[str] = []
    msgctxt: str | None = None
    msgid: list[str] = []
    msgstr: list[str] = []
    plural = False
    state: str | None = None
    start_line = 0

    def flush() -> None:
        nonlocal msgctxt, msgid, msgstr, locations, flags, state, plural
        if state is not None and ("".join(msgid) or msgctxt):
            entries.append(
                PoEntry(
                    msgid="".join(msgid),
                    msgstr="".join(msgstr),
                    msgctxt=msgctxt,
                    locations=list(locations),
                    flags=list(flags),
                    line_number=start_line,
                    plural=plural,
                )
            )
        msgctxt, msgid, msgstr = None, [], []
        locations, flags = [], []
        state, plural = None, False

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#~"):
            # Obsolete entry: drop whatever was accumulating and skip it.
            flush()
            continue
        if stripped.startswith("#:"):
            locations.extend(stripped[2:].split())
            continue
        if stripped.startswith("#,"):
            flags.extend(part.strip() for part in stripped[2:].split(","))
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("msgctxt "):
            flush()
            start_line = number
            state = "msgctxt"
            msgctxt = unquote(stripped)
            continue
        if stripped.startswith("msgid_plural "):
            plural = True
            state = "msgid_plural"
            continue
        if stripped.startswith("msgid "):
            if state in ("msgstr", "msgstr_plural"):
                flush()
            if not start_line or state is None:
                start_line = number
            state = "msgid"
            msgid = [unquote(stripped)]
            continue
        if stripped.startswith("msgstr["):
            state = "msgstr_plural"
            if stripped.startswith("msgstr[0]"):
                msgstr = [unquote(stripped)]
            continue
        if stripped.startswith("msgstr "):
            state = "msgstr"
            msgstr = [unquote(stripped)]
            continue
        if stripped.startswith('"'):
            piece = unquote(stripped)
            if state == "msgctxt":
                msgctxt = (msgctxt or "") + piece
            elif state == "msgid":
                msgid.append(piece)
            elif state == "msgstr":
                msgstr.append(piece)
            continue
        if not stripped:
            flush()
            start_line = 0
    flush()
    # The catalog header is the entry with an empty msgid.
    return [entry for entry in entries if entry.msgid.strip()]
