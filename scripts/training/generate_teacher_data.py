"""Generate and filter small-stage SFT data with the local Qwen3-14B teacher."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from scripts.training.training_paths import MODEL_ROOT, workspace_path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.core import CancellationToken, OcrLine, TextBlock
from screen_translator.translation_engine import TranslationEngine, build_translation_system_prompt
from scripts.training.evaluate_models import chrf_score, token_preservation, unexpected_repetitions

NTREX_FILES = {
    "en": "newstest2019-src.eng.txt",
    "ja": "newstest2019-ref.jpn.txt",
    "ko": "newstest2019-ref.kor.txt",
    "zh-Hans": "newstest2019-ref.zho-CN.txt",
}
TATOEBA_FILES = {
    "en": ("cmn-en/Tatoeba.cmn-en.en", "cmn-en/Tatoeba.cmn-en.cmn"),
    "ja": ("cmn-ja/Tatoeba.cmn-ja.ja", "cmn-ja/Tatoeba.cmn-ja.cmn"),
    "ko": ("cmn-ko/Tatoeba.cmn-ko.ko", "cmn-ko/Tatoeba.cmn-ko.cmn"),
}
LANGUAGES = ("en", "ja", "ko")


def normalized_source(text: str) -> str:
    return " ".join(text.split()).casefold()


def exclude_existing_sources(records: list[dict], paths: list[Path]) -> list[dict]:
    excluded = {
        normalized_source(json.loads(line)["source_text"])
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return [row for row in records if normalized_source(row["source_text"]) not in excluded]


def read_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]


def held_out_indexes(eval_path: Path) -> set[int]:
    held_out = set()
    for line in eval_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        provenance = record.get("provenance", {})
        if provenance.get("dataset") == "MicrosoftTranslator/NTREX-128":
            held_out.update(provenance["line_indexes"])
    return held_out


def build_candidates(
    ntrex_dir: Path,
    eval_path: Path,
    limit: int,
    seed: int,
    tatoeba_dir: Path | None = None,
    ntrex_fraction: float = 0.6,
    kozh_csv: Path | None = None,
) -> list[dict]:
    aligned = {code: read_lines(ntrex_dir / filename) for code, filename in NTREX_FILES.items()}
    if {len(lines) for lines in aligned.values()} != {1997}:
        raise ValueError("NTREX cache is missing or no longer line aligned")
    excluded = held_out_indexes(eval_path)
    rng = random.Random(seed)
    per_language = limit // len(LANGUAGES)
    remainder = limit % len(LANGUAGES)
    records = []
    for language_index, language in enumerate(LANGUAGES):
        ntrex_indexes = [
            index
            for index in range(1997)
            if index not in excluded and aligned[language][index] and aligned["zh-Hans"][index]
        ]
        rng.shuffle(ntrex_indexes)
        take = per_language + (language_index < remainder)
        ntrex_take = min(len(ntrex_indexes), round(take * ntrex_fraction))
        tatoeba_rows = []
        if tatoeba_dir:
            source_name, target_name = TATOEBA_FILES[language]
            sources = read_lines(tatoeba_dir / source_name)
            targets = read_lines(tatoeba_dir / target_name)
            if len(sources) != len(targets):
                raise ValueError(f"Tatoeba {language} cache is no longer line aligned")
            tatoeba_rows = [
                (index, source, target)
                for index, (source, target) in enumerate(zip(sources, targets, strict=True))
                if source and target
            ]
            rng.shuffle(tatoeba_rows)
        kozh_rows = []
        if language == "ko" and kozh_csv:
            with kozh_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                for index, row in enumerate(csv.DictReader(stream)):
                    source, target = row.get("ko", "").strip(), row.get("zh", "").strip()
                    if source and target and len(source) <= 600 and len(target) <= 600:
                        kozh_rows.append((index, source, target, row.get("source", "unknown")))
            rng.shuffle(kozh_rows)
        tatoeba_take = min(len(tatoeba_rows), take - ntrex_take)
        ntrex_take = min(len(ntrex_indexes), take - tatoeba_take)
        if ntrex_take + tatoeba_take < take:
            extra_tatoeba = min(len(tatoeba_rows) - tatoeba_take, take - ntrex_take - tatoeba_take)
            tatoeba_take += extra_tatoeba
        kozh_take = min(len(kozh_rows), take - ntrex_take - tatoeba_take)

        language_records = []
        for index in ntrex_indexes[:ntrex_take]:
            language_records.append(
                {
                    "id": f"train-ntrex-{language}-{index:04d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "source_text": aligned[language][index],
                    "human_reference": aligned["zh-Hans"][index],
                    "provenance": {
                        "dataset": "MicrosoftTranslator/NTREX-128",
                        "line_index": index,
                        "license": "CC-BY-SA-4.0",
                    },
                }
            )
        for index, source, target in tatoeba_rows[:tatoeba_take]:
            language_records.append(
                {
                    "id": f"train-tatoeba-{language}-{index:05d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "source_text": source,
                    "human_reference": target,
                    "provenance": {
                        "dataset": "OPUS/Tatoeba v2026-07-08",
                        "line_index": index,
                        "license": "CC-BY-2.0-FR",
                    },
                }
            )
        for index, source, target, subset in kozh_rows[:kozh_take]:
            language_records.append(
                {
                    "id": f"train-aihub-kozh-{index:06d}",
                    "source_language": language,
                    "target_language": "zh-Hans",
                    "source_text": source,
                    "human_reference": target,
                    "provenance": {
                        "dataset": "AIHub Ko-Zh integrated small-100k",
                        "line_index": index,
                        "subset": subset,
                        "license": "MIT repository metadata; underlying AI Hub terms apply",
                    },
                }
            )
        # Exact duplicate sentences add memorization pressure without new information.
        unique = {}
        for record in language_records:
            unique.setdefault(record["source_text"], record)
        language_records = list(unique.values())
        rng.shuffle(language_records)
        records.extend(language_records)
    return records


def make_block(record: dict) -> TextBlock:
    line = OcrLine([(0, 0), (100, 0), (100, 20), (0, 20)], record["source_text"], 1.0)
    return TextBlock(record["id"], [line])


def make_batches(records: list[dict], max_blocks=12, max_chars=2400):
    for language in LANGUAGES:
        batch, length = [], 0
        for record in (item for item in records if item["source_language"] == language):
            size = len(record["source_text"])
            if batch and (len(batch) >= max_blocks or length + size > max_chars):
                yield batch
                batch, length = [], 0
            batch.append(record)
            length += size
        if batch:
            yield batch


def target_script_ok(text: str) -> bool:
    if not text.strip():
        return False
    kana = sum("\u3040" <= char <= "\u30ff" for char in text)
    hangul = sum("\uac00" <= char <= "\ud7af" for char in text)
    han = sum("\u4e00" <= char <= "\u9fff" for char in text)
    return han > 0 and kana + hangul <= max(2, len(text) // 50)


def rejection_reasons(record: dict, translation: str) -> list[str]:
    reference = record["human_reference"]
    reasons = []
    if not target_script_ok(translation):
        reasons.append("output_language")
    if chrf_score(translation, reference) < 0.16:
        reasons.append("low_reference_similarity")
    if token_preservation(record["source_text"], translation, reference) < 1:
        reasons.append("protected_token_changed")
    if unexpected_repetitions(translation, reference):
        reasons.append("unexpected_repetition")
    ratio = len(translation) / max(1, len(reference))
    if ratio < 0.35:
        reasons.append("possible_omission")
    if ratio > 2.2:
        reasons.append("possible_expansion")
    return reasons


def load_batch_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_outputs(output_dir: Path, states: list[dict], metadata: dict) -> dict:
    states = sorted(states, key=lambda state: state["stats"]["batch"])
    accepted = [row for state in states for row in state["accepted"]]
    rejected = [row for state in states for row in state["rejected"]]
    conversations = [state["conversation"] for state in states if state["conversation"]]
    batch_stats = [state["stats"] for state in states]
    for name, rows in (
        ("teacher_blocks.jsonl", accepted),
        ("rejected.jsonl", rejected),
        ("sft_messages.jsonl", conversations),
    ):
        (output_dir / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    manifest = {
        "schema_version": 2,
        **metadata,
        "accepted_blocks": len(accepted),
        "rejected_blocks": len(rejected),
        "conversations": len(conversations),
        "acceptance_rate": round(len(accepted) / max(1, len(accepted) + len(rejected)), 4),
        "languages": dict(Counter(row["source_language"] for row in accepted)),
        "datasets": dict(Counter(row["provenance"]["dataset"] for row in accepted)),
        "rejection_reasons": dict(
            Counter(reason for row in rejected for reason in row["rejection_reasons"])
        ),
        "eval_source_overlap": 0,
        "batches": batch_stats,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def process_batch(engine, token, batch: list[dict], batch_number: int) -> dict:
    batch_ids = [record["id"] for record in batch]
    blocks = [make_block(record) for record in batch]
    language = batch[0]["source_language"]
    started = time.monotonic()
    try:
        values = engine.request(blocks, token, language, "zh-Hans")
        json_valid = True
    except (ValueError, KeyError):
        values, json_valid = {}, False
    accepted, rejected, kept = [], [], []
    for record in batch:
        translation = values.get(record["id"], "")
        reasons = [] if json_valid else ["invalid_json"]
        reasons.extend(rejection_reasons(record, translation))
        scored = {
            **record,
            "teacher_model": "qwen3-14b-q5-k-m",
            "teacher_translation": translation,
            "chrf": round(chrf_score(translation, record["human_reference"]), 6),
            "token_preservation": round(
                token_preservation(record["source_text"], translation, record["human_reference"]), 6
            ),
            "rejection_reasons": sorted(set(reasons)),
        }
        if reasons:
            rejected.append(scored)
        else:
            accepted.append(scored)
            kept.append(scored)
    conversation = None
    if kept:
        source_payload = {row["id"]: row["source_text"] for row in kept}
        target_payload = {row["id"]: row["teacher_translation"] for row in kept}
        conversation = {
            "messages": [
                {"role": "system", "content": build_translation_system_prompt(language, "zh-Hans")},
                {"role": "user", "content": json.dumps(source_payload, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(target_payload, ensure_ascii=False)},
            ],
            "metadata": {"source_language": language, "block_ids": list(source_payload)},
        }
    return {
        "input_ids": batch_ids,
        "accepted": accepted,
        "rejected": rejected,
        "conversation": conversation,
        "stats": {
            "batch": batch_number,
            "input": len(batch),
            "accepted": len(kept),
            "json_valid": json_valid,
            "seconds": round(time.monotonic() - started, 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ntrex-dir", type=Path, default=workspace_path("cache/ntrex"))
    parser.add_argument("--tatoeba-dir", type=Path, default=workspace_path("cache/tatoeba"))
    parser.add_argument(
        "--kozh-csv",
        type=Path,
        default=workspace_path("cache/aihub-kozh-100k/train.csv"),
    )
    parser.add_argument("--eval", type=Path, default=workspace_path("data/eval/v1/eval.jsonl"))
    parser.add_argument(
        "--exclude-data",
        type=Path,
        action="append",
        default=[],
        help="JSONL file whose source_text values must not be generated; may be repeated",
    )
    parser.add_argument("--models-dir", type=Path, default=MODEL_ROOT)
    parser.add_argument("--output-dir", type=Path, default=workspace_path("data/train/pilot-v1"))
    parser.add_argument("--limit", type=int, default=600)
    parser.add_argument("--ntrex-fraction", type=float, default=0.6)
    parser.add_argument("--max-blocks", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=2400)
    parser.add_argument("--parallel", type=int, choices=(1, 2), default=2)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()

    if not 0 <= args.ntrex_fraction <= 1:
        raise ValueError("--ntrex-fraction must be between 0 and 1")
    records = build_candidates(
        args.ntrex_dir,
        args.eval,
        args.limit,
        args.seed,
        args.tatoeba_dir,
        args.ntrex_fraction,
        args.kozh_csv,
    )
    records = exclude_existing_sources(records, args.exclude_data)
    candidate_fingerprints = {hashlib.sha256(row["source_text"].encode()).hexdigest() for row in records}
    eval_fingerprints = {
        hashlib.sha256(json.loads(line)["source_text"].encode()).hexdigest()
        for line in args.eval.read_text(encoding="utf-8").splitlines()
    }
    if candidate_fingerprints & eval_fingerprints:
        raise RuntimeError("training/evaluation source leakage detected")

    token = CancellationToken()
    engine = TranslationEngine(
        args.models_dir,
        model_id="qwen3-14b-q5-k-m",
        parallel_slots=args.parallel,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "batch_state.jsonl"
    states = load_batch_state(state_path)
    completed_ids = {record_id for state in states for record_id in state["input_ids"]}
    expected_ids = {record["id"] for record in records}
    if completed_ids - expected_ids:
        raise RuntimeError("resume state does not match the requested candidate set")
    try:
        engine.start(token, lambda message: print(message, flush=True))
        all_batches = list(make_batches(records, args.max_blocks, args.max_chars))
        pending = []
        for batch_number, batch in enumerate(all_batches, 1):
            batch_ids = [record["id"] for record in batch]
            done = [record_id in completed_ids for record_id in batch_ids]
            if all(done):
                print(f"[{batch_number}/{len(all_batches)}] already complete", flush=True)
                continue
            if any(done):
                raise RuntimeError("resume state contains a partial batch")
            pending.append((batch_number, batch))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(process_batch, engine, token, batch, batch_number): batch_number
                for batch_number, batch in pending
            }
            for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
                state = future.result()
                with state_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(state, ensure_ascii=False) + "\n")
                    stream.flush()
                states.append(state)
                completed_ids.update(state["input_ids"])
                stats = state["stats"]
                print(
                    f"[{completed}/{len(pending)} pending; batch {stats['batch']}/{len(all_batches)}] "
                    f"accepted {stats['accepted']}/{stats['input']}",
                    flush=True,
                )
    finally:
        engine.stop()

    manifest = write_outputs(
        args.output_dir,
        states,
        {
        "teacher_model": "qwen3-14b-q5-k-m",
        "seed": args.seed,
        "candidates": len(records),
        "ntrex_fraction": args.ntrex_fraction,
        "max_blocks": args.max_blocks,
        "max_chars": args.max_chars,
        "parallel": args.parallel,
        "resumable": True,
        },
    )
    print(json.dumps({key: value for key, value in manifest.items() if key != "batches"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
