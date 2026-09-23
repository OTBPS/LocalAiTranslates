from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse


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
# Version 5 adds every field the interaction refactor needs at once, even the
# ones nothing reads yet. Bumping once per feature would mean each intermediate
# release writes a file that an earlier build refuses to load; one bump keeps
# the on-disk shape stable for the whole refactor.
CURRENT_CONFIG_VERSION = 5

LOCAL_MODE = "local"
REMOTE_MODE = "remote"
APPLICATION_MODES = (LOCAL_MODE, REMOTE_MODE)
DEFAULT_SERVICE_PORT = 8765
AUTO_SERVICE_ADDRESS = "auto"
MAX_SECRET_CHARACTERS = 256
MAX_ALLOWED_PEERS = 32
MAX_PAIRED_DEVICES = 16
MAX_DEVICE_LABEL_CHARACTERS = 64


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


def normalize_remote_url(value: object) -> str:
    """Accept only a plain http(s) origin, or return an empty string.

    Structural validation only.  Whether the host is actually on the tailnet
    is a policy question and belongs to ``remote.access``; keeping it out of
    here is what stops the configuration layer from depending on the
    networking layer.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    if "://" not in text:
        # Users copy a bare "100.101.102.103:8765" out of the host window.
        text = f"http://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.path.strip("/") or parsed.query or parsed.params or parsed.username:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def normalize_service_address(value: object) -> str:
    if not isinstance(value, str) or value.strip() in ("", AUTO_SERVICE_ADDRESS):
        return AUTO_SERVICE_ADDRESS
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return AUTO_SERVICE_ADDRESS


@dataclass(frozen=True)
class PairedDevice:
    """A device that completed pairing and holds its own secret.

    ``device_id`` is a digest of the secret, never the secret itself: it is
    what logs and the settings list show, so that identifying a device never
    requires printing credentials.
    """

    device_id: str
    label: str
    address: str
    secret: str
    paired_at: float
    last_seen: float = 0.0

    @staticmethod
    def identify(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def normalize_paired_devices(value: object) -> tuple[PairedDevice, ...]:
    """Rebuild paired devices from JSON, dropping anything malformed.

    ``Config.load`` constructs the dataclass with ``cls(**values)``, which
    performs no nested conversion; without this the field would hold plain
    dicts and every reader would have to guess which it got.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    devices: list[PairedDevice] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, PairedDevice):
            item = asdict(item)
        if not isinstance(item, dict):
            continue
        secret = item.get("secret")
        if not isinstance(secret, str) or not 1 <= len(secret) <= MAX_SECRET_CHARACTERS:
            continue
        label = item.get("label")
        label = label[:MAX_DEVICE_LABEL_CHARACTERS] if isinstance(label, str) else ""
        address = item.get("address")
        address = address.strip() if isinstance(address, str) else ""
        if address:
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                address = ""
        device_id = item.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            device_id = PairedDevice.identify(secret)
        if device_id in seen:
            continue
        seen.add(device_id)
        devices.append(
            PairedDevice(
                device_id=device_id,
                label=label,
                address=address,
                secret=secret,
                paired_at=_timestamp(item.get("paired_at")),
                last_seen=_timestamp(item.get("last_seen")),
            )
        )
    return tuple(devices[:MAX_PAIRED_DEVICES])


