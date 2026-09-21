"""Only this module performs external network I/O, on explicit download actions."""

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

from .model_registry import ModelRegistry, RegistryError, tree_sha256, tree_size


@dataclass(frozen=True)
class TranslationModel:
    model_id: str
    display_name: str
    repo: str
    filename: str
    approximate_size_gb: float
    fallback_languages: tuple[str, ...] = ()


TRANSLATION_MODELS = {
    model.model_id: model
    for model in (
        TranslationModel(
            "qwen3-14b-q5-k-m",
            "Qwen3 14B（高质量）",
            "Qwen/Qwen3-14B-GGUF",
            "Qwen3-14B-Q5_K_M.gguf",
            10.5,
        ),
        TranslationModel(
            "qwen3-8b-q5-k-m",
            "Qwen3 8B（平衡）",
            "Qwen/Qwen3-8B-GGUF",
            "Qwen3-8B-Q5_K_M.gguf",
            5.8,
            ("ko",),
        ),
        TranslationModel(
            "qwen3-4b-instruct-2507-q8-0",
            "Qwen3 4B（极速）",
            "unsloth/Qwen3-4B-Instruct-2507-GGUF",
            "Qwen3-4B-Instruct-2507-Q8_0.gguf",
            4.3,
            ("ja", "ko"),
        ),
    )
}
DEFAULT_MODEL_ID = "qwen3-14b-q5-k-m"
# Compatibility aliases for integrations that still import the original names.
QWEN_REPO = TRANSLATION_MODELS[DEFAULT_MODEL_ID].repo
QWEN_FILE = TRANSLATION_MODELS[DEFAULT_MODEL_ID].filename
OCR_NAMES = ["PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec", "korean_PP-OCRv5_mobile_rec"]
DEFAULT_SHARED_MODEL_ROOT = Path(os.environ.get("AI_MODEL_ROOT", r"D:\AI\Models"))
OCR_MODEL_IDS = {
    "PP-OCRv5_mobile_det": "paddleocr-pp-ocrv5-mobile-det",
    "PP-OCRv5_mobile_rec": "paddleocr-pp-ocrv5-mobile-rec",
    "korean_PP-OCRv5_mobile_rec": "paddleocr-korean-pp-ocrv5-mobile-rec",
    "latin_PP-OCRv5_mobile_rec": "paddleocr-latin-pp-ocrv5-mobile-rec",
}
MODEL_LAYOUT = {
    "qwen3-14b-q5-k-m": "base/qwen/Qwen3-14B-GGUF/gguf/Q5_K_M/Qwen3-14B-Q5_K_M.gguf",
    "qwen3-8b-q5-k-m": "base/qwen/Qwen3-8B-GGUF/gguf/Q5_K_M/Qwen3-8B-Q5_K_M.gguf",
    "qwen3-4b-instruct-2507-q8-0": (
        "base/unsloth/Qwen3-4B-Instruct-2507-GGUF/gguf/Q8_0/"
        "Qwen3-4B-Instruct-2507-Q8_0.gguf"
    ),
}


def get_translation_model(model_id: str) -> TranslationModel:
    try:
        return TRANSLATION_MODELS[model_id]
    except KeyError as error:
        raise ValueError(f"不支持的翻译模型：{model_id}") from error


def sha256(path, token):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            token.check()
            digest.update(chunk)
    return digest.hexdigest()


