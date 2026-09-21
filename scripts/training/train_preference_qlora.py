"""Train a QLoRA adapter with reference-anchored preference optimization."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from peft import (
    LoraConfig,
    PeftModel,
    get_peft_model,
    prepare_model_for_kbit_training,
)
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

from scripts.training.training_paths import add_model_arguments, resolve_model_argument


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def new_lora_config() -> LoraConfig:
    """Return the same conservative adapter shape used by SFT training."""
    return LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules="all-linear",
        bias="none",
        task_type="CAUSAL_LM",
        use_rslora=True,
    )


def encode_completion(tokenizer, prompt: list[dict], completion: str, max_length: int):
    full = tokenizer.apply_chat_template(
        [*prompt, {"role": "assistant", "content": completion}],
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    prefix = tokenizer.apply_chat_template(
        prompt,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    full_ids = full["input_ids"] if hasattr(full, "keys") else full
    prefix_ids = prefix["input_ids"] if hasattr(prefix, "keys") else prefix
    if len(full_ids) > max_length or len(prefix_ids) >= len(full_ids):
        return None
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": [-100] * len(prefix_ids) + full_ids[len(prefix_ids) :],
    }


class PreferenceDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int):
        self.items = []
        for row in rows:
            chosen = encode_completion(tokenizer, row["prompt"], row["chosen"], max_length)
            rejected = encode_completion(tokenizer, row["prompt"], row["rejected"], max_length)
            if chosen and rejected:
                self.items.append({"chosen": chosen, "rejected": rejected})
        if not self.items:
            raise ValueError("no preference pairs fit max_length")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


@dataclass
class PreferenceCollator:
    pad_token_id: int

    def __call__(self, features):
        sequences = [item["chosen"] for item in features] + [item["rejected"] for item in features]
        max_length = (max(len(item["input_ids"]) for item in sequences) + 7) // 8 * 8
        inputs, attention, labels = [], [], []
        for item in sequences:
            padding = max_length - len(item["input_ids"])
            inputs.append(item["input_ids"] + [self.pad_token_id] * padding)
            attention.append(item["attention_mask"] + [0] * padding)
            labels.append(item["labels"] + [-100] * padding)
        batch = {
            "input_ids": torch.tensor(inputs, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "pair_count": len(features),
        }
        if all("reference_chosen_logp" in item for item in features):
            batch["reference_chosen_logp"] = torch.tensor(
                [item["reference_chosen_logp"] for item in features], dtype=torch.float32
            )
            batch["reference_rejected_logp"] = torch.tensor(
                [item["reference_rejected_logp"] for item in features], dtype=torch.float32
            )
        return batch


def completion_logps(logits: torch.Tensor, labels: torch.Tensor):
    shifted_logits = logits[:, :-1, :]
    shifted_labels = labels[:, 1:]
    mask = shifted_labels != -100
    safe_labels = shifted_labels.masked_fill(~mask, 0)
    token_logps = shifted_logits.log_softmax(-1).gather(-1, safe_labels.unsqueeze(-1)).squeeze(-1)
    sums = (token_logps * mask).sum(-1)
    counts = mask.sum(-1).clamp_min(1)
    return sums, sums / counts, counts


def dpo_loss(
    chosen_logps: torch.Tensor,
    rejected_logps: torch.Tensor,
    reference_chosen_logps: torch.Tensor,
    reference_rejected_logps: torch.Tensor,
    beta: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    policy_logratios = chosen_logps - rejected_logps
    reference_logratios = reference_chosen_logps - reference_rejected_logps
    relative_margins = policy_logratios - reference_logratios
    return -F.logsigmoid(beta * relative_margins).mean(), relative_margins


def attach_reference_logps(
    model,
    dataset: PreferenceDataset,
    collator: PreferenceCollator,
    batch_size: int = 4,
) -> dict[str, float]:
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collator)
    raw_margins: list[float] = []
    offset = 0
    model.eval()
    with torch.inference_mode():
        for batch in loader:
            pair_count = batch.pop("pair_count")
            batch = {key: value.cuda() for key, value in batch.items()}
            outputs = model(**batch)
            _, averages, _ = completion_logps(outputs.logits, batch["labels"])
            chosen = averages[:pair_count].float().cpu()
            rejected = averages[pair_count:].float().cpu()
            for index in range(pair_count):
                item = dataset.items[offset + index]
                item["reference_chosen_logp"] = chosen[index].item()
                item["reference_rejected_logp"] = rejected[index].item()
            raw_margins.extend((chosen - rejected).tolist())
            offset += pair_count
    return {
        "mean_raw_margin": sum(raw_margins) / len(raw_margins),
        "preference_accuracy": sum(value > 0 for value in raw_margins) / len(raw_margins),
    }


class PreferenceTrainer(Trainer):
    def __init__(self, *args, beta: float, sft_weight: float, **kwargs):
        super().__init__(*args, **kwargs)
        # The custom loss is already normalized per pair. Recent Transformers
        # versions otherwise scale it again for gradient accumulation.
        self.model_accepts_loss_kwargs = False
        self.beta = beta
        self.sft_weight = sft_weight

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        pair_count = inputs.pop("pair_count")
        reference_chosen = inputs.pop("reference_chosen_logp")
        reference_rejected = inputs.pop("reference_rejected_logp")
        outputs = model(**inputs)
        sums, averages, counts = completion_logps(outputs.logits, inputs["labels"])
        chosen_avg, rejected_avg = averages[:pair_count], averages[pair_count:]
        preference_loss, relative_margins = dpo_loss(
            chosen_avg,
            rejected_avg,
            reference_chosen,
            reference_rejected,
            self.beta,
        )
        chosen_nll = -(sums[:pair_count].sum() / counts[:pair_count].sum())
        loss = preference_loss + self.sft_weight * chosen_nll
        if return_outputs:
            return loss, {
                "relative_preference_margin": relative_margins.detach().mean(),
                "chosen_nll": chosen_nll.detach(),
            }
        return loss


def main() -> int:
    parser = argparse.ArgumentParser()
    add_model_arguments(parser)
    parser.add_argument(
        "--adapter",
        type=Path,
        help="Optional existing adapter to continue; omit to train a new adapter from the base model.",
    )
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=3072)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--sft-weight", type=float, default=0.1)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    args.model = resolve_model_argument(args)

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("preference QLoRA requires CUDA with BF16 support")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("pairs_sha256") != file_sha256(args.pairs):
        raise RuntimeError("preference pairs changed after manifest creation")
    if manifest.get("held_out_overlap") != 0:
        raise RuntimeError("preference pairs overlap held-out data")

    rows = [json.loads(line) for line in args.pairs.read_text(encoding="utf-8").splitlines()]
    random.Random(args.seed).shuffle(rows)
    validation_size = max(1, round(len(rows) * args.validation_fraction))
    validation_rows, training_rows = rows[:validation_size], rows[validation_size:]

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    train_dataset = PreferenceDataset(training_rows, tokenizer, args.max_length)
    validation_dataset = PreferenceDataset(validation_rows, tokenizer, args.max_length)

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
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter, is_trainable=True)
    else:
        model = get_peft_model(model, new_lora_config())
    collator = PreferenceCollator(tokenizer.pad_token_id)
    train_reference_metrics = attach_reference_logps(model, train_dataset, collator)
    validation_reference_metrics = attach_reference_logps(model, validation_dataset, collator)

    planned_steps = math.ceil(len(train_dataset) / 4) * math.ceil(args.epochs)
    training_args = TrainingArguments(
        output_dir=str(args.output),
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=args.learning_rate,
        weight_decay=0.0,
        num_train_epochs=args.epochs,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, round(planned_steps * 0.1)),
        bf16=True,
        tf32=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1,
        save_strategy="epoch",
        eval_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        max_grad_norm=1.0,
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
    )
    trainer = PreferenceTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=collator,
        beta=args.beta,
        sft_weight=args.sft_weight,
    )
    result = trainer.train()
    trainer.save_model(str(args.output / "adapter"))
    tokenizer.save_pretrained(args.output / "adapter")

    report = {
        "schema_version": 1,
        "base_model": str(args.model.resolve()),
        "initial_adapter": str(args.adapter.resolve()) if args.adapter else None,
        "pairs": str(args.pairs.resolve()),
        "pairs_sha256": file_sha256(args.pairs),
        "train_pairs": len(train_dataset),
        "validation_pairs": len(validation_dataset),
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "beta": args.beta,
        "sft_weight": args.sft_weight,
        "max_grad_norm": training_args.max_grad_norm,
        "train_reference_metrics": train_reference_metrics,
        "validation_reference_metrics": validation_reference_metrics,
        "best_model_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval_loss": trainer.state.best_metric,
        "train_metrics": result.metrics,
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    }
    (args.output / "training_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
