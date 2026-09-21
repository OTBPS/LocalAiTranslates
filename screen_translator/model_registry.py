"""Shared, application-neutral model registry.

The registry stores stable model IDs and paths relative to a user-controlled
model root.  Consumers never need to know the physical directory layout.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRY_FILENAME = "registry.json"
SUPPORTED_SCHEMA_VERSION = 1


class RegistryError(RuntimeError):
    """Raised when the shared registry is invalid or cannot satisfy a request."""


@dataclass(frozen=True)
class ValidationResult:
    model_id: str
    path: Path
    valid: bool
    reason: str = ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def tree_sha256(path: Path) -> str:
    """Hash a directory deterministically without depending on timestamps."""
    digest = hashlib.sha256()
    files = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        size = item.stat().st_size
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(_sha256_file(item).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


class ModelRegistry:
    """Resolve and validate models in a shared repository."""

    def __init__(self, root: Path, document: dict[str, Any], *, legacy: bool = False):
        self.root = root.resolve()
        self.document = document
        self.legacy = legacy
        models = document.get("models")
        if document.get("schema_version") != SUPPORTED_SCHEMA_VERSION or not isinstance(models, list):
            raise RegistryError("不支持或损坏的模型注册表")
        self._records: dict[str, dict[str, Any]] = {}
        for record in models:
            if not isinstance(record, dict) or not isinstance(record.get("model_id"), str):
                raise RegistryError("模型注册表包含无效记录")
            if record["model_id"] in self._records:
                raise RegistryError(f"模型 ID 重复：{record['model_id']}")
            self._records[record["model_id"]] = record

    @classmethod
    def open(cls, model_root: str | Path) -> ModelRegistry:
        root = Path(model_root).expanduser().resolve()
        registry_path = root / REGISTRY_FILENAME
        if registry_path.is_file():
            try:
                document = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RegistryError("无法读取模型注册表") from error
            return cls(root, document)
        return cls(root, cls._legacy_document(root), legacy=True)

    @staticmethod
    def _legacy_document(root: Path) -> dict[str, Any]:
        """Read the v0.x flat manifest without modifying it."""
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            manifest = []
        by_path = {
            item.get("path"): item
            for item in manifest
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        known = {
            "qwen3-14b-q5-k-m": ("Qwen3-14B-Q5_K_M.gguf", ["translation"]),
            "qwen3-8b-q5-k-m": ("Qwen3-8B-Q5_K_M.gguf", ["translation"]),
            "qwen3-4b-instruct-2507-q8-0": (
                "Qwen3-4B-Instruct-2507-Q8_0.gguf",
                ["translation"],
            ),
            "paddleocr-pp-ocrv5-mobile-det": ("PP-OCRv5_mobile_det", ["ocr-detection"]),
            "paddleocr-pp-ocrv5-mobile-rec": ("PP-OCRv5_mobile_rec", ["ocr-recognition"]),
            "paddleocr-korean-pp-ocrv5-mobile-rec": (
                "korean_PP-OCRv5_mobile_rec",
                ["ocr-recognition-ko"],
            ),
            "paddleocr-latin-pp-ocrv5-mobile-rec": (
                "latin_PP-OCRv5_mobile_rec",
                ["ocr-recognition-latin"],
            ),
        }
        records = []
        for model_id, (relative, roles) in known.items():
            path = root / relative
            if not path.exists():
                continue
            if path.is_file():
                legacy = by_path.get(relative, {})
                if not legacy:
                    continue
                size = legacy.get("size", path.stat().st_size)
                sha256 = legacy.get("sha256")
                artifact_type = "file"
            else:
                if not any(
                    isinstance(name, str) and name.startswith(relative + "/")
                    for name in by_path
                ):
                    continue
                size = sum(
                    item.get("size", 0)
                    for name, item in by_path.items()
                    if isinstance(name, str) and name.startswith(relative + "/")
                ) or tree_size(path)
                sha256 = None
                artifact_type = "directory"
            records.append(
                {
                    "model_id": model_id,
                    "kind": "auxiliary" if "ocr" in model_id else "base-inference",
                    "status": "experimental" if "latin" in model_id else "production",
                    "roles": roles,
                    "path": relative,
                    "artifact_type": artifact_type,
                    "size": size,
                    "sha256": sha256,
                    "dependencies": [],
                }
            )
        return {"schema_version": 1, "models": records}

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._records.values())

    def record(self, model_id: str) -> dict[str, Any]:
        try:
            return self._records[model_id]
        except KeyError as error:
            raise RegistryError(f"模型未注册：{model_id}") from error

    def resolve(self, model_id: str, role: str | None = None) -> Path:
        record = self.record(model_id)
        if record.get("status") not in {"production", "experimental", "deprecated"}:
            raise RegistryError(f"模型状态无效：{model_id}")
        roles = record.get("roles", [])
        if role and role not in roles:
            raise RegistryError(f"模型 {model_id} 不支持角色 {role}")
        relative = record.get("path")
        if not isinstance(relative, str) or not relative.strip():
            raise RegistryError(f"模型路径无效：{model_id}")
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise RegistryError(f"模型路径越界：{model_id}")
        return candidate

    def validate(self, model_id: str, full_hash: bool = False) -> ValidationResult:
        try:
            record = self.record(model_id)
            path = self.resolve(model_id)
            for dependency in record.get("dependencies", []):
                if dependency not in self._records:
                    return ValidationResult(model_id, path, False, f"缺少依赖：{dependency}")
            artifact_type = record.get("artifact_type", "file")
            exists = path.is_dir() if artifact_type == "directory" else path.is_file()
            if not exists:
                return ValidationResult(model_id, path, False, "文件不存在")
            actual_size = tree_size(path) if artifact_type == "directory" else path.stat().st_size
            if not isinstance(record.get("size"), int) or actual_size != record["size"]:
                return ValidationResult(model_id, path, False, "文件大小不匹配")
            if full_hash:
                expected = record.get("sha256")
                if not isinstance(expected, str) or len(expected) != 64:
                    return ValidationResult(model_id, path, False, "缺少 SHA-256")
                actual = tree_sha256(path) if artifact_type == "directory" else _sha256_file(path)
                if actual.lower() != expected.lower():
                    return ValidationResult(model_id, path, False, "SHA-256 不匹配")
            return ValidationResult(model_id, path, True)
        except (OSError, RegistryError, TypeError, ValueError) as error:
            return ValidationResult(model_id, self.root, False, str(error))

    def resolve_requirements(self, project_requirements: str | Path | dict[str, Any]) -> dict[str, Path]:
        if isinstance(project_requirements, (str, Path)):
            document = json.loads(Path(project_requirements).read_text(encoding="utf-8"))
        else:
            document = project_requirements
        requirements = document.get("required_models")
        if not isinstance(requirements, list):
            raise RegistryError("项目模型需求格式无效")
        resolved = {}
        for item in requirements:
            if not isinstance(item, dict) or not isinstance(item.get("model_id"), str):
                raise RegistryError("项目模型需求包含无效记录")
            model_id = item["model_id"]
            resolved[model_id] = self.resolve(model_id, item.get("role"))
        return resolved

    def update(self, records: list[dict[str, Any]], **metadata: Any) -> None:
        if self.legacy:
            raise RegistryError("旧版 manifest 只读；请先迁移到 registry.json")
        document = dict(self.document)
        document.update(metadata)
        document["schema_version"] = SUPPORTED_SCHEMA_VERSION
        document["models"] = records
        temporary = self.root / f"{REGISTRY_FILENAME}.tmp"
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.root / REGISTRY_FILENAME)
        self.document = document
        self._records = {record["model_id"]: record for record in records}