def sha256_unchecked(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url, destination, expected_hash, size, token, progress):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.exists()
        and destination.stat().st_size == size
        and sha256(destination, token) == expected_hash
    ):
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(3):
        token.check()
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == size:
            if sha256(partial, token) == expected_hash:
                partial.replace(destination)
                return
            partial.unlink()
            offset = 0
        if offset > size:
            partial.unlink()
            offset = 0
        if shutil.disk_usage(destination.parent).free < size - offset + 64 * 1024 * 1024:
            raise RuntimeError("模型目录空间不足")
        try:
            with requests.get(
                url, headers={"Range": f"bytes={offset}-"} if offset else {}, stream=True, timeout=(15, 30)
            ) as response:
                response.raise_for_status()
                if offset and response.status_code == 206:
                    if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise RuntimeError("下载服务器返回错误的续传范围")
                else:
                    offset = 0
                with partial.open("ab" if offset else "wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        token.check()
                        stream.write(chunk)
                        offset += len(chunk)
                        progress(destination.name, offset, size)
            if offset != size or sha256(partial, token) != expected_hash:
                partial.unlink(missing_ok=True)
                raise RuntimeError("模型文件校验失败")
            partial.replace(destination)
            return
        except (requests.RequestException, RuntimeError):
            if attempt == 2:
                raise
            token.event.wait(1 + attempt)


def fetch_repo(repo, root, select, token, progress):
    response = requests.get(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=30)
    response.raise_for_status()
    info = response.json()
    revision = info["sha"]
    records = []
    for item in info["siblings"]:
        name = item["rfilename"]
        if not select(name):
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("无效模型路径")
        token.check()
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{quote(name)}"
        lfs = item.get("lfs")
        if lfs:
            digest, size = lfs["sha256"], lfs["size"]
        else:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            digest, size = hashlib.sha256(response.content).hexdigest(), len(response.content)
        download_file(url, root / relative, digest, size, token, progress)
        records.append({"path": name, "sha256": digest, "size": size})
    if not records:
        raise RuntimeError(f"模型仓库未找到文件：{repo}")
    return records


def _read_manifest(root: Path) -> dict[str, dict]:
    try:
        records = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return {
            record["path"]: record
            for record in records
            if isinstance(record, dict) and isinstance(record.get("path"), str)
        }
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def resolve_model_path(root, model_id, role=None):
    """Resolve both shared-registry and legacy flat model layouts."""
    return ModelRegistry.open(root).resolve(model_id, role)


ADAPTER_ROLE = "translation-adapter"
# Fine-tuned adapters that passed the project release gate, keyed by base model ID.
# Empty on purpose: no trained adapter has reached the gate in
# `model-requirements.json` yet, so the application ships base weights only.
# See D:\AI\Training\screen-translator\runs\benchmark-v1\REPORT.md.
SUPPORTED_ADAPTERS: dict[str, str] = {}


class AdapterError(RuntimeError):
    """An allow-listed adapter exists but cannot be used safely."""


@dataclass(frozen=True)
class AdapterBinding:
    model_id: str
    path: Path
    scale: float

    def argument(self) -> str:
        return f"{self.path}:{self.scale:g}"


def resolve_translation_adapter(root, base_model_id, adapters=None):
    """Resolve the released adapter for ``base_model_id`` through the registry.

    Returns ``None`` when the base model has no allow-listed adapter.  When one
    is listed but fails any release requirement this raises instead of silently
    falling back, so a run can never claim to use a trained adapter it did not
    load.
    """
    catalog = SUPPORTED_ADAPTERS if adapters is None else adapters
    adapter_id = catalog.get(base_model_id)
    if not adapter_id:
        return None
    try:
        registry = ModelRegistry.open(root)
        record = registry.record(adapter_id)
    except RegistryError as error:
        raise AdapterError(f"适配器 {adapter_id} 未注册：{error}") from error
    if record.get("kind") != "adapter":
        raise AdapterError(f"适配器 {adapter_id} 的类型无效：{record.get('kind')}")
    if record.get("status") != "production":
        raise AdapterError(f"适配器 {adapter_id} 未通过发布门槛：{record.get('status')}")
    if record.get("format") != "gguf":
        raise AdapterError(f"适配器 {adapter_id} 的格式无法由 llama.cpp 加载：{record.get('format')}")
    if base_model_id not in record.get("dependencies", []):
        raise AdapterError(f"适配器 {adapter_id} 不依赖基础模型 {base_model_id}")
    try:
        path = registry.resolve(adapter_id, ADAPTER_ROLE)
    except RegistryError as error:
        raise AdapterError(f"适配器 {adapter_id} 无法解析：{error}") from error
    result = registry.validate(adapter_id)
    if not result.valid:
        raise AdapterError(f"适配器 {adapter_id} 校验失败：{result.reason}")
    scale = record.get("runtime", {}).get("lora_scale", 1.0)
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale <= 0:
        raise AdapterError(f"适配器 {adapter_id} 的缩放系数无效：{scale}")
    return AdapterBinding(adapter_id, path, float(scale))


def _registry_record(
    root: Path,
    model_id: str,
    path: Path,
    *,
    kind: str,
    status: str,
    roles: list[str],
    format_name: str,
    source_repo: str,
    quantization: str | None = None,
):
    is_directory = path.is_dir()
    return {
        "model_id": model_id,
        "kind": kind,
        "status": status,
        "capabilities": ["translation"] if "translation" in roles else ["optical-character-recognition"],
        "modalities": {"input": ["text"] if "translation" in roles else ["image"], "output": ["text"]},
        "roles": roles,
        "path": path.relative_to(root).as_posix(),
        "artifact_type": "directory" if is_directory else "file",
        "format": format_name,
        "quantization": quantization,
        "source": {"repository": source_repo, "revision": None},
        "runtime": {"engine": "llama.cpp" if format_name == "gguf" else "PaddleOCR"},
        "resources": {},
        "size": tree_size(path) if is_directory else path.stat().st_size,
        "sha256": tree_sha256(path) if is_directory else sha256_unchecked(path),
        "license": "Apache-2.0",
        "dependencies": [],
    }


def _write_registry(root: Path, changed: dict[str, dict]):
    registry_path = root / "registry.json"
    if registry_path.exists():
        registry = ModelRegistry.open(root)
        records = {record["model_id"]: record for record in registry.records}
    else:
        records = {}
    records.update(changed)
    document = {
        "schema_version": 1,
        "repository_id": "local-user-models",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": sorted(records.values(), key=lambda record: record["model_id"]),
    }
    temporary = root / "registry.json.tmp"
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, registry_path)


