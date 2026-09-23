"""Wire format shared by the remote client and the host service.

This module is deliberately free of Qt, OpenCV and any model runtime: the host
service imports it inside the desktop process, but a thin client build that
ships no weights must be able to import it too.

Two rules shape every decoder here.  Payloads arrive from another machine and
are untrusted, so each field is validated for type, range and size rather than
coerced.  And the reply to a translation carries only ``{block_id: text}``:
polygons never leave the capturing device, which keeps the downlink at a few
kilobytes and lets the client render with its own DPI and fonts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence

from ..core import OcrLine, OcrResult, TextBlock, TranslatedBlock

#: What this build sends and prefers.
PROTOCOL_VERSION = 2
#: What it will also speak, newest first. Both ends used to demand exact
#: equality, so raising the number alone would have made every v1 install
#: and every v2 install refuse each other -- which is why negotiation had
#: to ship before the first feature that needed a new version.
SUPPORTED_PROTOCOL_VERSIONS = (2, 1)
#: The version assumed when a peer sends no version header at all. Only a
#: v1 build does that.
LEGACY_PROTOCOL_VERSION = 1

# Bounds exist to keep a malicious or broken peer from exhausting host memory.
# They are generous compared with a real screenshot selection.
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_BLOCKS = 512
MAX_BLOCK_CHARACTERS = 20000
MAX_LINES = 4096
MAX_POLYGON_POINTS = 64
MAX_EVENT_BYTES = 8 * 1024 * 1024

#: The only route that runs without a secret, because it is how a device
#: gets one. Named here rather than in the host service so the thin
#: client can reach it without importing anything host-side.
PAIR_CLAIM_PATH = "/v1/pair/claim"
#: A claim is two short strings. The cap is what stops an unauthenticated
#: peer making the host buffer anything worth buffering.
MAX_CLAIM_BYTES = 512

EVENT_PROGRESS = "progress"
EVENT_RESULT = "result"
EVENT_ERROR = "error"
_EVENT_TYPES = (EVENT_PROGRESS, EVENT_RESULT, EVENT_ERROR)

_LANGUAGES = ("auto", "zh-Hans", "en", "ja", "ko")


class ProtocolError(ValueError):
    """Raised when a peer sends a payload this version cannot accept."""


def parse_version(value: object) -> int | None:
    """Read a peer's advertised version. ``None`` means "unreadable"."""
    if value is None:
        return LEGACY_PROTOCOL_VERSION
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        # A version header is a small integer; anything else is either a
        # broken peer or someone probing.
        if text.isdigit() and len(text) <= 4:
            return int(text)
    return None


def negotiate(peer_version: object, supported: Sequence[int] | None = None) -> int | None:
    """The highest version both ends speak, or ``None`` if there is none.

    A peer advertising something newer than anything here is answered at
    this build's own best version rather than refused: a newer client is
    required to be able to fall back, and refusing it would strand the
    older side of a rolling upgrade.
    """
    # Read at call time, not bound as a default: a build's own set is a
    # module fact, and tests need to stand in for an older one.
    supported = tuple(supported if supported is not None else SUPPORTED_PROTOCOL_VERSIONS)
    version = parse_version(peer_version)
    if version is None:
        return None
    if version in supported:
        return version
    highest = max(supported)
    return highest if version > highest else None


def describe_version_mismatch(peer_version: object) -> str:
    return f"协议版本不兼容（对方 {peer_version}，本机支持 {list(SUPPORTED_PROTOCOL_VERSIONS)}）"


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _text(value: object, field: str, *, limit: int = MAX_BLOCK_CHARACTERS) -> str:
    _require(isinstance(value, str), f"{field} 必须是字符串")
    assert isinstance(value, str)
    _require(len(value) <= limit, f"{field} 超过 {limit} 字符上限")
    return value


def _number(value: object, field: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} 必须是数字")
    assert isinstance(value, (int, float))
    _require(math.isfinite(value), f"{field} 必须是有限数字")
    return float(value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping), f"{field} 必须是对象")
    assert isinstance(value, Mapping)
    return value


def _sequence(value: object, field: str, limit: int) -> Sequence[object]:
    _require(isinstance(value, list), f"{field} 必须是数组")
    assert isinstance(value, list)
    _require(len(value) <= limit, f"{field} 超过 {limit} 项上限")
    return value


