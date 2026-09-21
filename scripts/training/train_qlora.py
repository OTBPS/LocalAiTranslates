"""Train a reproducible Qwen3-4B QLoRA adapter on filtered teacher data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)

from scripts.training.training_paths import add_model_arguments, resolve_model_argument, workspace_path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ConversationDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int):
        self.items = []
        for row in rows:
            messages = row["messages"]
            full = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=False,
                enable_thinking=False,
            )
            prompt = tokenizer.apply_chat_template(
                messages[:-1],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            full_ids = full["input_ids"] if hasattr(full, "keys") else full
            prompt_ids = prompt["input_ids"] if hasattr(prompt, "keys") else prompt
            if len(full_ids) > max_length or len(prompt_ids) >= len(full_ids):
                continue
            labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids) :]
            self.items.append(
                {
                    "input_ids": full_ids,
                    "attention_mask": [1] * len(full_ids),
                    "labels": labels,
                }
            )
        if not self.items:
            raise ValueError("no training conversations fit max_length")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


@dataclass
class CausalCollator:
    pad_token_id: int

    def __call__(self, features):
        max_length = max(len(feature["input_ids"]) for feature in features)
        max_length = (max_length + 7) // 8 * 8
        inputs, attention, labels = [], [], []
        for feature in features:
            padding = max_length - len(feature["input_ids"])
            inputs.append(feature["input_ids"] + [self.pad_token_id] * padding)
            attention.append(feature["attention_mask"] + [0] * padding)
            labels.append(feature["labels"] + [-100] * padding)
        return {
            "input_ids": torch.tensor(inputs, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    add_model_arguments(parser)
    parser.add_argument("--data", type=Path, default=workspace_path("data/train/pilot-v1/sft_messages.jsonl"))
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--initial-adapter", type=Path)
    parser.add_argument("--eval-manifest", type=Path, default=workspace_path("data/eval/v1/manifest.json"))
    parser.add_argument("--output", type=Path, default=workspace_path("runs/qwen3-4b-pilot-v1"))
    parser.add_argument("--max-length", type=int, default=3072)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--validation-fraction", type=float, default=0.08)
    parser.add_argument("--eval-steps", type=int, default=25)
    parser.add_argument("--early-stopping-patience", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()
    args.model = resolve_model_argument(args)

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("QLoRA requires CUDA with BF16 support")
    if not 0 < args.validation_fraction < 0.5:
        raise ValueError("--validation-fraction must be between 0 and 0.5")
    audit = None
    if args.audit:
        audit = json.loads(args.audit.read_text(encoding="utf-8"))
        if not audit.get("passed"):
            raise RuntimeError("training data audit did not pass")
        if audit.get("sft_messages_sha256") != file_sha256(args.data):
            raise RuntimeError("training data changed after its audit")
    eval_manifest = json.loads(args.eval_manifest.read_text(encoding="utf-8"))
    if not eval_manifest.get("training_use_prohibited"):
        raise RuntimeError("evaluation manifest does not enforce held-out usage")

    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines()]
    random.Random(args.seed).shuffle(rows)
    validation_size = max(1, round(len(rows) * args.validation_fraction))
    validation_rows, training_rows = rows[:validation_size], rows[validation_size:]

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    train_dataset = ConversationDataset(training_rows, tokenizer, args.max_length)
    validation_dataset = ConversationDataset(validation_rows, tokenizer, args.max_length)
    planned_steps = (
        args.max_steps
        if args.max_steps > 0
        else math.ceil(len(train_dataset) / 8) * math.ceil(args.epochs)
    )
    warmup_steps = max(1, round(planned_steps * 0.05))

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
    if args.initial_adapter:
        model = PeftModel.from_pretrained(model, args.initial_adapter, is_trainable=True)
    else:
        model = get_peft_model(
            model,
            LoraConfig(
                r=16,
                lora_alpha=32,
                lora_dropout=0.05,
                target_modules="all-linear",
                bias="none",
                task_type="CAUSAL_LM",
                use_rslora=True,
            ),
        )
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=str(args.output),
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=args.learning_rate,
        weight_decay=0.01,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        lr_scheduler_type="cosine",
        warmup_steps=warmup_steps,
        bf16=True,
        tf32=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=5,
        save_strategy="steps",
        eval_strategy="steps",
        save_steps=args.eval_steps,
        eval_steps=args.eval_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        seed=args.seed,
        data_seed=args.seed,
        dataloader_num_workers=0,
        remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=CausalCollator(tokenizer.pad_token_id),
        callbacks=[
            EarlyStoppingCallback(early_stopping_patience=args.early_stopping_patience)
        ],
    )
    result = trainer.train(resume_from_checkpoint=True if args.resume else None)
    trainer.save_model(str(args.output / "adapter"))
    tokenizer.save_pretrained(args.output / "adapter")

    report = {
        "schema_version": 1,
        "base_model": str(args.model.resolve()),
        "teacher_data": str(args.data.resolve()),
        "teacher_data_sha256": file_sha256(args.data),
        "audit": str(args.audit.resolve()) if args.audit else None,
        "audit_sha256": file_sha256(args.audit) if args.audit else None,
        "initial_adapter": str(args.initial_adapter.resolve()) if args.initial_adapter else None,
        "held_out_eval_sha256": eval_manifest["dataset_sha256"],
        "train_conversations": len(train_dataset),
        "validation_conversations": len(validation_dataset),
        "max_length": args.max_length,
        "epochs": args.epochs,
        "max_steps": args.max_steps,
        "learning_rate": args.learning_rate,
        "validation_fraction": args.validation_fraction,
        "eval_steps": args.eval_steps,
        "warmup_steps": warmup_steps,
        "early_stopping_patience": args.early_stopping_patience,
        "seed": args.seed,
        "best_model_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval_loss": trainer.state.best_metric,
        "train_metrics": result.metrics,
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "training_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
