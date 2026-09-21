import json

import pytest

from screen_translator.models import (
    ADAPTER_ROLE,
    SUPPORTED_ADAPTERS,
    AdapterError,
    resolve_translation_adapter,
)

BASE = "qwen3-8b-q5-k-m"
ADAPTER = "screen-translator-8b-lora-v1"


def write_registry(root, records):
    (root / "registry.json").write_text(
        json.dumps({"schema_version": 1, "models": records}, ensure_ascii=False),
        encoding="utf-8",
    )


def base_record(root):
    path = root / "base" / "model.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"base-weights")
    return {
        "model_id": BASE,
        "kind": "base-inference",
        "status": "production",
        "roles": ["translation"],
        "path": "base/model.gguf",
        "artifact_type": "file",
        "format": "gguf",
        "size": path.stat().st_size,
        "dependencies": [],
    }


def adapter_record(root, *, payload=b"lora-weights", **overrides):
    path = root / "adapters" / "v1" / "adapter.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    record = {
        "model_id": ADAPTER,
        "kind": "adapter",
        "status": "production",
        "roles": [ADAPTER_ROLE],
        "path": "adapters/v1/adapter.gguf",
        "artifact_type": "file",
        "format": "gguf",
        "size": path.stat().st_size,
        "runtime": {"engine": "llama.cpp", "lora_scale": 4.0},
        "dependencies": [BASE],
    }
    record.update(overrides)
    return record


def test_no_adapter_is_shipped_with_the_application():
    assert SUPPORTED_ADAPTERS == {}


def test_an_empty_allow_list_resolves_to_no_adapter(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path)])

    assert resolve_translation_adapter(tmp_path, BASE, {}) is None
    assert resolve_translation_adapter(tmp_path, BASE) is None


def test_a_released_adapter_resolves_to_a_scaled_lora_argument(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path)])

    binding = resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})

    assert binding.model_id == ADAPTER
    assert binding.path == (tmp_path / "adapters" / "v1" / "adapter.gguf").resolve()
    assert binding.scale == 4.0
    assert binding.argument().endswith("adapter.gguf:4")


def test_a_missing_scale_defaults_to_one(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path, runtime={})])

    assert resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER}).scale == 1.0


def test_an_unregistered_adapter_is_reported_instead_of_ignored(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path)])

    with pytest.raises(AdapterError, match="未注册"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_a_missing_adapter_file_is_reported(tmp_path):
    record = adapter_record(tmp_path)
    (tmp_path / "adapters" / "v1" / "adapter.gguf").unlink()
    write_registry(tmp_path, [base_record(tmp_path), record])

    with pytest.raises(AdapterError, match="文件不存在"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_a_corrupted_adapter_is_reported(tmp_path):
    record = adapter_record(tmp_path)
    (tmp_path / "adapters" / "v1" / "adapter.gguf").write_bytes(b"truncated")
    write_registry(tmp_path, [base_record(tmp_path), record])

    with pytest.raises(AdapterError, match="文件大小不匹配"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_an_experimental_adapter_never_reaches_the_application(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path, status="experimental")])

    with pytest.raises(AdapterError, match="未通过发布门槛"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_a_peft_adapter_is_rejected_because_llama_cpp_cannot_load_it(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path, format="safetensors")])

    with pytest.raises(AdapterError, match="格式"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_an_adapter_for_another_base_model_is_rejected(tmp_path):
    write_registry(
        tmp_path, [base_record(tmp_path), adapter_record(tmp_path, dependencies=["qwen3-4b-hf-1cfa9a7"])]
    )

    with pytest.raises(AdapterError, match="不依赖基础模型"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_a_record_that_is_not_an_adapter_is_rejected(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path, kind="derived")])

    with pytest.raises(AdapterError, match="类型无效"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_an_adapter_without_the_translation_adapter_role_is_rejected(tmp_path):
    write_registry(tmp_path, [base_record(tmp_path), adapter_record(tmp_path, roles=["translation"])])

    with pytest.raises(AdapterError, match="无法解析"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


@pytest.mark.parametrize("scale", [0, -1, "4.0", True, None])
def test_an_invalid_scale_is_rejected(tmp_path, scale):
    write_registry(
        tmp_path,
        [base_record(tmp_path), adapter_record(tmp_path, runtime={"lora_scale": scale})],
    )

    with pytest.raises(AdapterError, match="缩放系数无效"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})


def test_an_adapter_with_a_missing_dependency_record_is_rejected(tmp_path):
    write_registry(tmp_path, [adapter_record(tmp_path)])

    with pytest.raises(AdapterError, match="缺少依赖"):
        resolve_translation_adapter(tmp_path, BASE, {BASE: ADAPTER})
