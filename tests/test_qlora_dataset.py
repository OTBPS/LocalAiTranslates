import json

import pytest

transformers = pytest.importorskip("transformers")
from scripts.training.train_qlora import ConversationDataset  # noqa: E402
from scripts.training.training_paths import MODEL_ROOT, TRAINING_ROOT  # noqa: E402


def test_conversation_dataset_masks_prompt_tokens():
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        MODEL_ROOT / "base/qwen/Qwen3-4B/hf/1cfa9a7"
    )
    row = json.loads(
        (TRAINING_ROOT / "data/train/pilot-v1/sft_messages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    dataset = ConversationDataset([row], tokenizer, 3072)
    item = dataset[0]
    first_target = next(index for index, label in enumerate(item["labels"]) if label != -100)
    assert first_target > 0
    assert all(label == -100 for label in item["labels"][:first_target])
    assert any(label != -100 for label in item["labels"][first_target:])
