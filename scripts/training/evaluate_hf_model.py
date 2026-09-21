"""Evaluate the Qwen3-4B base model or a PEFT adapter on held-out data."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from scripts.training.training_paths import add_model_arguments, resolve_model_argument, workspace_path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from screen_translator.core import parse_translation
from screen_translator.translation_engine import build_translation_system_prompt
from scripts.training.evaluate_models import (
    batches,
    chrf_score,
    summarize,
    token_preservation,
    unexpected_repetitions,
)


class HfTranslationModel:
    def __init__(
        self,
        model_path: Path,
        adapter_path: Path | None = None,
        *,
        temperature: float = 0.0,
        top_p: float = 0.8,
        top_k: int = 20,
        generation_seed: int = 20260920,
    ):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the held-out QLoRA evaluation")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=quantization,
            dtype=torch.bfloat16,
            device_map={"": 0},
            attn_implementation="sdpa",
        )
        if adapter_path:
            self.model = PeftModel.from_pretrained(self.model, adapter_path)
        self.model.eval()
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        torch.manual_seed(generation_seed)
        torch.cuda.manual_seed_all(generation_seed)

    def request(self, records: list[dict], repair: bool = False) -> dict[str, str]:
        ids = [record["id"] for record in records]
        messages = [
            {
                "role": "system",
                "content": build_translation_system_prompt(
                    records[0]["source_language"], "zh-Hans", repair
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {record["id"]: record["source_text"] for record in records},
                    ensure_ascii=False,
                ),
            },
        ]
        encoded = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
            return_tensors="pt",
            return_dict=True,
        )
        encoded = {key: value.to(self.model.device) for key, value in encoded.items()}
        with self.torch.inference_mode():
            generation_args = {
                "do_sample": self.temperature > 0,
                "max_new_tokens": 1536,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "use_cache": True,
            }
            if self.temperature > 0:
                generation_args.update(
                    {
                        "temperature": self.temperature,
                        "top_p": self.top_p,
                        "top_k": self.top_k,
                    }
                )
            generated = self.model.generate(
                **encoded,
                **generation_args,
            )
        prompt_length = encoded["input_ids"].shape[1]
        raw = self.tokenizer.decode(generated[0, prompt_length:], skip_special_tokens=True).strip()
        try:
            return parse_translation(raw, ids)
        except (ValueError, json.JSONDecodeError) as exc:
            raise PredictionFormatError(str(exc)) from exc


class PredictionFormatError(ValueError):
    """The model completed generation but did not return the required JSON mapping."""


def translate_batch(model: HfTranslationModel, records: list[dict]):
    attempts = 1
    first_pass = True
    try:
        values = model.request(records)
    except PredictionFormatError:
        first_pass = False
        attempts += 1
        try:
            values = model.request(records, repair=True)
        except PredictionFormatError:
            values = {}
            for record in records:
                attempts += 1
                try:
                    values.update(model.request([record], repair=True))
                except PredictionFormatError:
                    continue
    return values, first_pass, attempts


def select_records(records: list[dict], per_language: int | None, seed: int) -> list[dict]:
    if per_language is None:
        return records
    selected = []
    rng = random.Random(seed)
    for language in ("en", "ja", "ko"):
        candidates = [record for record in records if record["source_language"] == language]
        rng.shuffle(candidates)
        selected.extend(candidates[:per_language])
    return selected


def main() -> int:
    import torch

    parser = argparse.ArgumentParser()
    add_model_arguments(parser)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--dataset", type=Path, default=workspace_path("data/eval/v1/eval.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-language", type=int)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--generation-seed", type=int, default=20260920)
    parser.add_argument("--max-blocks-per-request", type=int, default=10)
    parser.add_argument("--max-chars-per-request", type=int, default=2200)
    args = parser.parse_args()
    args.model = resolve_model_argument(args)

    if args.temperature < 0:
        parser.error("--temperature must be non-negative")
    if not 0 < args.top_p <= 1:
        parser.error("--top-p must be in (0, 1]")
    if args.top_k < 0:
        parser.error("--top-k must be non-negative")
    if args.max_blocks_per_request < 1:
        parser.error("--max-blocks-per-request must be positive")
    if args.max_chars_per_request < 1:
        parser.error("--max-chars-per-request must be positive")

    records = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines()]
    records = select_records(records, args.per_language, args.seed)
    records.sort(key=lambda record: (record["source_language"], record["id"]))

    model = HfTranslationModel(
        args.model,
        args.adapter,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        generation_seed=args.generation_seed,
    )
    predictions, batch_stats = [], []
    all_batches = list(
        batches(
            records,
            max_blocks=args.max_blocks_per_request,
            max_chars=args.max_chars_per_request,
        )
    )
    for batch_index, batch in enumerate(all_batches, 1):
        started = time.monotonic()
        values, first_pass, attempts = translate_batch(model, batch)
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
                    "unexpected_repetitions": unexpected_repetitions(
                        translation, record["reference_text"]
                    ),
                }
            )
        print(f"[{batch_index}/{len(all_batches)}] {len(batch)} records in {elapsed:.2f}s", flush=True)

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions),
        encoding="utf-8",
    )
    summary = summarize(predictions, batch_stats)
    summary.update(
        {
            "model": str(args.model.resolve()),
            "adapter": str(args.adapter.resolve()) if args.adapter else None,
            "dataset": str(args.dataset.resolve()),
            "records": len(predictions),
            "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
            "generation": {
                "temperature": args.temperature,
                "top_p": args.top_p,
                "top_k": args.top_k,
                "seed": args.generation_seed,
                "max_blocks_per_request": args.max_blocks_per_request,
                "max_chars_per_request": args.max_chars_per_request,
            },
        }
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "batches.json").write_text(
        json.dumps(batch_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
