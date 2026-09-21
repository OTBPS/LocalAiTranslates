"""Evaluate local GGUF translation models on the immutable held-out set."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from scripts.training.training_paths import MODEL_ROOT, workspace_path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.core import CancellationToken, OcrLine, TextBlock
from screen_translator.models import TRANSLATION_MODELS
from screen_translator.translation_engine import TranslationEngine

TOKEN_PATTERN = re.compile(
    r"https?://[^\s\]\[(){}<>\"'，。；！？]+|"
    r"(?<![A-Za-z0-9_])(?:[A-Za-z_][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*|"
    r"[A-Z][A-Z0-9_]{1,}|\d[\d,.:/%-]*)(?![A-Za-z0-9_])"
)
SENTENCE_PATTERN = re.compile(r"[^\n。！？!?;；]+[。！？!?;；]?")


def char_ngrams(text: str, order: int) -> Counter[str]:
    normalized = "".join(text.lower().split())
    return Counter(normalized[index : index + order] for index in range(max(0, len(normalized) - order + 1)))


def chrf_score(candidate: str, reference: str, max_order: int = 6, beta: float = 2.0) -> float:
    precisions, recalls = [], []
    for order in range(1, max_order + 1):
        cand = char_ngrams(candidate, order)
        ref = char_ngrams(reference, order)
        overlap = sum((cand & ref).values())
        precisions.append(overlap / max(1, sum(cand.values())))
        recalls.append(overlap / max(1, sum(ref.values())))
    precision = sum(precisions) / max_order
    recall = sum(recalls) / max_order
    if not precision and not recall:
        return 0.0
    beta2 = beta * beta
    return (1 + beta2) * precision * recall / (beta2 * precision + recall)


def protected_tokens(text: str) -> Counter[str]:
    return Counter(token.rstrip(".") for token in TOKEN_PATTERN.findall(text))


def token_preservation(source: str, candidate: str, reference: str | None = None) -> float:
    expected = protected_tokens(source)
    if reference is not None:
        # Only require source tokens that the human reference also keeps verbatim.
        # Names that are legitimately transliterated must not look like corruption.
        expected &= protected_tokens(reference)
    if not expected:
        return 1.0
    actual = protected_tokens(candidate)
    return sum((expected & actual).values()) / sum(expected.values())


def unexpected_repetitions(candidate: str, reference: str) -> int:
    candidate_units = Counter(
        unit.strip() for unit in SENTENCE_PATTERN.findall(candidate) if len(unit.strip()) >= 2
    )
    reference_units = Counter(
        unit.strip() for unit in SENTENCE_PATTERN.findall(reference) if len(unit.strip()) >= 2
    )
    reference_repeat_allowance = max(reference_units.values(), default=1)
    return sum(
        max(0, count - max(1, reference_units[unit], reference_repeat_allowance))
        for unit, count in candidate_units.items()
    )


def make_block(record: dict) -> TextBlock:
    line = OcrLine([(0, 0), (100, 0), (100, 20), (0, 20)], record["source_text"], 1.0, record["source_language"])
    return TextBlock(record["id"], [line])


def batches(records: list[dict], max_blocks: int = 10, max_chars: int = 2200):
    batch, size = [], 0
    for record in records:
        length = len(record["source_text"])
        if batch and (len(batch) >= max_blocks or size + length > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(record)
        size += length
    if batch:
        yield batch


def translate_batch(engine, records, token):
    blocks = [make_block(record) for record in records]
    language = records[0]["source_language"]
    attempts = 1
    first_pass = True
    try:
        values = engine.request(blocks, token, language, "zh-Hans")
    except ValueError:
        first_pass = False
        attempts += 1
        try:
            values = engine.request(blocks, token, language, "zh-Hans", True)
        except ValueError:
            values = {}
            for block in blocks:
                attempts += 1
                values.update(engine.request([block], token, language, "zh-Hans", True))
    return values, first_pass, attempts


def semantic_alignment_flags(predictions: list[dict], batch_stats: list[dict]) -> dict[str, bool]:
    flags = {}
    offset = 0
    for stats in batch_stats:
        batch = predictions[offset : offset + stats["records"]]
        offset += stats["records"]
        for row in batch:
            own_score = chrf_score(row["translation"], row["reference_text"])
            alternatives = [
                (other["id"], chrf_score(row["translation"], other["reference_text"]))
                for other in batch
                if other["id"] != row["id"]
            ]
            best_other_id, best_other_score = max(alternatives, key=lambda item: item[1], default=(None, 0.0))
            flags[row["id"]] = not (
                best_other_id is not None
                and best_other_score >= 0.35
                and best_other_score - own_score >= 0.12
            )
    if offset != len(predictions):
        raise ValueError("batch statistics do not cover every prediction")
    return flags


def summarize(predictions: list[dict], batch_stats: list[dict]) -> dict:
    count = len(predictions)
    by_language = defaultdict(list)
    by_domain = defaultdict(list)
    for row in predictions:
        by_language[row["source_language"]].append(row)
        by_domain[row["domain"]].append(row)
    alignment = semantic_alignment_flags(predictions, batch_stats)

    def aggregate(rows):
        return {
            "count": len(rows),
            "mean_chrf": round(sum(row["chrf"] for row in rows) / len(rows), 4),
            "reference_similarity_pass_rate": round(sum(row["chrf"] >= 0.35 for row in rows) / len(rows), 4),
            "token_preservation_rate": round(sum(row["token_preservation"] for row in rows) / len(rows), 4),
            "unexpected_repetitions": sum(row["unexpected_repetitions"] for row in rows),
        }

    candidate_groups = defaultdict(list)
    for row in predictions:
        candidate_groups[(row["source_language"], "".join(row["translation"].split()))].append(row)
    cross_record_duplicates = 0
    for (_, output), rows in candidate_groups.items():
        references = {"".join(row["reference_text"].split()) for row in rows}
        if len(output) >= 8 and len(rows) > 1 and len(references) > 1:
            cross_record_duplicates += len(rows) - 1
    summary = aggregate(predictions)
    summary.update(
        {
            "json_first_pass_rate": round(sum(row["first_pass"] for row in batch_stats) / len(batch_stats), 4),
            "json_final_success_rate": round(sum(row["final_success"] for row in batch_stats) / len(batch_stats), 4),
            "id_coverage_rate": round(sum(bool(row["translation"]) for row in predictions) / count, 4),
            "semantic_block_alignment_rate": round(sum(alignment.values()) / count, 4),
            "suspected_misaligned_ids": sorted(record_id for record_id, ok in alignment.items() if not ok),
            "cross_record_duplicate_outputs": cross_record_duplicates,
            "translation_seconds": round(sum(row["seconds"] for row in batch_stats), 3),
            "records_per_second": round(count / max(0.001, sum(row["seconds"] for row in batch_stats)), 3),
            "by_language": {key: aggregate(value) for key, value in sorted(by_language.items())},
            "by_domain": {key: aggregate(value) for key, value in sorted(by_domain.items())},
            "similarity_gate_is_provisional": True,
        }
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=workspace_path("data/eval/v1/eval.jsonl"))
    parser.add_argument("--models-dir", type=Path, default=MODEL_ROOT)
    parser.add_argument("--model", choices=tuple(TRANSLATION_MODELS), required=True)
    parser.add_argument("--output-dir", type=Path, default=workspace_path("runs/baseline"))
    parser.add_argument("--language", choices=("en", "ja", "ko"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    records = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines()]
    if args.language:
        records = [record for record in records if record["source_language"] == args.language]
    if args.limit:
        records = records[: args.limit]
    grouped = []
    for language in ("en", "ja", "ko"):
        grouped.extend(record for record in records if record["source_language"] == language)

    token = CancellationToken()
    engine = TranslationEngine(args.models_dir, model_id=args.model)
    predictions, batch_stats = [], []
    try:
        engine.start(token, lambda message: print(message, flush=True))
        all_batches = list(batches(grouped))
        for batch_index, batch in enumerate(all_batches, 1):
            started = time.monotonic()
            values, first_pass, attempts = translate_batch(engine, batch, token)
            elapsed = time.monotonic() - started
            final_success = set(values) == {record["id"] for record in batch}
            batch_stats.append(
                {
                    "batch": batch_index,
                    "records": len(batch),
                    "first_pass": first_pass,
                    "final_success": final_success,
                    "attempts": attempts,
                    "seconds": elapsed,
                }
            )
            for record in batch:
                translation = values.get(record["id"], "")
                predictions.append(
                    {
                        **record,
                        "translation": translation,
                        "chrf": round(chrf_score(translation, record["reference_text"]), 6),
                        "token_preservation": round(
                            token_preservation(
                                record["source_text"], translation, record["reference_text"]
                            ),
                            6,
                        ),
                        "unexpected_repetitions": unexpected_repetitions(translation, record["reference_text"]),
                    }
                )
            print(f"[{batch_index}/{len(all_batches)}] {len(batch)} records in {elapsed:.2f}s", flush=True)
    finally:
        engine.stop()

    output = args.output_dir / args.model
    output.mkdir(parents=True, exist_ok=True)
    (output / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions), encoding="utf-8"
    )
    summary = summarize(predictions, batch_stats)
    summary.update({"model": args.model, "dataset": str(args.dataset), "records": len(predictions)})
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "batches.json").write_text(json.dumps(batch_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
