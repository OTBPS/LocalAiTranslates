"""Move Screen Translator model and training assets into shared repositories.

The operation is same-volume and journaled.  It never copies model payloads.
Run with --dry-run first; --rollback reverses a completed or interrupted move.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_ROOT = Path(os.environ.get("AI_MODEL_ROOT", r"D:\AI\Models"))
DEFAULT_TRAINING_ROOT = Path(
    os.environ.get("AI_TRAINING_ROOT", r"D:\AI\Training")
) / "screen-translator"
JOURNAL = PROJECT.parent / "screen-translator-model-migration.json"
LOCK = PROJECT.parent / ".screen-translator-model-migration.lock"


@dataclass
class Move:
    source: str
    destination: str
    status: str = "pending"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_metadata(path: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    files = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
    size = 0
    for item in files:
        relative = item.relative_to(path).as_posix()
        item_size = item.stat().st_size
        item_hash = sha256_file(item)
        size += item_size
        digest.update(f"{relative}\0{item_size}\0{item_hash}\n".encode())
    return len(files), size, digest.hexdigest()


def moves_for(model_root: Path, training_root: Path) -> list[Move]:
    old_models = PROJECT / "models"
    old_training = PROJECT / "training"
    mapping = [
        (old_models / "Qwen3-14B-Q5_K_M.gguf", model_root / "base/qwen/Qwen3-14B-GGUF/gguf/Q5_K_M/Qwen3-14B-Q5_K_M.gguf"),
        (old_models / "Qwen3-8B-Q5_K_M.gguf", model_root / "base/qwen/Qwen3-8B-GGUF/gguf/Q5_K_M/Qwen3-8B-Q5_K_M.gguf"),
        (old_models / "Qwen3-4B-Instruct-2507-Q8_0.gguf", model_root / "base/unsloth/Qwen3-4B-Instruct-2507-GGUF/gguf/Q8_0/Qwen3-4B-Instruct-2507-Q8_0.gguf"),
        (old_models / "PP-OCRv5_mobile_det", model_root / "base/paddlepaddle/PP-OCRv5_mobile_det"),
        (old_models / "PP-OCRv5_mobile_rec", model_root / "base/paddlepaddle/PP-OCRv5_mobile_rec"),
        (old_models / "korean_PP-OCRv5_mobile_rec", model_root / "base/paddlepaddle/korean_PP-OCRv5_mobile_rec"),
        (old_models / "latin_PP-OCRv5_mobile_rec", model_root / "base/paddlepaddle/latin_PP-OCRv5_mobile_rec"),
        (old_models / "LICENSE", model_root / "licenses/qwen/LICENSE"),
        (old_models / "manifest.json", training_root / "migration-audit/legacy-inference-manifest.json"),
        (old_training / "models/Qwen3-4B", model_root / "base/qwen/Qwen3-4B/hf/1cfa9a7"),
        (old_training / "models/Qwen3-8B", model_root / "base/qwen/Qwen3-8B/hf/b968826"),
    ]
    if old_training.exists():
        mapping.extend(
            (item, training_root / item.name)
            for item in old_training.iterdir()
            if item.name != "models"
        )
    return [Move(str(source.resolve()), str(destination.resolve())) for source, destination in mapping]


def acquire_lock() -> int:
    try:
        return os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"迁移锁已存在：{LOCK}") from error


def release_lock(handle: int) -> None:
    os.close(handle)
    LOCK.unlink(missing_ok=True)


def preflight(moves: list[Move]) -> None:
    for move in moves:
        source, destination = Path(move.source), Path(move.destination)
        if source.exists() and destination.exists():
            raise RuntimeError(f"目标冲突：{destination}")
        if not source.exists() and not destination.exists():
            raise RuntimeError(f"源资产缺失：{source}")
        if not source.drive or source.drive.lower() != destination.drive.lower():
            raise RuntimeError(f"拒绝跨盘迁移：{source} -> {destination}")


def replace_paths(value: Any, old_training: Path, training_root: Path, model_root: Path) -> tuple[Any, list[str]]:
    changed: list[str] = []
    old_text = str(old_training)
    old_slash = old_text.replace("\\", "/")
    model_map = {
        str(old_training / "models/Qwen3-4B"): str(model_root / "base/qwen/Qwen3-4B/hf/1cfa9a7"),
        str(old_training / "models/Qwen3-8B"): str(model_root / "base/qwen/Qwen3-8B/hf/b968826"),
        "training\\models\\Qwen3-4B": str(model_root / "base/qwen/Qwen3-4B/hf/1cfa9a7"),
        "training\\models\\Qwen3-8B": str(model_root / "base/qwen/Qwen3-8B/hf/b968826"),
        "training/models/Qwen3-4B": str(model_root / "base/qwen/Qwen3-4B/hf/1cfa9a7"),
        "training/models/Qwen3-8B": str(model_root / "base/qwen/Qwen3-8B/hf/b968826"),
    }
    if isinstance(value, str):
        original = value
        for source, destination in model_map.items():
            value = value.replace(source, destination)
        value = value.replace(old_text, str(training_root)).replace(old_slash, training_root.as_posix())
        value = value.replace("training\\", str(training_root) + "\\").replace("training/", training_root.as_posix() + "/")
        return value, [original] if value != original else []
    if isinstance(value, list):
        result = []
        for item in value:
            converted, item_changed = replace_paths(item, old_training, training_root, model_root)
            result.append(converted)
            changed.extend(item_changed)
        return result, changed
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            converted, item_changed = replace_paths(item, old_training, training_root, model_root)
            result[key] = converted
            changed.extend(item_changed)
        return result, changed
    return value, changed


def rewrite_training_metadata(training_root: Path, model_root: Path) -> list[str]:
    audit_root = training_root / "migration-audit/metadata-backups"
    changed_files = []
    candidates = set(training_root.rglob("adapter_config.json"))
    candidates.update(training_root.rglob("*manifest*.json"))
    old_training = PROJECT / "training"
    for path in sorted(candidates):
        try:
            original_text = path.read_text(encoding="utf-8")
            value = json.loads(original_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        converted, legacy_paths = replace_paths(value, old_training, training_root, model_root)
        if not legacy_paths:
            continue
        if isinstance(converted, dict):
            converted.setdefault("migration", {})
            converted["migration"].update(
                {
                    "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "legacy_paths": sorted(set(legacy_paths)),
                }
            )
        backup = audit_root / path.relative_to(training_root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(original_text, encoding="utf-8")
        atomic_json(path, converted)
        changed_files.append(path.relative_to(training_root).as_posix())
    return changed_files


def source_revision(path: Path) -> str | None:
    metadata = path / ".cache/huggingface/download/config.json.metadata"
    if metadata.is_file():
        revision = metadata.read_text(encoding="utf-8").splitlines()[0].strip()
        return revision or None
    return None


def build_registry(model_root: Path) -> dict[str, Any]:
    specs = [
        ("qwen3-14b-q5-k-m", "base-inference", "production", ["translation"], "base/qwen/Qwen3-14B-GGUF/gguf/Q5_K_M/Qwen3-14B-Q5_K_M.gguf", "gguf", "Q5_K_M", "Qwen/Qwen3-14B-GGUF"),
        ("qwen3-8b-q5-k-m", "base-inference", "production", ["translation"], "base/qwen/Qwen3-8B-GGUF/gguf/Q5_K_M/Qwen3-8B-Q5_K_M.gguf", "gguf", "Q5_K_M", "Qwen/Qwen3-8B-GGUF"),
        ("qwen3-4b-instruct-2507-q8-0", "base-inference", "production", ["translation"], "base/unsloth/Qwen3-4B-Instruct-2507-GGUF/gguf/Q8_0/Qwen3-4B-Instruct-2507-Q8_0.gguf", "gguf", "Q8_0", "unsloth/Qwen3-4B-Instruct-2507-GGUF"),
        ("paddleocr-pp-ocrv5-mobile-det", "auxiliary", "production", ["ocr-detection"], "base/paddlepaddle/PP-OCRv5_mobile_det", "paddle-inference", None, "PaddlePaddle/PP-OCRv5_mobile_det"),
        ("paddleocr-pp-ocrv5-mobile-rec", "auxiliary", "production", ["ocr-recognition"], "base/paddlepaddle/PP-OCRv5_mobile_rec", "paddle-inference", None, "PaddlePaddle/PP-OCRv5_mobile_rec"),
        ("paddleocr-korean-pp-ocrv5-mobile-rec", "auxiliary", "production", ["ocr-recognition-ko"], "base/paddlepaddle/korean_PP-OCRv5_mobile_rec", "paddle-inference", None, "PaddlePaddle/korean_PP-OCRv5_mobile_rec"),
        ("paddleocr-latin-pp-ocrv5-mobile-rec", "auxiliary", "experimental", ["ocr-recognition-latin"], "base/paddlepaddle/latin_PP-OCRv5_mobile_rec", "paddle-inference", None, "PaddlePaddle/latin_PP-OCRv5_mobile_rec"),
        ("qwen3-4b-hf-1cfa9a7", "base-training", "production", ["training"], "base/qwen/Qwen3-4B/hf/1cfa9a7", "safetensors", None, "Qwen/Qwen3-4B"),
        ("qwen3-8b-hf-b968826", "base-training", "production", ["training"], "base/qwen/Qwen3-8B/hf/b968826", "safetensors", None, "Qwen/Qwen3-8B"),
    ]
    records = []
    for model_id, kind, status, roles, relative, format_name, quantization, repository in specs:
        path = model_root / relative
        if not path.exists():
            raise RuntimeError(f"注册资产不存在：{path}")
        if path.is_dir():
            file_count, size, digest = tree_metadata(path)
            artifact_type = "directory"
        else:
            file_count, size, digest = 1, path.stat().st_size, sha256_file(path)
            artifact_type = "file"
        records.append(
            {
                "model_id": model_id,
                "kind": kind,
                "status": status,
                "capabilities": ["translation"] if "translation" in roles or "training" in roles else ["optical-character-recognition"],
                "modalities": {"input": ["text"] if "qwen" in model_id else ["image"], "output": ["text"]},
                "roles": roles,
                "path": relative,
                "artifact_type": artifact_type,
                "format": format_name,
                "quantization": quantization,
                "source": {
                    "repository": repository,
                    "revision": source_revision(path) or "legacy-import-unrecorded",
                },
                "runtime": {"engine": "llama.cpp" if format_name == "gguf" else ("transformers" if kind == "base-training" else "PaddleOCR")},
                "resources": {},
                "file_count": file_count,
                "size": size,
                "sha256": digest,
                "license": "Apache-2.0",
                "license_path": "licenses/qwen/LICENSE" if "qwen" in model_id else None,
                "dependencies": [],
            }
        )
    return {
        "schema_version": 1,
        "repository_id": "local-user-models",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path_policy": "All paths are relative to this registry file.",
        "models": records,
    }


def update_config(config_path: Path, model_root: Path, audit_root: Path) -> None:
    if not config_path.exists():
        return
    original = config_path.read_text(encoding="utf-8")
    config = json.loads(original)
    audit_root.mkdir(parents=True, exist_ok=True)
    (audit_root / "config-before.json").write_text(original, encoding="utf-8")
    config["model_dir"] = str(model_root)
    atomic_json(config_path, config)


def remove_empty_legacy_dirs() -> None:
    candidates = [PROJECT / "training/models", PROJECT / "training", PROJECT / "models"]
    for path in candidates:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def restore_training_metadata(training_root: Path) -> None:
    backup_root = training_root / "migration-audit/metadata-backups"
    if not backup_root.is_dir():
        return
    for backup in sorted(item for item in backup_root.rglob("*") if item.is_file()):
        destination = training_root / backup.relative_to(backup_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, destination)


def rollback(journal_path: Path) -> None:
    if not journal_path.is_file():
        raise RuntimeError("找不到迁移日志，无法回滚")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    training_root = Path(journal["training_root"])
    restore_training_metadata(training_root)
    for item in reversed(journal["moves"]):
        source, destination = Path(item["source"]), Path(item["destination"])
        if destination.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(source)
            item["status"] = "rolled-back"
            atomic_json(journal_path, journal)
    config_path = Path(journal.get("config_path", ""))
    backup = training_root / "migration-audit/config-before.json"
    if config_path and backup.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup, config_path)
    (Path(journal["model_root"]) / "registry.json").unlink(missing_ok=True)
    journal["status"] = "rolled-back"
    atomic_json(journal_path, journal)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--training-root", type=Path, default=DEFAULT_TRAINING_ROOT)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("APPDATA", "")) / "ScreenTranslator/config.json")
    parser.add_argument("--journal", type=Path, default=JOURNAL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    model_root = args.model_root.resolve()
    training_root = args.training_root.resolve()
    moves = moves_for(model_root, training_root)
    if args.dry_run:
        preflight(moves)
        print(json.dumps({"model_root": str(model_root), "training_root": str(training_root), "moves": [asdict(item) for item in moves]}, ensure_ascii=False, indent=2))
        return 0

    lock = acquire_lock()
    try:
        if args.rollback:
            rollback(args.journal)
            return 0
        previous = None
        if args.journal.is_file():
            previous = json.loads(args.journal.read_text(encoding="utf-8"))
            if previous.get("status") == "complete":
                print(f"迁移已经完成：{previous['model_root']}")
                return 0
            if previous.get("status") == "moving":
                moves = [Move(**item) for item in previous["moves"]]
        preflight(moves)
        journal = previous if previous and previous.get("status") == "moving" else {
                "schema_version": 1,
                "status": "moving",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "model_root": str(model_root),
                "training_root": str(training_root),
                "config_path": str(args.config.resolve()),
                "moves": [asdict(item) for item in moves],
            }
        atomic_json(args.journal, journal)
        try:
            for item in journal["moves"]:
                source, destination = Path(item["source"]), Path(item["destination"])
                if destination.exists() and not source.exists():
                    item["status"] = "moved"
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                item["status"] = "moved"
                atomic_json(args.journal, journal)
            changed = rewrite_training_metadata(training_root, model_root)
            registry = build_registry(model_root)
            atomic_json(model_root / "registry.json", registry)
            update_config(args.config.resolve(), model_root, training_root / "migration-audit")
            journal["metadata_files_updated"] = changed
            journal["registry_sha256"] = sha256_file(model_root / "registry.json")
            journal["status"] = "complete"
            journal["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            atomic_json(args.journal, journal)
            remove_empty_legacy_dirs()
        except Exception:
            journal["status"] = "failed"
            atomic_json(args.journal, journal)
            rollback(args.journal)
            raise
    finally:
        release_lock(lock)
    print(f"迁移完成：{model_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
