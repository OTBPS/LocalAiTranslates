"""Build a direction-specific held-out or development set for en<->zh work.

The existing `build_eval_set.py` only produces X->zh records from a fixed
1,997-line NTREX slice. This builder adds the missing pieces for the Chinese
pair: an explicit translation direction, automatic exclusion of every line any
existing dataset already consumed, and a dataset-level license field.

Source corpora are the ones already cached under the training workspace; this
script never downloads anything.

    python -m scripts.training.build_direction_set --direction zh-en --split eval \\
        --records 300 --output-dir D:\\AI\\Training\\screen-translator\\data\\eval\\zh-en-v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

from scripts.training.training_paths import workspace_path

NTREX_DATASET = "MicrosoftTranslator/NTREX-128"
TATOEBA_DATASET = "OPUS/Tatoeba v2026-07-08"
FIXTURE_DATASET = "ScreenTranslator adversarial evaluation cases"
LICENSES = {
    NTREX_DATASET: "CC-BY-SA-4.0",
    TATOEBA_DATASET: "CC-BY-2.0-FR",
    FIXTURE_DATASET: "project-test-data",
}
DIRECTIONS = {"en-zh": ("en", "zh-Hans"), "zh-en": ("zh-Hans", "en")}
# The 30 application fixtures are fully consumed by the frozen eval-v1 set (its
# English side is the source and its Chinese side the reference), so neither
# direction can reuse them without overlapping a held-out set. Curated corpora
# therefore only cover news and long documents; application domains need new
# authored cases before they can be added here.
DEFAULT_MIX = "news_web=55,long_document=20,parallel_corpus=25"


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_lines(path: Path) -> list[str]:
    return [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines()]


def read_tatoeba(archive: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(archive) as bundle:
        english = next(name for name in bundle.namelist() if name.endswith(".en"))
        chinese = next(name for name in bundle.namelist() if name.endswith(".cmn"))
        with bundle.open(english) as stream:
            en_lines = stream.read().decode("utf-8").splitlines()
        with bundle.open(chinese) as stream:
            zh_lines = stream.read().decode("utf-8").splitlines()
    return list(zip(en_lines, zh_lines, strict=True))


def consumed(paths: list[Path]) -> tuple[set[int], set[str]]:
    """Return NTREX line indexes and normalized texts every existing dataset used."""
    ntrex_indexes: set[int] = set()
    texts: set[str] = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            provenance = row.get("provenance", {})
            if provenance.get("dataset") == NTREX_DATASET:
                for key in ("line_indexes", "line_index"):
                    value = provenance.get(key)
                    if isinstance(value, int):
                        ntrex_indexes.add(value)
                    elif isinstance(value, list):
                        ntrex_indexes.update(item for item in value if isinstance(item, int))
            for key in ("source_text", "reference_text"):
                value = row.get(key)
                if isinstance(value, str):
                    for piece in value.split("\n"):
                        if len(normalize(piece)) >= 12:
                            texts.add(normalize(piece))
    return ntrex_indexes, texts


def discover_existing(root: Path) -> list[Path]:
    paths = []
    for pattern in ("data/eval/*/*.jsonl", "data/dev/*/*.jsonl", "data/train/*/teacher_blocks.jsonl"):
        paths.extend(sorted(root.glob(pattern)))
    return paths


def parse_mix(text: str) -> dict[str, int]:
    mix = {}
    for item in text.split(","):
        name, _, count = item.partition("=")
        mix[name.strip()] = int(count)
    return mix


def build(args) -> tuple[list[dict], dict]:
    source_language, target_language = DIRECTIONS[args.direction]
    existing = discover_existing(args.workspace) if args.auto_exclude else []
    existing += [Path(p) for p in args.exclude]
    used_indexes, used_texts = consumed(existing)

    ntrex = {
        "en": read_lines(args.ntrex_dir / "newstest2019-src.eng.txt"),
        "zh-Hans": read_lines(args.ntrex_dir / "newstest2019-ref.zho-CN.txt"),
        "documents": read_lines(args.ntrex_dir / "DOCUMENT_IDS.tsv"),
    }
    if len({len(ntrex["en"]), len(ntrex["zh-Hans"])}) != 1:
        raise ValueError("NTREX English and Chinese files are not aligned")

    free = [
        index
        for index in range(len(ntrex["en"]))
        if index not in used_indexes
        and ntrex["en"][index].strip()
        and ntrex["zh-Hans"][index].strip()
    ]
    rng = random.Random(args.seed)

    documents: dict[str, list[int]] = defaultdict(list)
    for index in free:
        documents[ntrex["documents"][index]].append(index)

    mix = parse_mix(args.domain_mix)
    scale = args.records / sum(mix.values())
    wanted = {domain: max(0, round(count * scale)) for domain, count in mix.items()}

    records: list[dict] = []
    shortfalls: dict[str, int] = {}

    # long_document: same-document NTREX runs keep discourse coherent, but they
    # burn several reserve lines each, so taking them is opt-in.
    groups = sorted((idx for idx in documents.values() if len(idx) >= 3), key=len, reverse=True)
    rng.shuffle(groups)
    long_budget = wanted.get("long_document", 0) if args.long_from_ntrex else 0
    long_groups = [group[:5] for group in groups[:long_budget]]
    long_used = {index for group in long_groups for index in group}
    for ordinal, indexes in enumerate(long_groups):
        records.append(
            _ntrex_record(args, ordinal, "long", "long_document", indexes, ntrex,
                          source_language, target_language)
        )
    if len(long_groups) < wanted.get("long_document", 0):
        shortfalls["long_document"] = wanted["long_document"] - len(long_groups)

    # news_web: single NTREX lines that no dataset has touched.
    singles = [index for index in free if index not in long_used]
    rng.shuffle(singles)
    take = singles[: wanted.get("news_web", 0)]
    for ordinal, index in enumerate(take):
        records.append(
            _ntrex_record(args, ordinal, "news", "news_web", [index], ntrex,
                          source_language, target_language)
        )
    if len(take) < wanted.get("news_web", 0):
        shortfalls["news_web"] = wanted["news_web"] - len(take)

    # Application domains would have to come from the fixture, which eval-v1 has
    # already consumed on both sides. Requesting them is therefore an explicit
    # opt-in that knowingly overlaps a frozen set.
    if args.allow_fixture_reuse:
        cases = json.loads(args.fixture.read_text(encoding="utf-8"))
        by_domain: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for ordinal, case in enumerate(cases):
            family = "adversarial" if case["domain"].startswith("adversarial") else case["domain"]
            by_domain[family].append((ordinal, case))
        for family in ("software_ui", "game_subtitle", "adversarial"):
            pool = by_domain.get(family, [])
            rng.shuffle(pool)
            chosen = pool[: wanted.get(family, 0)]
            for ordinal, case in chosen:
                records.append(
                    {
                        "id": f"{args.split}-{args.direction}-{case['domain']}-{ordinal:03d}",
                        "source_language": source_language,
                        "target_language": target_language,
                        "domain": case["domain"],
                        "source_text": case[source_language],
                        "reference_text": case[target_language],
                        "held_out": True,
                        "training_use_prohibited": True,
                        "provenance": {
                            "dataset": FIXTURE_DATASET,
                            "case_index": ordinal,
                            "license": LICENSES[FIXTURE_DATASET],
                            "overlaps_frozen_eval_v1": True,
                        },
                    }
                )
            if len(chosen) < wanted.get(family, 0):
                shortfalls[family] = wanted[family] - len(chosen)
    else:
        for family in ("software_ui", "game_subtitle", "adversarial"):
            if wanted.get(family):
                shortfalls[family] = wanted[family]

    # Tatoeba can fill the remainder, but short crowd-sourced sentences are a poor
    # substitute for the missing domains, so filling is opt-in.
    remaining = args.records - len(records)
    if remaining > 0 and not args.corpus_fill:
        shortfalls["parallel_corpus_fill_declined"] = remaining
        remaining = 0
    if remaining > 0:
        pairs = read_tatoeba(args.tatoeba_dir / "cmn-en.txt.zip")
        candidates = [
            (index, en, zh)
            for index, (en, zh) in enumerate(pairs)
            if en.strip()
            and zh.strip()
            and normalize(en) not in used_texts
            and normalize(zh) not in used_texts
        ]
        rng.shuffle(candidates)
        for ordinal, (index, en, zh) in enumerate(candidates[:remaining]):
            source_text, reference_text = (en, zh) if source_language == "en" else (zh, en)
            records.append(
                {
                    "id": f"{args.split}-{args.direction}-corpus-{ordinal:03d}",
                    "source_language": source_language,
                    "target_language": target_language,
                    "domain": "parallel_corpus",
                    "source_text": source_text,
                    "reference_text": reference_text,
                    "held_out": True,
                    "training_use_prohibited": True,
                    "provenance": {
                        "dataset": TATOEBA_DATASET,
                        "line_index": index,
                        "license": LICENSES[TATOEBA_DATASET],
                    },
                }
            )
        if len(candidates) < remaining:
            shortfalls["parallel_corpus"] = remaining - len(candidates)

    verify(records, used_texts)
    manifest = {
        "schema_version": 1,
        "dataset_name": f"screen-translator-{args.split}-{args.direction}",
        "direction": args.direction,
        "source_language": source_language,
        "target_language": target_language,
        "records": len(records),
        "seed": args.seed,
        "held_out": True,
        "training_use_prohibited": True,
        "licenses": sorted({record["provenance"]["license"] for record in records}),
        "domains": _counts(records, "domain"),
        "datasets": _counts(records, lambda r: r["provenance"]["dataset"]),
        "requested_records": args.records,
        "domain_mix": args.domain_mix,
        "shortfalls": shortfalls,
        # A set that could not be filled as designed is not a release-grade ruler.
        "provisional": bool(shortfalls),
        "provisional_reason": (
            "missing domains have no licensed human-referenced source material"
            if shortfalls
            else None
        ),
        "ntrex_lines_consumed": sorted(
            index
            for record in records
            if record["provenance"]["dataset"] == NTREX_DATASET
            for index in record["provenance"]["line_indexes"]
        ),
        "excluded_sources": [str(path) for path in existing],
    }
    return records, manifest


def _ntrex_record(args, ordinal, kind, domain, indexes, ntrex, source_language, target_language):
    return {
        "id": f"{args.split}-{args.direction}-{kind}-{ordinal:03d}",
        "source_language": source_language,
        "target_language": target_language,
        "domain": domain,
        "source_text": "\n".join(ntrex[source_language][index] for index in indexes),
        "reference_text": "\n".join(ntrex[target_language][index] for index in indexes),
        "held_out": True,
        "training_use_prohibited": True,
        "provenance": {
            "dataset": NTREX_DATASET,
            "line_indexes": list(indexes),
            "license": LICENSES[NTREX_DATASET],
        },
    }


def _counts(records, key):
    counter: dict[str, int] = defaultdict(int)
    for record in records:
        counter[key(record) if callable(key) else record[key]] += 1
    return dict(sorted(counter.items()))


def verify(records: list[dict], used_texts: set[str]) -> None:
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate record ids")
    seen: set[str] = set()
    for record in records:
        known_overlap = record["provenance"].get("overlaps_frozen_eval_v1", False)
        for piece in record["source_text"].split("\n"):
            key = normalize(piece)
            if len(key) < 12:
                continue
            if key in used_texts and not known_overlap:
                raise ValueError(f"record {record['id']} overlaps an existing dataset")
            if key in seen:
                raise ValueError(f"record {record['id']} duplicates another record in this set")
            seen.add(key)
        if not record["source_text"].strip() or not record["reference_text"].strip():
            raise ValueError(f"record {record['id']} has an empty side")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--direction", choices=tuple(DIRECTIONS), required=True)
    parser.add_argument("--split", choices=("eval", "dev"), required=True)
    parser.add_argument("--records", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--domain-mix", default=DEFAULT_MIX)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--workspace", type=Path, default=workspace_path(""))
    parser.add_argument("--ntrex-dir", type=Path, default=workspace_path("cache/ntrex"))
    parser.add_argument("--tatoeba-dir", type=Path, default=workspace_path("cache/tatoeba"))
    parser.add_argument("--fixture", type=Path, default=workspace_path("fixtures/screen_translation_eval.json"))
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--auto-exclude", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--allow-fixture-reuse",
        action="store_true",
        help="Reuse the application fixtures even though eval-v1 already consumed both sides.",
    )
    parser.add_argument(
        "--corpus-fill",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Pad the remainder with Tatoeba sentences instead of reporting a shortfall.",
    )
    parser.add_argument(
        "--long-from-ntrex",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build long_document from NTREX runs; disable to preserve the reserve lines.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.records < 1:
        parser.error("--records must be at least 1")

    records, manifest = build(args)
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=False)
    dataset_path = args.output_dir / f"{args.split}.jsonl"
    dataset_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest["dataset_sha256"] = file_sha256(dataset_path)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