def _language(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    _require(value in _LANGUAGES, f"{field} 不是受支持的语言")
    assert isinstance(value, str)
    return value


def encode_ocr_line(line: OcrLine) -> dict[str, object]:
    return {
        "polygon": [[float(x), float(y)] for x, y in line.polygon],
        "text": line.text,
        "confidence": float(line.confidence),
        "language": line.language,
    }


def decode_ocr_line(payload: object) -> OcrLine:
    data = _mapping(payload, "识别行")
    points = _sequence(data.get("polygon"), "polygon", MAX_POLYGON_POINTS)
    _require(len(points) >= 3, "polygon 至少需要 3 个点")
    polygon: list[tuple[float, float]] = []
    for point in points:
        pair = _sequence(point, "polygon 点", 2)
        _require(len(pair) == 2, "polygon 点必须是两个坐标")
        polygon.append((_number(pair[0], "polygon.x"), _number(pair[1], "polygon.y")))
    return OcrLine(
        polygon=polygon,
        text=_text(data.get("text"), "text"),
        confidence=_number(data.get("confidence"), "confidence"),
        language=_language(data.get("language", "auto"), "language") or "auto",
    )


def encode_ocr_result(result: OcrResult) -> dict[str, object]:
    return {
        "lines": [encode_ocr_line(line) for line in result.lines],
        "detected_language": result.detected_language,
        "device": result.device,
        "timings_ms": {str(key): float(value) for key, value in result.timings_ms.items()},
    }


def decode_ocr_result(payload: object) -> OcrResult:
    data = _mapping(payload, "识别结果")
    lines = _sequence(data.get("lines"), "lines", MAX_LINES)
    timings = _mapping(data.get("timings_ms", {}), "timings_ms")
    return OcrResult(
        lines=[decode_ocr_line(line) for line in lines],
        detected_language=_text(
            data.get("detected_language", "auto"), "detected_language", limit=32
        ),
        device=_text(data.get("device", "未知"), "device", limit=64),
        timings_ms={
            _text(key, "timings_ms 键", limit=64): _number(value, "timings_ms 值")
            for key, value in timings.items()
        },
    )


def encode_translation_request(
    blocks: Sequence[TextBlock],
    source_language: str,
    target_language: str,
    detected_language: str | None,
) -> dict[str, object]:
    """Send identifiers and text only; geometry stays on the capturing device."""
    return {
        "blocks": [{"block_id": block.block_id, "text": block.text} for block in blocks],
        "source_language": source_language,
        "target_language": target_language,
        "detected_language": detected_language,
    }


def decode_translation_request(payload: object) -> dict[str, object]:
    data = _mapping(payload, "翻译请求")
    entries = _sequence(data.get("blocks"), "blocks", MAX_BLOCKS)
    _require(entries, "blocks 不能为空")
    blocks: list[TextBlock] = []
    seen: set[str] = set()
    for entry in entries:
        item = _mapping(entry, "文本块")
        block_id = _text(item.get("block_id"), "block_id", limit=64)
        _require(block_id, "block_id 不能为空")
        _require(block_id not in seen, "block_id 重复")
        seen.add(block_id)
        blocks.append(rebuild_block(block_id, _text(item.get("text"), "text")))
    return {
        "blocks": blocks,
        "source_language": _language(data.get("source_language", "auto"), "source_language"),
        "target_language": _language(data.get("target_language", "zh-Hans"), "target_language"),
        "detected_language": _language(
            data.get("detected_language"), "detected_language", allow_none=True
        ),
    }


def rebuild_block(block_id: str, text: str) -> TextBlock:
    """Rebuild a translatable block from text alone.

    The translation path reads only ``block_id`` and ``text`` (see
    ``translation_engine`` and ``translation_quality``), so placeholder
    geometry is sufficient and no polygon has to cross the network.  Splitting
    on newlines keeps ``TextBlock.text`` identical to the one the client sent.
    """
    placeholder = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    lines = [OcrLine(list(placeholder), part, 1.0) for part in text.split("\n")]
    return TextBlock(block_id, lines)


def encode_translation_result(translated: Iterable[TranslatedBlock]) -> dict[str, str]:
    return {item.block.block_id: item.text for item in translated}


def decode_translation_result(payload: object, expected_ids: Sequence[str]) -> dict[str, str]:
    data = _mapping(payload, "翻译结果")
    _require(set(data) == set(expected_ids), "译文文本块与请求不一致")
    return {key: _text(value, "译文") for key, value in data.items()}


def apply_translation(
    blocks: Sequence[TextBlock], values: Mapping[str, str]
) -> list[TranslatedBlock]:
    """Reattach remote text to the local blocks that still hold the geometry."""
    return [TranslatedBlock(block, values[block.block_id]) for block in blocks]


def encode_event(event_type: str, **fields: object) -> bytes:
    _require(event_type in _EVENT_TYPES, f"未知事件类型：{event_type}")
    body = json.dumps({"type": event_type, **fields}, ensure_ascii=False, separators=(",", ":"))
    return f"data: {body}\n\n".encode()


def heartbeat() -> bytes:
    """A comment frame: it carries no state but proves the socket is still open.

    Cancellation depends on this.  Model inference emits no progress for
    seconds at a time, so without a periodic write the host would never notice
    that the client pressed Esc and closed the connection.
    """
    return b": ping\n\n"


def iter_events(lines: Iterable[bytes]) -> Iterator[dict[str, object] | None]:
    """Yield decoded events, or ``None`` for a heartbeat or blank line.

    Yielding ``None`` rather than skipping is what lets the caller check its
    cancellation token on every frame instead of only on real events.
    """
    for raw in lines:
        if not raw:
            yield None
            continue
        _require(len(raw) <= MAX_EVENT_BYTES, "事件帧过大")
        if raw.startswith(b":"):
            yield None
            continue
        _require(raw.startswith(b"data: "), "不是有效的事件帧")
        try:
            payload = json.loads(raw[6:].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProtocolError("事件帧不是合法 JSON") from error
        data = _mapping(payload, "事件")
        _require(data.get("type") in _EVENT_TYPES, "未知事件类型")
        yield dict(data)
