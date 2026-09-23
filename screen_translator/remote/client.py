"""Client side of cross-device translation.

These are ordinary ``OcrPort`` and ``TranslationPort`` implementations that
happen to reach the models over a tailnet, so the capture pipeline in
``controller`` does not change at all: it still calls ``recognize`` then
``translate``, still passes a ``CancellationToken``, and still renders locally
with its own screen DPI and fonts.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace

import requests

from ..core import CancellationToken, OcrResult, TextBlock, TranslatedBlock
from .protocol import (
    EVENT_ERROR,
    EVENT_PROGRESS,
    EVENT_RESULT,
    MAX_IMAGE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    apply_translation,
    decode_ocr_result,
    decode_translation_result,
    describe_version_mismatch,
    encode_translation_request,
    iter_events,
    negotiate,
)

LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
# Must comfortably exceed the host heartbeat interval: a silent gap longer
# than this means the host really is gone, not merely thinking.
READ_TIMEOUT = 30.0
HEALTH_TIMEOUT = 3.0

UNLOADED_MODE = "未连接"


class RemoteError(RuntimeError):
    """A remote request failed. The message is safe to show to the user.

    Deriving from :class:`RuntimeError` matters: both the capture pipeline and
    the manual translation controller show ``RuntimeError`` messages verbatim
    and replace anything else with a generic string.
    """


@dataclass(frozen=True)
class RemoteHealth:
    """Last known state of the host, refreshed off the UI thread."""

    reachable: bool = False
    ready: bool = False
    device: str = UNLOADED_MODE
    model_id: str = ""
    busy: bool = False
    detail: str = "尚未连接到远程主机"
    #: The version both ends settled on, 0 while unreachable.
    protocol: int = 0

    def describe(self) -> str:
        if not self.reachable:
            return f"远程主机不可用：{self.detail}"
        if not self.ready:
            return f"远程主机未就绪：{self.detail}"
        return f"远程 {self.device} · {self.model_id}"


def encode_image(array: object) -> bytes:
    """Encode a BGR array as lossless PNG.

    Lossy compression is not an option here: OCR accuracy on small glyphs is
    exactly what a quality setting would trade away, and a cropped selection
    is small enough that the saving would not matter.
    """
    import cv2

    success, buffer = cv2.imencode(".png", array)
    if not success:
        raise RemoteError("截图编码失败")
    data = buffer.tobytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise RemoteError("选区过大，无法发送到远程主机")
    return data


class RemoteEndpoint:
    """HTTP transport for one host: auth, framing, cancellation, errors."""

    def __init__(self, base_url: str, secret: str, *, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("远程主机地址不能为空")
        self._secret = secret
        self._session = session or requests.Session()
        # Never let a system proxy intercept tailnet traffic.
        self._session.trust_env = False

    def close(self) -> None:
        self._session.close()

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._secret}",
            "X-Protocol-Version": str(PROTOCOL_VERSION),
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    @staticmethod
    def _describe_status(status: int) -> str:
        if status in (401, 403):
            return "远程主机拒绝了密钥或设备，请检查配对密钥和设备白名单"
        if status == 404:
            return "远程主机不支持该接口，请确认两端版本一致"
        if status == 409:
            return "远程主机正忙，请稍后再试"
        if status == 413:
            return "请求超出远程主机的大小上限"
        return f"远程主机返回错误（HTTP {status}）"

    def _describe_failure(self, response: requests.Response) -> str:
        """Prefer the host's own explanation over a bare status code.

        A protocol-version mismatch, for instance, is a 400 whose body names
        both versions; reducing that to "HTTP 400" would waste the one piece
        of information the user needs.
        """
        fallback = self._describe_status(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            return fallback
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            detail = payload["error"].strip()[:200]
            if detail:
                return detail
        return fallback

    def health(self) -> RemoteHealth:
        """Ask the host how it is doing. Never raises."""
        try:
            response = self._session.get(
                f"{self.base_url}/v1/health",
                headers=self._headers(),
                timeout=HEALTH_TIMEOUT,
            )
        except requests.RequestException as error:
            return RemoteHealth(detail=f"无法连接（{type(error).__name__}）")
        if not response.ok:
            return RemoteHealth(detail=self._describe_failure(response))
        try:
            payload = response.json()
        except ValueError:
            return RemoteHealth(detail="返回内容不是合法 JSON")
        if not isinstance(payload, dict):
            return RemoteHealth(detail="返回内容格式错误")
        # A host advertises everything it speaks; a v1 host advertises only
        # "protocol". Take the best the two have in common rather than
        # demanding equality, which is what made any version bump a flag
        # day for both ends at once.
        offered = payload.get("protocols") or [payload.get("protocol")]
        agreed = max(
            (version for version in (negotiate(item) for item in offered) if version),
            default=None,
        )
        if agreed is None:
            return RemoteHealth(
                reachable=True,
                detail=describe_version_mismatch(payload.get("protocol")),
            )
        return RemoteHealth(
            reachable=True,
            protocol=agreed,
            ready=bool(payload.get("ready")),
            device=str(payload.get("device") or UNLOADED_MODE),
            model_id=str(payload.get("model_id") or ""),
            busy=bool(payload.get("busy")),
            detail=str(payload.get("detail") or ""),
        )

    def stream(
        self,
        path: str,
        token: CancellationToken,
        progress,
        *,
        json_body: object = None,
        data: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Run one streaming request and return its result event.

        Cancellation works by closing the socket: the token is checked on
        every frame including heartbeats, and the host treats a failed write
        as a cancellation.
        """
        headers = self._headers(content_type)
        headers.update(extra_headers or {})
        try:
            with self._session.post(
                f"{self.base_url}{path}",
                headers=headers,
                json=json_body,
                data=data,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as response:
                if not response.ok:
                    raise RemoteError(self._describe_failure(response))
                for event in iter_events(response.iter_lines(chunk_size=1)):
                    token.check()
                    if event is None:
                        continue
                    kind = event.get("type")
                    if kind == EVENT_PROGRESS:
                        progress(str(event.get("text", "")))
                    elif kind == EVENT_ERROR:
                        raise RemoteError(str(event.get("message") or "远程处理失败"))
                    elif kind == EVENT_RESULT:
                        return event
        except requests.RequestException as error:
            raise RemoteError(f"与远程主机的连接中断（{type(error).__name__}）") from error
        except ProtocolError as error:
            raise RemoteError(f"远程主机返回了无法解析的数据：{error}") from error
        raise RemoteError("远程主机在返回结果前关闭了连接")


class RemoteOcrEngine:
    """``OcrPort`` backed by the host's PaddleOCR installation."""

    def __init__(self, endpoint: RemoteEndpoint, health: RemoteHealthCache):
        self._endpoint = endpoint
        self._health = health

    @property
    def mode(self) -> str:
        return self._health.current.device if self._health.current.reachable else UNLOADED_MODE

    def ready(self) -> bool:
        return self._health.current.ready

    def warmup(self, source_language: str, token: CancellationToken, progress) -> None:
        self._endpoint.stream(
            "/v1/warmup",
            token,
            progress,
            json_body={"scope": "ocr", "source_language": source_language},
        )
        self._health.refresh()

    def recognize(self, image, source_language: str, token: CancellationToken, progress) -> OcrResult:
        event = self._endpoint.stream(
            "/v1/ocr",
            token,
            progress,
            data=encode_image(image),
            content_type="image/png",
            extra_headers={"X-Source-Language": source_language},
        )
        try:
            return decode_ocr_result(event.get("value"))
        except ProtocolError as error:
            raise RemoteError(f"远程识别结果无法解析：{error}") from error


class RemoteTranslationEngine:
    """``TranslationPort`` backed by the host's llama.cpp server."""

    def __init__(self, endpoint: RemoteEndpoint, health: RemoteHealthCache):
        self._endpoint = endpoint
        self._health = health
        self.last_metrics: dict[str, object] = {}

    @property
    def mode(self) -> str:
        return self._health.current.device if self._health.current.reachable else UNLOADED_MODE

    def ready(self) -> bool:
        return self._health.current.ready

    def start(self, token: CancellationToken, progress) -> None:
        self._endpoint.stream(
            "/v1/warmup",
            token,
            progress,
            json_body={"scope": "translation", "source_language": "auto"},
        )
        self._health.refresh()

    def stop(self) -> None:
        """Intentionally a no-op.

        The host owns its model lifecycle and may be serving its own user or
        another device; a client must never unload weights it does not own.
        """

    def translate(
        self,
        blocks: Sequence[TextBlock],
        token: CancellationToken,
        progress,
        source_language: str = "auto",
        target_language: str = "zh-Hans",
        detected_language: str | None = None,
    ) -> list[TranslatedBlock]:
        blocks = list(blocks)
        if not blocks:
            return []
        event = self._endpoint.stream(
            "/v1/translate",
            token,
            progress,
            json_body=encode_translation_request(
                blocks, source_language, target_language, detected_language
            ),
        )
        try:
            values = decode_translation_result(
                event.get("value"), [block.block_id for block in blocks]
            )
        except ProtocolError as error:
            raise RemoteError(f"远程译文无法解析：{error}") from error
        metrics = event.get("metrics")
        self.last_metrics = dict(metrics) if isinstance(metrics, dict) else {}
        return apply_translation(blocks, values)


class RemoteHealthCache:
    """Health readable from the UI thread, written by background refreshes.

    ``ready()`` is polled whenever the user presses the hotkey, so it must
    never block on the network; the cached snapshot is replaced wholesale
    under a lock rather than mutated field by field.
    """

    def __init__(self, endpoint: RemoteEndpoint):
        self._endpoint = endpoint
        self._lock = threading.Lock()
        self._state = RemoteHealth()

    @property
    def current(self) -> RemoteHealth:
        with self._lock:
            return self._state

    def refresh(self) -> RemoteHealth:
        state = self._endpoint.health()
        with self._lock:
            self._state = state
        return state

    def mark_unreachable(self, detail: str) -> None:
        with self._lock:
            self._state = replace(self._state, reachable=False, ready=False, detail=detail)


class RemoteBackend:
    """A host reachable over the tailnet, presented as one replaceable unit."""

    kind = "remote"

    def __init__(self, base_url: str, secret: str, *, session: requests.Session | None = None):
        self._endpoint = RemoteEndpoint(base_url, secret, session=session)
        self.health = RemoteHealthCache(self._endpoint)
        self.ocr = RemoteOcrEngine(self._endpoint, self.health)
        self.translator = RemoteTranslationEngine(self._endpoint, self.health)

    def ready(self) -> bool:
        return self.health.current.ready

    def refresh(self) -> None:
        self.health.refresh()

    def describe(self) -> str:
        return self.health.current.describe()

    def stop(self) -> None:
        self._endpoint.close()
