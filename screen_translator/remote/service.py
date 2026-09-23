"""Host side of cross-device translation.

Layering inside this module mirrors the rest of the application:
:class:`TranslationService` is the use-case layer and knows nothing about
HTTP, ``_Handler`` is the transport, and :class:`RemoteService` owns the
lifecycle as an explicit state machine.  Only the transport touches sockets,
so the interesting behaviour stays unit-testable without a server.

The service runs inside the desktop process on purpose.  A separate headless
process would need its own copy of the weights, and two llama.cpp servers do
not fit in one GPU; sharing the process means remote work goes through the
same :class:`~screen_translator.inference.InferenceCoordinator` slot as the
host user's own captures.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..contracts import OcrPort
from ..core import CancellationToken, Cancelled
from ..inference import REMOTE, InferenceBusy, InferenceCoordinator
from ..tasks import TaskRunner
from ..version import __version__
from .access import AccessDenied, AccessPolicy, is_loopback_address, is_tailnet_address
from .pairing import REJECTION_MESSAGE as PAIRING_REJECTION
from .pairing import (
    PairingBroker,
    PairingError,
    PairingGrant,
    decode_claim,
)
from .protocol import (
    EVENT_ERROR,
    EVENT_PROGRESS,
    EVENT_RESULT,
    MAX_CLAIM_BYTES,
    MAX_IMAGE_BYTES,
    PAIR_CLAIM_PATH,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    ProtocolError,
    decode_translation_request,
    describe_version_mismatch,
    encode_event,
    encode_ocr_result,
    encode_translation_result,
    heartbeat,
    negotiate,
)
from .tailnet import TailnetUnavailable, discover_address

LOGGER = logging.getLogger(__name__)
PERFORMANCE_LOGGER = logging.getLogger("screen_translator.performance")

HEARTBEAT_INTERVAL = 0.5
WARMUP_TIMEOUT = 300.0
OCR_TIMEOUT = 120.0
TRANSLATE_TIMEOUT = 600.0
# A short overlap with the host user's own work should queue rather than fail;
# a long one should fail clearly instead of stalling the remote device.
SLOT_WAIT = 15.0

DEFAULT_PORT = 8765
AUTO_ADDRESS = "auto"

# Deliberately uniform for every rejection reason; see ``_Handler._authorize``.
REJECTION_MESSAGE = "远程主机拒绝了该请求，请检查配对密钥和设备白名单"


class ServiceState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(frozen=True)
class ServiceStatus:
    state: ServiceState = ServiceState.STOPPED
    address: str = ""
    port: int = 0
    detail: str = "远程服务未启用"

    @property
    def url(self) -> str:
        return f"http://{self.address}:{self.port}" if self.state == ServiceState.RUNNING else ""

    def describe(self) -> str:
        if self.state == ServiceState.RUNNING:
            return f"正在监听 {self.address}:{self.port}"
        return self.detail


def decode_image(data: bytes):
    """Decode a PNG upload into the BGR array the OCR engine expects."""
    import cv2
    import numpy as np

    array = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        raise ProtocolError("上传的图片无法解码")
    return array


class TranslationService:
    """Execute one remote request against the host's local engines.

    Engines are reached through providers rather than held directly, because
    changing the model in settings replaces them while the service keeps
    running.
    """

    def __init__(
        self,
        *,
        ocr_provider: Callable[[], OcrPort],
        inference: InferenceCoordinator,
        ready_provider: Callable[[], bool],
        model_provider: Callable[[], str],
    ):
        self._ocr_provider = ocr_provider
        self._inference = inference
        self._ready_provider = ready_provider
        self._model_provider = model_provider

    def health(self) -> dict[str, object]:
        ready = bool(self._ready_provider())
        return {
            "protocol": PROTOCOL_VERSION,
            # A v1 client reads only "protocol" and demands equality, so it
            # will refuse a v2 host -- that is the version skew this list
            # lets a v2 client survive.
            "protocols": list(SUPPORTED_PROTOCOL_VERSIONS),
            "version": __version__,
            "ready": ready,
            "device": self._ocr_provider().mode,
            "model_id": self._model_provider(),
            "busy": self._inference.capture_active or self._inference.owner is not None,
            "detail": "" if ready else "主机模型尚未就绪",
        }

    def _require_ready(self) -> None:
        if not self._ready_provider():
            raise RuntimeError("远程主机的模型尚未就绪")

    def warmup(self, payload: object, token: CancellationToken, progress) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ProtocolError("预热请求必须是对象")
        scope = payload.get("scope")
        if scope not in ("ocr", "translation"):
            raise ProtocolError("scope 必须是 ocr 或 translation")
        source_language = payload.get("source_language", "auto")
        if not isinstance(source_language, str):
            raise ProtocolError("source_language 必须是字符串")
        self._require_ready()
        if scope == "ocr":
            self._ocr_provider().warmup(source_language, token, progress)
            return {"value": {"scope": scope}}
        # Loading weights can take minutes, so warm-up never blocks the slot
        # away from an interactive capture; it only runs when nothing owns it.
        if self._inference.owner is not None:
            return {"value": {"scope": scope, "skipped": "busy"}}
        with self._inference.reserve(REMOTE, timeout=SLOT_WAIT) as port:
            port.start(token, progress)
        return {"value": {"scope": scope}}

    def recognize(
        self, image_bytes: bytes, source_language: str, token: CancellationToken, progress
    ) -> dict[str, object]:
        self._require_ready()
        engine = self._ocr_provider()
        started = time.monotonic()
        result = engine.recognize(decode_image(image_bytes), source_language, token, progress)
        PERFORMANCE_LOGGER.info(
            "Remote OCR bytes=%d lines=%d device=%s elapsed_ms=%.1f",
            len(image_bytes),
            len(result.lines),
            result.device,
            (time.monotonic() - started) * 1000,
        )
        return {"value": encode_ocr_result(result), "device": result.device}

    def translate(self, payload: object, token: CancellationToken, progress) -> dict[str, object]:
        request = decode_translation_request(payload)
        self._require_ready()
        blocks = request["blocks"]
        started = time.monotonic()
        with self._inference.reserve(REMOTE, timeout=SLOT_WAIT) as port:
            token.check()
            translated = port.translate(
                blocks,
                token,
                progress,
                request["source_language"],
                request["target_language"],
                request["detected_language"],
            )
            device = getattr(port, "mode", "未知")
            metrics = dict(getattr(port, "last_metrics", {}) or {})
        PERFORMANCE_LOGGER.info(
            "Remote translation blocks=%d batches=%d retries=%d device=%s elapsed_ms=%.1f",
            len(blocks),
            metrics.get("batches", 0),
            metrics.get("quality_retries", 0),
            device,
            (time.monotonic() - started) * 1000,
        )
        return {
            "value": encode_translation_result(translated),
            "metrics": metrics,
            "device": device,
        }


def stream_work(
    work: Callable[[CancellationToken, Callable[[str], None]], dict[str, object]],
    write: Callable[[bytes], bool],
    tasks: TaskRunner,
    *,
    name: str,
    timeout: float,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
) -> str:
    """Run ``work`` on a worker thread while the caller streams events.

    Returns a status string for logging.  The split exists so the connection
    keeps producing heartbeats during model inference, which emits no progress
    for seconds at a time; a failed write is how a client pressing Esc becomes
    a cancelled token on this side.
    """
    token = CancellationToken()
    events: queue.Queue[tuple[str, object]] = queue.Queue()

    def worker() -> None:
        try:
            events.put((EVENT_RESULT, work(token, lambda text: events.put((EVENT_PROGRESS, text)))))
        except Cancelled:
            events.put((EVENT_ERROR, "已取消"))
        except InferenceBusy as error:
            events.put((EVENT_ERROR, str(error)))
        except (ProtocolError, RuntimeError) as error:
            events.put((EVENT_ERROR, str(error)))
        except Exception as error:
            LOGGER.exception("Remote request failed: %s", name)
            events.put((EVENT_ERROR, f"远程处理失败（{type(error).__name__}）"))

    tasks.start(worker, name=name)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            token.cancel()
            write(encode_event(EVENT_ERROR, message="远程处理超时"))
            return "timeout"
        try:
            kind, payload = events.get(timeout=min(heartbeat_interval, remaining))
        except queue.Empty:
            if not write(heartbeat()):
                token.cancel()
                return "disconnected"
            continue
        if kind == EVENT_PROGRESS:
            if not write(encode_event(EVENT_PROGRESS, text=str(payload))):
                token.cancel()
                return "disconnected"
            continue
        if kind == EVENT_ERROR:
            write(encode_event(EVENT_ERROR, message=str(payload)))
            return "error"
        assert isinstance(payload, dict)
        write(encode_event(EVENT_RESULT, **payload))
        return "ok"


@dataclass
class ServiceContext:
    """Everything a request handler is allowed to reach."""

    service: TranslationService
    policy: AccessPolicy
    tasks: TaskRunner
    request_id: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    #: The pairing window, when one is open. Held in the process rather
    #: than exposed as an endpoint: a `/v1/pair/status` route would let
    #: anyone on the tailnet ask whether the host is currently pairing.
    broker: PairingBroker = field(default_factory=PairingBroker)
    #: Called with a fresh grant so the host can persist it. Set by the
    #: owner; the transport never touches configuration.
    on_paired: Callable[[PairingGrant, str], None] = lambda _grant, _peer: None

    def next_request_id(self) -> int:
        with self.lock:
            self.request_id += 1
            return self.request_id


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ScreenTranslator"
    sys_version = ""

    @property
    def context(self) -> ServiceContext:
        return self.server.context  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        """Replace the default stderr access log.

        It is noisy, it bypasses the application's rotating privacy-scoped log
        file, and the handler already logs the one line per request that
        matters.
        """
        LOGGER.debug("http %s", fmt % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _begin_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Protocol-Version", str(PROTOCOL_VERSION))
        # Close-delimited: the body length is unknown until the work finishes.
        self.send_header("Connection", "close")
        self.end_headers()

    def _write(self, frame: bytes) -> bool:
        try:
            self.wfile.write(frame)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            return False
        return True

    def _drain_body(self, limit: int = 64 * 1024) -> None:
        """Consume a bounded part of a rejected request body.

        Without this the peer usually sees a connection reset instead of the
        403 it needs to read.  The cap is what keeps an unauthenticated peer
        from making the host buffer a full-size upload.
        """
        try:
            length = min(int(self.headers.get("Content-Length", "0")), limit)
        except ValueError:
            return
        if length > 0:
            self.rfile.read(length)

    def _authorize(self) -> bool:
        peer = self.client_address[0]
        try:
            self.context.policy.authorize(peer, self.headers.get("Authorization"))
        except AccessDenied as error:
            # The precise reason stays in the host's own log. Telling the peer
            # whether it failed the allow-list or the secret would confirm
            # which of the two it already got right.
            LOGGER.warning("Rejected remote request from %s: %s", peer, error)
            self._drain_body()
            self._send_json(HTTPStatus.FORBIDDEN, {"error": REJECTION_MESSAGE})
            return False
        version = self.headers.get("X-Protocol-Version")
        agreed = negotiate(version)
        if agreed is None:
            self._drain_body()
            self._send_json(
                HTTPStatus.BAD_REQUEST, {"error": describe_version_mismatch(version)}
            )
            return False
        # Kept for handlers that need to know what the peer can read back.
        self.agreed_version = agreed
        return True

    def _read_body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length 无效"})
            return None
        if length > limit:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "请求体过大"})
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:
        if not self._authorize():
            return
        if self.path != "/v1/health":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "未知接口"})
            return
        self._send_json(HTTPStatus.OK, self.context.service.health())

    def _handle_pair_claim(self) -> None:
        """The one route that runs without a secret, because it issues one.

        The address check still applies, so the caller is already inside
        the tailnet. The body is capped far below anything else here: a
        claim is two short strings, and this is the only place an
        unauthenticated peer can make the host read at all.
        """
        peer = self.client_address[0]
        body = self._read_body(MAX_CLAIM_BYTES)
        if body is None:
            return
        try:
            self.context.policy.admit(peer)
            payload = json.loads(body.decode("utf-8"))
            fields = decode_claim(payload)
            # Ask before claiming: a retransmitted claim returns a grant
            # indistinguishable from a fresh one, so afterwards is too late.
            replayed = self.context.broker.already_granted(fields["nonce"], peer)
            grant = self.context.broker.claim(
                code=fields["code"],
                nonce=fields["nonce"],
                peer=peer,
                label=fields["label"],
                protocol=getattr(self, "agreed_version", PROTOCOL_VERSION),
            )
        except AccessDenied as error:
            LOGGER.warning("Rejected pairing from %s: %s", peer, error)
            self._send_json(HTTPStatus.FORBIDDEN, {"error": REJECTION_MESSAGE})
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Deliberately the pairing rejection, not "bad JSON": the shape
            # of the failure must not say whether an offer is even open.
            self._send_json(HTTPStatus.FORBIDDEN, {"error": PAIRING_REJECTION})
            return
        except PairingError as error:
            LOGGER.warning("Rejected pairing from %s: %s", peer, error.reason)
            self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
            return
        if replayed:
            # The peer never received the first reply. Send it again and
            # stop there: this is one pairing, not two.
            LOGGER.info("Re-sent grant id=%s to %s", grant.device_id, peer)
            self._send_json(HTTPStatus.OK, grant.to_payload())
            return
        LOGGER.info("Paired device id=%s peer=%s", grant.device_id, peer)
        # Reply first: persisting the grant is the host's own business and
        # must not delay the answer the peer is waiting on.
        self._send_json(HTTPStatus.OK, grant.to_payload())
        self.context.on_paired(grant, peer)

    def do_POST(self) -> None:
        if self.path == PAIR_CLAIM_PATH:
            # Before `_authorize`: the caller cannot have a secret yet,
            # which is the entire point of the route.
            if negotiate(self.headers.get("X-Protocol-Version")) is None:
                self._drain_body()
                self._send_json(HTTPStatus.FORBIDDEN, {"error": PAIRING_REJECTION})
                return
            self.agreed_version = negotiate(self.headers.get("X-Protocol-Version"))
            self._handle_pair_claim()
            return
        if not self._authorize():
            return
        routes = {
            "/v1/warmup": (self._json_work, WARMUP_TIMEOUT),
            "/v1/translate": (self._json_work, TRANSLATE_TIMEOUT),
            "/v1/ocr": (self._image_work, OCR_TIMEOUT),
        }
        route = routes.get(self.path)
        if route is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "未知接口"})
            return
        build, timeout = route
        work = build()
        if work is None:
            return
        request_id = self.context.next_request_id()
        started = time.monotonic()
        self._begin_stream()
        status = stream_work(
            work,
            self._write,
            self.context.tasks,
            name=f"remote-{self.path.rsplit('/', 1)[-1]}-{request_id}",
            timeout=timeout,
        )
        self.close_connection = True
        LOGGER.info(
            "Remote request id=%d path=%s peer=%s status=%s elapsed_ms=%.1f",
            request_id,
            self.path,
            self.client_address[0],
            status,
            (time.monotonic() - started) * 1000,
        )

    def _json_work(self):
        body = self._read_body(2 * MAX_IMAGE_BYTES)
        if body is None:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "请求体不是合法 JSON"})
            return None
        service = self.context.service
        if self.path == "/v1/warmup":
            return lambda token, progress: service.warmup(payload, token, progress)
        return lambda token, progress: service.translate(payload, token, progress)

    def _image_work(self):
        body = self._read_body(MAX_IMAGE_BYTES)
        if body is None:
            return None
        if not body:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "缺少图片数据"})
            return None
        language = self.headers.get("X-Source-Language", "auto")
        service = self.context.service
        return lambda token, progress: service.recognize(body, language, token, progress)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], context: ServiceContext):
        self.context = context
        super().__init__(address, _Handler)


def resolve_bind_address(configured: str) -> str:
    """Resolve the address to listen on, refusing to expose the host widely.

    ``0.0.0.0`` is never acceptable here: the point of binding the Tailscale
    address is that the port does not appear on whatever café Wi-Fi the host
    is also attached to.
    """
    configured = (configured or AUTO_ADDRESS).strip()
    if configured == AUTO_ADDRESS:
        return discover_address()
    if not is_tailnet_address(configured) and not is_loopback_address(configured):
        raise TailnetUnavailable(f"{configured} 不是 Tailscale 地址，拒绝在该地址上监听")
    return configured


class RemoteService:
    """Lifecycle of the host listener as an explicit state machine."""

    def __init__(
        self,
        service: TranslationService,
        policy: AccessPolicy,
        tasks: TaskRunner,
        *,
        address: str = AUTO_ADDRESS,
        port: int = DEFAULT_PORT,
        on_paired: Callable[[PairingGrant, str], None] | None = None,
    ):
        self._context = ServiceContext(
            service=service,
            policy=policy,
            tasks=tasks,
            on_paired=on_paired or (lambda _grant, _peer: None),
        )
        self._tasks = tasks
        self._address = address
        self._port = port
        self._server: _Server | None = None
        self._lock = threading.Lock()
        self._status = ServiceStatus()

    @property
    def status(self) -> ServiceStatus:
        with self._lock:
            return self._status

    @property
    def broker(self) -> PairingBroker:
        """The pairing window, read directly by the host's own UI.

        In-process rather than behind an endpoint: a `/v1/pair/status`
        route would let anyone on the tailnet ask whether this host is
        currently pairing, which is one more thing to probe for nothing.
        """
        return self._context.broker

    def set_device_secrets(self, devices) -> None:
        """Replace the per-device credentials without restarting the listener."""
        self._context.policy = replace(
            self._context.policy,
            device_secrets=tuple((item.device_id, item.secret) for item in devices),
        )

    def _set_status(self, status: ServiceStatus) -> None:
        with self._lock:
            self._status = status

    def _fail(self, detail: str) -> ServiceStatus:
        LOGGER.warning("Remote service failed to start: %s", detail)
        self._set_status(ServiceStatus(ServiceState.FAILED, detail=detail))
        return self.status

    def start(self) -> ServiceStatus:
        with self._lock:
            if self._server is not None:
                return self._status
            self._status = ServiceStatus(ServiceState.STARTING, detail="正在启动远程服务…")
        try:
            self._context.policy.validate()
            bind_address = resolve_bind_address(self._address)
            server = _Server((bind_address, self._port), self._context)
        except (TailnetUnavailable, ValueError) as error:
            return self._fail(str(error))
        except OSError as error:
            return self._fail(f"无法监听 {self._address}:{self._port}（{type(error).__name__}）")
        # Report the port the kernel actually gave us, which differs from the
        # requested one when the caller asked for an ephemeral port.
        bound_port = server.server_address[1]
        # Only now is the bound address known, and the policy needs it to
        # recognise the host talking to its own service: those packets carry
        # the tailnet address, not 127.0.0.1, and would otherwise be refused
        # by the host's own device allow-list.
        self._context.policy = replace(self._context.policy, local_address=bind_address)
        with self._lock:
            self._server = server
            self._status = ServiceStatus(
                ServiceState.RUNNING, bind_address, bound_port, "远程服务已启动"
            )
        self._tasks.start(server.serve_forever, name="remote-service")
        LOGGER.info("Remote service listening on %s:%d", bind_address, bound_port)
        return self.status

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._set_status(ServiceStatus(detail="远程服务已停止"))

    def self_check(self, timeout: float = 2.0) -> bool:
        """Confirm the listener actually accepts connections."""
        status = self.status
        if status.state != ServiceState.RUNNING:
            return False
        try:
            with socket.create_connection((status.address, status.port), timeout=timeout):
                return True
        except OSError:
            return False