def _timestamp(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value >= 0 else 0.0
    return 0.0


def normalize_allowed_peers(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    peers: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        try:
            address = str(ipaddress.ip_address(item.strip()))
        except ValueError:
            continue
        if address not in peers:
            peers.append(address)
    return tuple(peers[:MAX_ALLOWED_PEERS])


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
    # Client role: where this installation runs its models.
    mode: str = LOCAL_MODE
    remote_url: str = ""
    remote_token: str = ""
    # Host role: whether this installation serves other devices.
    service_enabled: bool = False
    service_address: str = AUTO_SERVICE_ADDRESS
    service_port: int = DEFAULT_SERVICE_PORT
    service_token: str = ""
    service_allowed_peers: tuple[str, ...] = field(default_factory=tuple)
    # Fields below are written by version 5 and read as the refactor lands;
    # see CURRENT_CONFIG_VERSION for why they all arrive together.
    onboarding_completed: bool = False
    capture_confirm_on_release: bool = False
    remote_host_id: str = ""
    remote_host_label: str = ""
    remote_protocol: int = 0
    paired_devices: tuple[PairedDevice, ...] = field(default_factory=tuple)
    pairing_strict_peers: bool = True

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
        if version == 3:
            # Cross-device support is additive: an existing single-device
            # installation keeps working with these defaults untouched.
            data.setdefault("mode", LOCAL_MODE)
            data.setdefault("remote_url", "")
            data.setdefault("remote_token", "")
            data.setdefault("service_enabled", False)
            data.setdefault("service_address", AUTO_SERVICE_ADDRESS)
            data.setdefault("service_port", DEFAULT_SERVICE_PORT)
            data.setdefault("service_token", "")
            data.setdefault("service_allowed_peers", [])
            version = 4
        if version == 4:
            # True on migration, False for a fresh Config: an installation
            # that already has a configuration file has already been set up,
            # and showing it onboarding would be a regression.
            data.setdefault("onboarding_completed", True)
            data.setdefault("capture_confirm_on_release", False)
            data.setdefault("remote_host_id", "")
            data.setdefault("remote_host_label", "")
            data.setdefault("remote_protocol", 0)
            data.setdefault("pairing_strict_peers", True)
            # An existing host secret becomes the first paired device so the
            # new multi-secret path has something to work with, while the
            # original field keeps its value: a downgrade to 0.7.0 must still
            # find the secret where it expects it.
            existing = data.get("service_token")
            if "paired_devices" not in data:
                data["paired_devices"] = (
                    [
                        {
                            "device_id": PairedDevice.identify(existing),
                            "label": "已有配对",
                            "address": "",
                            "secret": existing,
                            "paired_at": 0.0,
                        }
                    ]
                    if isinstance(existing, str) and existing
                    else []
                )
            version = 5
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
        for name in (
            "startup",
            "allow_cpu",
            "service_enabled",
            "onboarding_completed",
            "capture_confirm_on_release",
            "pairing_strict_peers",
        ):
            if not isinstance(values.get(name), bool):
                values[name] = getattr(defaults, name)
        if values.get("mode") not in APPLICATION_MODES:
            values["mode"] = defaults.mode
        values["remote_url"] = normalize_remote_url(values.get("remote_url"))
        for name in ("remote_token", "service_token"):
            secret = values.get(name)
            values[name] = (
                secret.strip()
                if isinstance(secret, str) and len(secret) <= MAX_SECRET_CHARACTERS
                else getattr(defaults, name)
            )
        values["service_address"] = normalize_service_address(values.get("service_address"))
        port = values.get("service_port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            values["service_port"] = defaults.service_port
        values["service_allowed_peers"] = normalize_allowed_peers(
            values.get("service_allowed_peers")
        )
        values["paired_devices"] = normalize_paired_devices(values.get("paired_devices"))
        for name in ("remote_host_id", "remote_host_label"):
            text = values.get(name)
            values[name] = (
                text.strip()[:MAX_DEVICE_LABEL_CHARACTERS]
                if isinstance(text, str)
                else getattr(defaults, name)
            )
        protocol = values.get("remote_protocol")
        if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol < 0:
            values["remote_protocol"] = defaults.remote_protocol
        # A remote client with no host to talk to would fail on every capture;
        # fall back to local rather than leaving the app in a dead state.
        if values["mode"] == REMOTE_MODE and not (values["remote_url"] and values["remote_token"]):
            values["mode"] = LOCAL_MODE
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

    def normalized(self):
        """Return this configuration with every field validated.

        ``dataclasses.replace`` performs no validation, so anything that
        builds a configuration in memory has to come back through here before
        it is stored or written; otherwise invalid values are only caught on
        the next load, after they have already reached disk.
        """
        return type(self)(**self._normalize(asdict(self)))

    def save(self, path=None):
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