def install_models(root, token, progress, model_id=DEFAULT_MODEL_ID):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    model = get_translation_model(model_id)
    shared_layout = (root / "registry.json").exists() or root.name.lower() == "models" and root.parent.name.lower() == "ai"
    if not shared_layout:
        records = _read_manifest(root)
        downloaded = fetch_repo(
            model.repo,
            root,
            lambda name: name in (model.filename, "LICENSE"),
            token,
            progress,
        )
        records.update({record["path"]: record for record in downloaded})
        for name in OCR_NAMES:
            sub = root / name
            files = fetch_repo(
                f"PaddlePaddle/{name}",
                sub,
                lambda n: n.endswith((".json", ".yml", ".yaml", ".pdiparams", ".pdmodel", ".txt")),
                token,
                progress,
            )
            for record in files:
                record["path"] = f"{name}/{record['path']}"
            records.update({record["path"]: record for record in files})
        token.check()
        temporary = root / "manifest.tmp"
        temporary.write_text(
            json.dumps(sorted(records.values(), key=lambda record: record["path"]), indent=2),
            encoding="utf-8",
        )
        temporary.replace(root / "manifest.json")
        return

    model_destination = root / MODEL_LAYOUT[model_id]
    model_destination.parent.mkdir(parents=True, exist_ok=True)
    fetch_repo(
        model.repo,
        model_destination.parent,
        lambda name: name in (model.filename, "LICENSE"),
        token,
        progress,
    )
    changed = {
        model_id: _registry_record(
            root,
            model_id,
            model_destination,
            kind="base-inference",
            status="production",
            roles=["translation"],
            format_name="gguf",
            source_repo=model.repo,
            quantization="Q5_K_M" if "Q5_K_M" in model.filename else "Q8_0",
        )
    }
    for name in OCR_NAMES:
        sub = root / "base" / "paddlepaddle" / name
        fetch_repo(
            f"PaddlePaddle/{name}",
            sub,
            lambda n: n.endswith((".json", ".yml", ".yaml", ".pdiparams", ".pdmodel", ".txt")),
            token,
            progress,
        )
        role = "ocr-detection" if name.endswith("_det") else (
            "ocr-recognition-ko" if name.startswith("korean_") else "ocr-recognition"
        )
        changed[OCR_MODEL_IDS[name]] = _registry_record(
            root,
            OCR_MODEL_IDS[name],
            sub,
            kind="auxiliary",
            status="production",
            roles=[role],
            format_name="paddle-inference",
            source_repo=f"PaddlePaddle/{name}",
        )
    token.check()
    _write_registry(root, changed)


def models_ready(root, model_id=DEFAULT_MODEL_ID):
    try:
        registry = ModelRegistry.open(root)
        required = [model_id, *(OCR_MODEL_IDS[name] for name in OCR_NAMES)]
        return all(registry.validate(item).valid for item in required)
    except (OSError, ValueError, KeyError, TypeError, RegistryError):
        return False


def isolate_model_for_redownload(root, model_id):
    """Quarantine only one translation artifact; shared OCR and other models stay put."""
    root = Path(root).resolve()
    registry = ModelRegistry.open(root)
    target = registry.resolve(model_id, "translation")
    if not target.is_file():
        return None
    recovery = root / "recovery" / f"{model_id}-{int(time.time())}"
    recovery.mkdir(parents=True, exist_ok=False)
    target.replace(recovery / target.name)
    if not registry.legacy:
        records = [record for record in registry.records if record["model_id"] != model_id]
        registry.update(
            records,
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    return recovery
