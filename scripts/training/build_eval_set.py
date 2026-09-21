"""Build the immutable held-out translation evaluation set."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from scripts.training.training_paths import workspace_path

NTREX_BASE = "https://raw.githubusercontent.com/MicrosoftTranslator/NTREX/main"
NTREX_FILES = {
    "en": "NTREX-128/newstest2019-src.eng.txt",
    "ja": "NTREX-128/newstest2019-ref.jpn.txt",
    "ko": "NTREX-128/newstest2019-ref.kor.txt",
    "zh-Hans": "NTREX-128/newstest2019-ref.zho-CN.txt",
    "documents": "DOCUMENT_IDS.tsv",
}
LANGUAGES = ("en", "ja", "ko")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, destination: Path) -> dict[str, str | int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=90) as response:  # noqa: S310
        data = response.read()
    destination.write_bytes(data)
    return {"url": url, "sha256": sha256(data), "bytes": len(data)}


def read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]


def choose_ntrex_records(raw_dir: Path, seed: int) -> list[dict]:
    sources = {code: read_lines(raw_dir / Path(rel).name) for code, rel in NTREX_FILES.items()}
    lengths = {len(lines) for lines in sources.values()}
    if lengths != {1997}:
        raise ValueError(f"NTREX files are not aligned: {sorted(lengths)}")

    documents: dict[str, list[int]] = defaultdict(list)
    for index, document_id in enumerate(sources["documents"]):
        documents[document_id].append(index)
    eligible_docs = [indices for indices in documents.values() if len(indices) >= 3]
    rng = random.Random(seed)
    rng.shuffle(eligible_docs)
    long_groups = [indices[:3] for indices in eligible_docs[:20]]
    long_indexes = {index for group in long_groups for index in group}

    singles = [
        index
        for index in range(1997)
        if index not in long_indexes
        and all(sources[code][index] for code in ("en", "ja", "ko", "zh-Hans"))
    ]
    rng.shuffle(singles)
    singles = singles[:50]

    records = []
    for language in LANGUAGES:
        for ordinal, index in enumerate(singles):
            records.append(
                {
                    "id": f"eval-{language}-news-{ordinal:03d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "domain": "news_web",
                    "source_text": sources[language][index],
                    "reference_text": sources["zh-Hans"][index],
                    "held_out": True,
                    "provenance": {"dataset": "MicrosoftTranslator/NTREX-128", "line_indexes": [index], "license": "CC-BY-SA-4.0"},
                }
            )
        for ordinal, indexes in enumerate(long_groups):
            records.append(
                {
                    "id": f"eval-{language}-long-{ordinal:03d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "domain": "long_document",
                    "source_text": "\n".join(sources[language][index] for index in indexes),
                    "reference_text": "\n".join(sources["zh-Hans"][index] for index in indexes),
                    "held_out": True,
                    "provenance": {"dataset": "MicrosoftTranslator/NTREX-128", "line_indexes": indexes, "license": "CC-BY-SA-4.0"},
                }
            )
    return records


def choose_application_records(fixture: Path) -> list[dict]:
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    if len(cases) != 30:
        raise ValueError(f"expected 30 application cases, found {len(cases)}")
    records = []
    for language in LANGUAGES:
        for ordinal, case in enumerate(cases):
            records.append(
                {
                    "id": f"eval-{language}-app-{ordinal:03d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "domain": case["domain"],
                    "source_text": case[language],
                    "reference_text": case["zh-Hans"],
                    "held_out": True,
                    "provenance": {"dataset": "ScreenTranslator adversarial evaluation cases", "case_index": ordinal, "license": "project-test-data"},
                }
            )
    return records


def validate(records: list[dict]) -> None:
    if len(records) != 300:
        raise ValueError(f"expected 300 records, found {len(records)}")
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("duplicate evaluation IDs")
    if not all(record["held_out"] for record in records):
        raise ValueError("all evaluation records must be held out")
    language_counts = Counter(record["source_language"] for record in records)
    if language_counts != {"en": 100, "ja": 100, "ko": 100}:
        raise ValueError(f"unexpected language distribution: {language_counts}")
    required_domains = {"news_web", "long_document", "software_ui", "game_subtitle", "adversarial_tokens", "adversarial_repeat", "adversarial_blocks"}
    missing = required_domains - {record["domain"] for record in records}
    if missing:
        raise ValueError(f"missing domains: {sorted(missing)}")
    for record in records:
        if not record["source_text"] or not record["reference_text"]:
            raise ValueError(f"empty text in {record['id']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=workspace_path("data/eval/v1"))
    parser.add_argument("--cache-dir", type=Path, default=workspace_path("cache/ntrex"))
    parser.add_argument("--fixture", type=Path, default=workspace_path("fixtures/screen_translation_eval.json"))
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()

    downloads = {}
    for key, relative in NTREX_FILES.items():
        destination = args.cache_dir / Path(relative).name
        downloads[key] = download(f"{NTREX_BASE}/{relative}", destination)

    records = choose_ntrex_records(args.cache_dir, args.seed)
    records.extend(choose_application_records(args.fixture))
    records.sort(key=lambda record: record["id"])
    validate(records)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.output_dir / "eval.jsonl"
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    dataset_path.write_text(payload, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "dataset_name": "screen-translator-held-out-eval-v1",
        "created_by": "scripts/training/build_eval_set.py",
        "seed": args.seed,
        "record_count": len(records),
        "languages": dict(sorted(Counter(r["source_language"] for r in records).items())),
        "domains": dict(sorted(Counter(r["domain"] for r in records).items())),
        "dataset_sha256": sha256(payload.encode("utf-8")),
        "held_out": True,
        "training_use_prohibited": True,
        "sources": downloads,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
