"""Stable shared-model and per-project training path resolution."""

from __future__ import annotations

import os
from pathlib import Path

from screen_translator.model_registry import ModelRegistry

MODEL_ROOT = Path(os.environ.get("AI_MODEL_ROOT", r"D:\AI\Models")).expanduser()
TRAINING_ROOT = Path(os.environ.get("AI_TRAINING_ROOT", r"D:\AI\Training")).expanduser() / "screen-translator"
DEFAULT_TRAINING_MODEL_ID = "qwen3-4b-hf-1cfa9a7"


def workspace_path(relative: str) -> Path:
    return TRAINING_ROOT / relative


def add_model_arguments(parser, default_model_id: str = DEFAULT_TRAINING_MODEL_ID) -> None:
    parser.add_argument(
        "--model-id",
        default=default_model_id,
        help="Stable model ID from AI_MODEL_ROOT/registry.json.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        help="Explicit base model path (advanced override; --model-id is preferred).",
    )


def resolve_model_argument(args) -> Path:
    if args.model:
        return args.model.expanduser().resolve()
    return ModelRegistry.open(MODEL_ROOT).resolve(args.model_id, "training")
