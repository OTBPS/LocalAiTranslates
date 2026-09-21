"""Build the harder gold layers from open-source localisation catalogs.

Layers are **mutually exclusive**: a record carries exactly one primary
category, plus any number of descriptive analysis tags. The adversarial layer
is selected first (it is the scarcest), then software UI, game dialogue and
finally continuous long documents.

Long documents are consecutive paragraphs of one documentation page, kept in
their original order — never unrelated sentences stitched together.

Every record cites repository, commit, file, file digest, original entry id,
licence and the rule that selected it. Records are rejected if they duplicate,
exactly or approximately, anything already present in train/dev/eval/fixtures
or in an earlier layer.

    python -m scripts.training.build_gold_layers --direction en-zh \\
        --output-dir D:\\AI\\Training\\screen-translator\\data\\gold\\layers-v0\\en-zh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

from scripts.training.po_reader import PoEntry, parse_po
from scripts.training.training_paths import workspace_path

DIRECTIONS = {"en-zh": ("en", "zh-Hans"), "zh-en": ("zh-Hans", "en")}
DEFAULT_QUOTA = {"long_document": 20, "software_ui": 15, "game_dialogue": 10, "adversarial_format": 15}

TAG_PATTERNS = {
    "placeholder": re.compile(r"%[#0\- +]?\d*(?:\.\d+)?[sdifgexculo]|%\([^)]+\)[sd]|\{\w*\}|\$\w+"),
    "shortcut": re.compile(r"\b(?:Ctrl|Alt|Shift|Cmd|Meta|Super)\s*\+\s*\S", re.IGNORECASE),
    "path": re.compile(r"res://|user://|(?:[A-Za-z]:\\)|/\w+/\w+|\w+\.(?:png|json|cfg|gd|tscn|po|txt|cpp|h)\b"),
    "markup_tag": re.compile(r"<[^<>\s][^<>]*>|\[/?[a-zA-Z][^\]]*\]"),
    "newline": re.compile(r"\n"),
    "time": re.compile(r"\b\d{1,2}:\d{2}\b"),
    "score": re.compile(r"\b\d+\s*[-–]\s*\d+\b"),
    "number": re.compile(r"\d"),
    "identifier": re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:_[A-Za-z0-9]+)+\b|\b[A-Z]{2,}\b"),
}
# Tags that make a record genuinely adversarial for a translator.
ADVERSARIAL_TAGS = ("placeholder", "shortcut", "path", "markup_tag", "time", "score", "newline")


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def shingles(text: str, size: int = 5) -> set[str]:
    key = normalize(text)
    if len(key) <= size:
        return {key} if key else set()
    return {key[index : index + size] for index in range(len(key) - size + 1)}


def similar(text: str, pool: list[set[str]], threshold: float) -> bool:
    """Approximate duplicate check via character-shingle Jaccard."""
    candidate = shingles(text)
    if not candidate:
        return True
    for other in pool:
        if not other:
            continue
        overlap = len(candidate & other)
        if overlap and overlap / len(candidate | other) >= threshold:
            return True
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tags_for(text: str) -> list[str]:
    return sorted(name for name, pattern in TAG_PATTERNS.items() if pattern.search(text))


def existing_keys(root: Path) -> set[str]:
    seen: set[str] = set()
    patterns = (
        "data/eval/*/*.jsonl", "data/dev/*/*.jsonl", "data/train/*/teacher_blocks.jsonl",
        "data/gold/*/*/*.jsonl", "fixtures/*.json",
    )
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                for case in json.loads(text):
                    for value in case.values():
                        if isinstance(value, str) and len(normalize(value)) >= 12:
                            seen.add(normalize(value))
                continue
            for line in text.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                for key in ("source_text", "reference_text"):
                    value = row.get(key)
                    if isinstance(value, str):
                        for piece in value.split("\n"):
                            if len(normalize(piece)) >= 12:
                                seen.add(normalize(piece))
    return seen


def load_corpus(cache: Path, manifest: dict, name: str) -> list[tuple[dict, PoEntry, str]]:
    """Return (source metadata, entry, file digest) for every usable PO entry."""
    source = manifest["sources"][name]
    digests = {item["file"]: item["sha256"] for item in source["files"]}
    out = []
    for item in source["files"]:
        path = cache / name / item["file"]
        for entry in parse_po(path.read_text(encoding="utf-8")):
            if entry.usable:
                out.append((source, entry, digests[item["file"]]))
    return out


def make_record(args, ordinal, layer, source_text, reference_text, tags, provenance) -> dict:
    source_language, target_language = DIRECTIONS[args.direction]
    return {
        "id": f"goldl-{args.direction}-{layer}-{ordinal:03d}",
        "source_language": source_language,
        "target_language": target_language,
        "domain": layer,
        "analysis_tags": tags,
        "source_text": source_text,
        "reference_text": reference_text,
        "held_out": True,
        "training_use_prohibited": True,
        "provenance": provenance,
    }


def build(args) -> tuple[list[dict], dict]:
    source_language, _target = DIRECTIONS[args.direction]
    english_is_source = source_language == "en"
    manifest = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))
    taken = existing_keys(args.workspace)
    for path in args.exclude:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                for key in ("source_text", "reference_text"):
                    if isinstance(row.get(key), str):
                        taken.add(normalize(row[key]))

    rng = random.Random(args.seed)
    chosen_shingles: list[set[str]] = []
    records: list[dict] = []
    rejected: Counter[str] = Counter()

    def accept(text_source: str, text_reference: str) -> bool:
        if not text_source.strip() or not text_reference.strip():
            rejected["empty"] += 1
            return False
        if len(normalize(text_source)) < args.min_chars:
            rejected["too_short"] += 1
            return False
        if normalize(text_source) in taken or normalize(text_reference) in taken:
            rejected["exact_duplicate"] += 1
            return False
        if similar(text_source, chosen_shingles, args.similarity):
            rejected["near_duplicate"] += 1
            return False
        return True

    def commit(layer, ordinal, src, ref, tags, provenance):
        records.append(make_record(args, ordinal, layer, src, ref, tags, provenance))
        chosen_shingles.append(shingles(src))
        taken.add(normalize(src))
        taken.add(normalize(ref))

    # ---- candidate pools -------------------------------------------------
    ui_pool = load_corpus(args.cache, manifest, "godot-editor")
    game_pool = load_corpus(args.cache, manifest, "wesnoth")
    rng.shuffle(ui_pool)
    rng.shuffle(game_pool)

    def sides(entry: PoEntry) -> tuple[str, str]:
        return (entry.msgid, entry.msgstr) if english_is_source else (entry.msgstr, entry.msgid)

    def provenance_of(source, entry, digest, rule, corpus) -> dict:
        return {
            "corpus": corpus,
            "repository": source["repository"],
            "commit": source["commit"],
            "license": source["license"],
            "attribution": source["attribution"],
            "file_sha256": digest,
            "entry_id": f"{entry.locations[0] if entry.locations else 'unknown'}#L{entry.line_number}",
            "po_line": entry.line_number,
            "po_locations": entry.locations[:4],
            "msgctxt": entry.msgctxt,
            "extraction_rule": rule,
        }

    # ---- 1. adversarial: scarcest, so it picks first ---------------------
    quota = dict(DEFAULT_QUOTA)
    quota.update(args.quota or {})
    adversarial = []
    for corpus, pool in (("godot-editor", ui_pool), ("wesnoth", game_pool)):
        for source, entry, digest in pool:
            src, ref = sides(entry)
            tags = tags_for(entry.msgid) or []
            hits = [tag for tag in ADVERSARIAL_TAGS if tag in tags]
            if len(hits) >= args.adversarial_tags:
                adversarial.append((corpus, source, entry, digest, tags, len(hits)))
    adversarial.sort(key=lambda item: -item[5])
    ordinal = 0
    for corpus, source, entry, digest, tags, _hits in adversarial:
        if ordinal >= quota["adversarial_format"]:
            break
        src, ref = sides(entry)
        if not accept(src, ref):
            continue
        commit(
            "adversarial_format", ordinal, src, ref, tags,
            provenance_of(source, entry, digest,
                          f"PO entry carrying >={args.adversarial_tags} adversarial tags", corpus),
        )
        ordinal += 1

    # ---- 2. software UI --------------------------------------------------
    ordinal = 0
    for source, entry, digest in ui_pool:
        if ordinal >= quota["software_ui"]:
            break
        src, ref = sides(entry)
        if not accept(src, ref):
            continue
        commit(
            "software_ui", ordinal, src, ref, tags_for(entry.msgid),
            provenance_of(source, entry, digest, "Godot editor UI string", "godot-editor"),
        )
        ordinal += 1

    # ---- 3. game dialogue ------------------------------------------------
    ordinal = 0
    for source, entry, digest in game_pool:
        if ordinal >= quota["game_dialogue"]:
            break
        src, ref = sides(entry)
        if not accept(src, ref):
            continue
        commit(
            "game_dialogue", ordinal, src, ref, tags_for(entry.msgid),
            provenance_of(source, entry, digest,
                          "Wesnoth campaign dialogue, zh_CN locale, non-fuzzy", "wesnoth"),
        )
        ordinal += 1

    # ---- 4. continuous long documents ------------------------------------
    docs = manifest["sources"]["godot-docs"]
    digests = {item["file"]: item["sha256"] for item in docs["files"]}
    ordinal = 0
    for item in docs["files"]:
        if ordinal >= quota["long_document"]:
            break
        path = args.cache / "godot-docs" / item["file"]
        entries = [entry for entry in parse_po(path.read_text(encoding="utf-8")) if entry.usable]
        # Consecutive PO entries are consecutive paragraphs of one page.
        window = args.paragraphs
        for start in range(0, len(entries) - window + 1, window):
            if ordinal >= quota["long_document"]:
                break
            group = entries[start : start + window]
            src = "\n\n".join(sides(entry)[0] for entry in group)
            ref = "\n\n".join(sides(entry)[1] for entry in group)
            if not accept(src, ref):
                continue
            tags = sorted({tag for entry in group for tag in tags_for(entry.msgid)})
            commit(
                "long_document", ordinal, src, ref, tags,
                {
                    "corpus": "godot-docs",
                    "repository": docs["repository"],
                    "commit": docs["commit"],
                    "license": docs["license"],
                    "attribution": docs["attribution"],
                    "file_sha256": digests[item["file"]],
                    "entry_id": f"{item['file']}#L{group[0].line_number}-L{group[-1].line_number}",
                    "po_line_range": [group[0].line_number, group[-1].line_number],
                    "paragraphs": len(group),
                    "po_locations": [loc for entry in group for loc in entry.locations[:1]],
                    "extraction_rule": (
                        f"{window} consecutive paragraphs of one documentation page, original order"
                    ),
                },
            )
            ordinal += 1

    counts = Counter(record["domain"] for record in records)
    report = {
        "schema_version": 1,
        "direction": args.direction,
        "records": len(records),
        "layers": dict(sorted(counts.items())),
        "quota": quota,
        "shortfalls": {layer: quota[layer] - counts.get(layer, 0)
                       for layer in quota if counts.get(layer, 0) < quota[layer]},
        "rejected": dict(rejected),
        "seed": args.seed,
        "similarity_threshold": args.similarity,
        "min_chars": args.min_chars,
        "licenses": sorted({record["provenance"]["license"] for record in records}),
        "corpora": sorted({record["provenance"]["corpus"] for record in records}),
        "analysis_tag_counts": dict(
            sorted(Counter(tag for record in records for tag in record["analysis_tags"]).items())
        ),
        "held_out": True,
        "training_use_prohibited": True,
        "release_gold": False,
        "provisional": True,
        "provisional_reason": "awaiting two independent human annotations, arbitration and agreement",
        "reporting_note": (
            "open-source localisation corpora; report separately from FLORES and from the "
            "product evaluation sets"
        ),
    }
    return records, report


def parse_quota(values: list[str] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in values or []:
        name, _, count = item.partition("=")
        out[name.strip()] = int(count)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--direction", choices=tuple(DIRECTIONS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=workspace_path("cache/l10n"))
    parser.add_argument("--workspace", type=Path, default=workspace_path(""))
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--quota", action="append", metavar="LAYER=N")
    parser.add_argument("--paragraphs", type=int, default=3)
    parser.add_argument("--adversarial-tags", type=int, default=2)
    parser.add_argument("--similarity", type=float, default=0.8)
    parser.add_argument("--min-chars", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.quota = parse_quota(args.quota)

    records, report = build(args)
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=False)
    dataset = args.output_dir / "layers.jsonl"
    dataset.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8"
    )
    report["dataset_sha256"] = file_sha256(dataset)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
