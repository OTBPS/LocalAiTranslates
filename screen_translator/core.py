from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


class Cancelled(Exception):
    pass


class CancellationToken:
    def __init__(self):
        self.event = threading.Event()

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Cancelled()


@dataclass
class OcrLine:
    polygon: list[tuple[float, float]]
    text: str
    confidence: float
    language: str = "auto"

    @property
    def rect(self):
        xs, ys = zip(*self.polygon, strict=True)
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class OcrResult:
    lines: list[OcrLine]
    detected_language: str
    device: str
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class TextBlock:
    block_id: str
    lines: list[OcrLine]
    kind: str = "paragraph"
    column_index: int = 0

    @property
    def text(self):
        return "\n".join(line.text for line in self.lines)

    @property
    def rect(self):
        rs = [line.rect for line in self.lines]
        return min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)


@dataclass
class TranslatedBlock:
    block: TextBlock
    text: str
    draw_rect: tuple | None = None
    font_size: int = 0


LANGUAGE_NAMES = {
    "auto": "自动识别",
    "zh-Hans": "简体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
}
SOURCE_LANGUAGES = tuple(LANGUAGE_NAMES)
TARGET_LANGUAGES = tuple(code for code in LANGUAGE_NAMES if code != "auto")
CURRENT_CONFIG_VERSION = 3


def swap_language_pair(source: str, target: str, detected: str | None = None):
    """Return the swapped pair, or None when swapping is not meaningful yet."""
    actual_source = detected if source == "auto" else source
    if actual_source not in TARGET_LANGUAGES or target not in TARGET_LANGUAGES:
        return None
    if actual_source == target:
        return None
    return target, actual_source


def merge_lines(lines: list[OcrLine]) -> list[TextBlock]:
    """Compatibility facade for the replaceable document layout analyzer."""
    from .layout import LayoutAnalyzer

    return LayoutAnalyzer().analyze(lines)


def parse_translation(raw: str, ids: list[str]) -> dict[str, str]:
    # Never accept extra/missing IDs or coerce malformed model output.
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("重复的文本块 ID")
            out[key] = value
        return out

    value = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or set(value) != set(ids):
        raise ValueError("翻译文本块不完整")
    if any(not isinstance(v, str) or not v.strip() for v in value.values()):
        raise ValueError("译文格式错误")
    return value


def local_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ScreenTranslator"


@dataclass
class Config:
    version: int = CURRENT_CONFIG_VERSION
    hotkey: str = "Ctrl+Alt+T"
    model_dir: str = field(default_factory=lambda: str(local_dir() / "models"))
    translation_model: str = "qwen3-14b-q5-k-m"
    startup: bool = False
    source_language: str = "auto"
    target_language: str = "zh-Hans"
    log_level: str = "WARNING"
    allow_cpu: bool = False

    @staticmethod
    def path():
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "ScreenTranslator" / "config.json"

    @classmethod
    def _migrate(cls, raw):
        if not isinstance(raw, dict):
            raise TypeError("配置根节点必须是对象")
        data = dict(raw)
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError("配置版本无效")
        if version > CURRENT_CONFIG_VERSION:
            raise ValueError("配置由更新版本创建，请升级应用")
        if version == 1:
            data.setdefault("source_language", "auto")
            data.setdefault("target_language", "zh-Hans")
            version = 2
        if version == 2:
            data.setdefault("translation_model", "qwen3-14b-q5-k-m")
            version = 3
        data["version"] = version
        return data

    @classmethod
    def _normalize(cls, data):
        defaults = cls()
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        if not isinstance(values.get("hotkey"), str) or not values["hotkey"].strip():
            values["hotkey"] = defaults.hotkey
        if not isinstance(values.get("model_dir"), str) or not values["model_dir"].strip():
            values["model_dir"] = defaults.model_dir
        from .models import TRANSLATION_MODELS

        if values.get("translation_model") not in TRANSLATION_MODELS:
            values["translation_model"] = defaults.translation_model
        for name in ("startup", "allow_cpu"):
            if not isinstance(values.get(name), bool):
                values[name] = getattr(defaults, name)
        if values.get("source_language") not in SOURCE_LANGUAGES:
            values["source_language"] = defaults.source_language
        if values.get("target_language") not in TARGET_LANGUAGES:
            values["target_language"] = defaults.target_language
        if values.get("log_level") not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            values["log_level"] = defaults.log_level
        values["version"] = CURRENT_CONFIG_VERSION
        return values

    @classmethod
    def load(cls, path=None):
        path = Path(path or cls.path())
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = cls._migrate(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
            path.replace(backup)
            return cls()
        return cls(**cls._normalize(data))

    def save(self, path=None):
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
