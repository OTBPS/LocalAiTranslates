"""Measure chosen/rejected completion margins before preference training."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import torch
from peft import PeftModel
from torch.utils.data import DataLoader
from train_preference_qlora import (
    PreferenceCollator,
    PreferenceDataset,
    completion_logps,
    file_sha256,
)
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from scripts.training.training_paths import add_model_arguments, resolve_model_argument


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile of an empty sequence")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main() -> int:
    parser = argparse.ArgumentParser()
    add_model_arguments(parser)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=3072)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.model = resolve_model_argument(args)

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("preference margin analysis requires CUDA with BF16 support")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("pairs_sha256") != file_sha256(args.pairs):
        raise RuntimeError("preference pairs changed after manifest creation")
    if manifest.get("held_out_overlap") != 0:
        raise RuntimeError("preference pairs overlap held-out data")

    rows = [json.loads(line) for line in args.pairs.read_text(encoding="utf-8").splitlines()]
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dataset = PreferenceDataset(rows, tokenizer, args.max_length)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=PreferenceCollator(tokenizer.pad_token_id),
    )

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization,
        dtype=torch.bfloat16,
        device_map={"": 0},
        attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(model, args.adapter, is_trainable=False)
    model.eval()

    margins: list[float] = []
    chosen_nlls: list[float] = []
    rejected_nlls: list[float] = []
    with torch.inference_mode():
        for batch in loader:
            pair_count = batch.pop("pair_count")
            batch = {key: value.cuda() for key, value in batch.items()}
            outputs = model(**batch)
            _, averages, _ = completion_logps(outputs.logits, batch["labels"])
            chosen = averages[:pair_count].float().cpu()
            rejected = averages[pair_count:].float().cpu()
            margins.extend((chosen - rejected).tolist())
            chosen_nlls.extend((-chosen).tolist())
            rejected_nlls.extend((-rejected).tolist())

    report = {
        "schema_version": 1,
        "model": str(args.model.resolve()),
        "adapter": str(args.adapter.resolve()),
        "pairs": str(args.pairs.resolve()),
        "pairs_sha256": file_sha256(args.pairs),
        "pair_count": len(margins),
        "preference_accuracy": sum(value > 0 for value in margins) / len(margins),
        "margin": {
            "minimum": min(margins),
            "p10": percentile(margins, 0.10),
            "median": statistics.median(margins),
            "mean": statistics.fmean(margins),
            "p90": percentile(margins, 0.90),
            "maximum": max(margins),
        },
        "mean_chosen_nll": statistics.fmean(chosen_nlls),
        "mean_rejected_nll": statistics.fmean(rejected_nlls),
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
