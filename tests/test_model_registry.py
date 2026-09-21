import hashlib
import json

import pytest

from screen_translator.model_registry import ModelRegistry, RegistryError, tree_sha256


def write_registry(root, records):
    (root / "registry.json").write_text(
        json.dumps({"schema_version": 1, "models": records}), encoding="utf-8"
    )


def record(path="base/model.bin", **overrides):
    values = {
        "model_id": "test-model",
        "kind": "base-inference",
        "status": "production",
        "roles": ["translation"],
        "path": path,
        "artifact_type": "file",
        "size": 4,
        "sha256": hashlib.sha256(b"data").hexdigest(),
        "dependencies": [],
    }
    values.update(overrides)
    return values


def test_resolve_validate_and_requirements(tmp_path):
    target = tmp_path / "base/model.bin"
    target.parent.mkdir()
    target.write_bytes(b"data")
    write_registry(tmp_path, [record()])
    registry = ModelRegistry.open(tmp_path)

    assert registry.resolve("test-model", "translation") == target
    assert registry.validate("test-model").valid
    assert registry.validate("test-model", full_hash=True).valid
    assert registry.resolve_requirements(
        {"required_models": [{"model_id": "test-model", "role": "translation"}]}
    ) == {"test-model": target}


def test_rejects_path_traversal_and_wrong_role(tmp_path):
    write_registry(tmp_path, [record("../outside.bin")])
    registry = ModelRegistry.open(tmp_path)
    with pytest.raises(RegistryError, match="越界"):
        registry.resolve("test-model")
    write_registry(tmp_path, [record()])
    with pytest.raises(RegistryError, match="角色"):
        ModelRegistry.open(tmp_path).resolve("test-model", "training")


def test_validation_reports_size_hash_status_and_dependency(tmp_path):
    target = tmp_path / "base/model.bin"
    target.parent.mkdir()
    target.write_bytes(b"data")
    write_registry(tmp_path, [record(size=7)])
    assert ModelRegistry.open(tmp_path).validate("test-model").reason == "文件大小不匹配"
    write_registry(tmp_path, [record(sha256="0" * 64)])
    assert ModelRegistry.open(tmp_path).validate("test-model", full_hash=True).reason == "SHA-256 不匹配"
    write_registry(tmp_path, [record(status="unknown")])
    assert "状态无效" in ModelRegistry.open(tmp_path).validate("test-model").reason
    write_registry(tmp_path, [record(dependencies=["missing-model"])])
    assert "缺少依赖" in ModelRegistry.open(tmp_path).validate("test-model").reason


def test_directory_tree_hash_is_deterministic(tmp_path):
    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "b").write_bytes(b"2")
    (directory / "a").write_bytes(b"1")
    assert tree_sha256(directory) == tree_sha256(directory)


def test_legacy_manifest_is_read_only_compatible(tmp_path):
    payload = tmp_path / "Qwen3-8B-Q5_K_M.gguf"
    payload.write_bytes(b"data")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "path": payload.name,
                    "size": 4,
                    "sha256": hashlib.sha256(b"data").hexdigest(),
                }
            ]
        ),
        encoding="utf-8",
    )
    registry = ModelRegistry.open(tmp_path)
    assert registry.legacy
    assert registry.resolve("qwen3-8b-q5-k-m") == payload
    assert registry.validate("qwen3-8b-q5-k-m", full_hash=True).valid
