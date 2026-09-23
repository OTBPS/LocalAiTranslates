import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from screen_translator.core import Cancelled, Config, OcrLine, OcrResult, TranslatedBlock
from screen_translator.inference import REMOTE, InferenceBusy, InferenceCoordinator
from screen_translator.remote.access import AccessPolicy
from screen_translator.remote.host import HostService
from screen_translator.remote.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    encode_translation_request,
    rebuild_block,
)
from screen_translator.remote.service import (
    ServiceState,
    ServiceStatus,
    TranslationService,
    resolve_bind_address,
    stream_work,
)
from screen_translator.remote.tailnet import TailnetUnavailable
from screen_translator.tasks import TaskRunner

SECRET = "s" * 32


class FakePort:
    mode = "CUDA"
    last_metrics = {"batches": 2}

    def __init__(self, behaviour=None):
        self.behaviour = behaviour

    def start(self, token, progress):
        progress("正在加载模型…")

    def stop(self):
        pass

    def translate(self, blocks, token, progress, source, target, detected):
        if self.behaviour:
            self.behaviour(blocks, token, progress)
        return [TranslatedBlock(block, f"译{block.text}") for block in blocks]


class FakeOcr:
    mode = "CUDA"

    def __init__(self):
        self.warmups = []

    def ready(self):
        return True

    def warmup(self, source_language, token, progress):
        self.warmups.append(source_language)

    def recognize(self, image, source_language, token, progress):
        progress("正在识别文字…")
        return OcrResult(
            [OcrLine([(0, 0), (8, 0), (8, 8), (0, 8)], "Hello", 0.9)], "en", "CUDA", {"total": 1.0}
        )


def build_service(port=None, ocr=None, ready=True):
    arbiter = InferenceCoordinator(lambda: port or FakePort())
    service = TranslationService(
        ocr_provider=lambda: ocr or FakeOcr(),
        inference=arbiter,
        ready_provider=lambda: ready,
        model_provider=lambda: "qwen3-14b-q5-k-m",
    )
    return service, arbiter


def collector():
    frames = []

    def write(frame):
        frames.append(frame)
        return True

    return frames, write


def test_health_reports_protocol_model_and_device():
    service, _arbiter = build_service()

    health = service.health()

    assert health["protocol"] == PROTOCOL_VERSION
    # Everything this host will also speak, so a client one version behind
    # can settle on a common one instead of refusing outright.
    assert health["protocols"] == list(SUPPORTED_PROTOCOL_VERSIONS)
    assert 1 in health["protocols"], "v0.7.0 clients must keep working"
    assert health["ready"] is True
    assert health["device"] == "CUDA"
    assert health["model_id"] == "qwen3-14b-q5-k-m"
    assert health["busy"] is False


def test_health_reports_not_ready_without_claiming_a_device_is_missing():
    service, _arbiter = build_service(ready=False)

    health = service.health()

    assert health["ready"] is False
    assert health["detail"]


def test_translate_returns_values_metrics_and_device():
    service, _arbiter = build_service()
    payload = encode_translation_request([rebuild_block("b1", "Hello")], "en", "zh-Hans", "en")

    result = service.translate(payload, _token(), lambda _text: None)

    assert result["value"] == {"b1": "译Hello"}
    assert result["metrics"] == {"batches": 2}
    assert result["device"] == "CUDA"


def test_translate_holds_the_shared_inference_slot():
    observed = {}

    def behaviour(_blocks, _token, _progress):
        observed["owner"] = arbiter.owner

    service, arbiter = build_service(FakePort(behaviour))
    payload = encode_translation_request([rebuild_block("b1", "Hello")], "en", "zh-Hans", None)

    service.translate(payload, _token(), lambda _text: None)

    assert observed["owner"] == REMOTE
    assert arbiter.owner is None


def test_a_local_capture_preempts_remote_work():
    service, arbiter = build_service()
    arbiter.begin_capture()
    payload = encode_translation_request([rebuild_block("b1", "Hello")], "en", "zh-Hans", None)

    with pytest.raises(InferenceBusy):
        service.translate(payload, _token(), lambda _text: None)


def test_requests_are_refused_while_the_host_models_are_not_ready():
    service, _arbiter = build_service(ready=False)
    payload = encode_translation_request([rebuild_block("b1", "Hello")], "en", "zh-Hans", None)

    with pytest.raises(RuntimeError, match="尚未就绪"):
        service.translate(payload, _token(), lambda _text: None)
    with pytest.raises(RuntimeError, match="尚未就绪"):
        service.recognize(b"", "auto", _token(), lambda _text: None)


def test_ocr_warmup_is_forwarded_with_the_requested_language():
    ocr = FakeOcr()
    service, _arbiter = build_service(ocr=ocr)

    service.warmup({"scope": "ocr", "source_language": "ja"}, _token(), lambda _text: None)

    assert ocr.warmups == ["ja"]


def test_translation_warmup_is_skipped_rather_than_queued_when_the_slot_is_taken():
    service, arbiter = build_service()
    with arbiter.reserve(REMOTE):
        result = service.warmup({"scope": "translation"}, _token(), lambda _text: None)

    assert result["value"]["skipped"] == "busy"


def test_an_unknown_warmup_scope_is_rejected():
    service, _arbiter = build_service()

    with pytest.raises(ValueError):
        service.warmup({"scope": "everything"}, _token(), lambda _text: None)


def _token():
    from screen_translator.core import CancellationToken

    return CancellationToken()


def test_stream_emits_progress_then_result():
    frames, write = collector()

    def work(_token, progress):
        progress("第一步")
        return {"value": {"b1": "你好"}}

    status = stream_work(work, write, TaskRunner(), name="t", timeout=5)

    assert status == "ok"
    body = b"".join(frames)
    assert b'"type":"progress"' in body
    assert body.index(b"progress") < body.index(b"result")


def test_a_client_that_disconnects_cancels_the_work():
    cancelled = threading.Event()
    released = threading.Event()

    def work(token, _progress):
        released.wait(3)
        while not token.event.is_set():
            time.sleep(0.01)
        cancelled.set()
        raise Cancelled()

    def write(_frame):
        released.set()
        return False  # the socket is gone

    status = stream_work(work, write, TaskRunner(), name="t", timeout=5, heartbeat_interval=0.01)

    assert status == "disconnected"
    assert cancelled.wait(3)


def test_a_slow_task_keeps_the_connection_alive_with_heartbeats():
    frames, write = collector()

    def work(_token, _progress):
        time.sleep(0.2)
        return {"value": {}}

    stream_work(work, write, TaskRunner(), name="t", timeout=5, heartbeat_interval=0.02)

    assert frames.count(b": ping\n\n") >= 2


def test_work_that_overruns_its_deadline_is_cancelled_and_reported():
    frames, write = collector()
    seen = threading.Event()

    def work(token, _progress):
        while not token.event.is_set():
            time.sleep(0.01)
        seen.set()
        raise Cancelled()

    status = stream_work(work, write, TaskRunner(), name="t", timeout=0.1, heartbeat_interval=0.02)

    assert status == "timeout"
    assert "超时" in b"".join(frames).decode("utf-8")
    assert seen.wait(3)


def test_an_unexpected_failure_becomes_an_error_event_without_a_traceback():
    frames, write = collector()

    def work(_token, _progress):
        raise KeyError("internal detail")

    status = stream_work(work, write, TaskRunner(), name="t", timeout=5)

    body = b"".join(frames).decode("utf-8")
    assert status == "error"
    assert "KeyError" in body
    assert "internal detail" not in body
    assert "Traceback" not in body


def test_a_busy_slot_becomes_a_readable_error_event():
    frames, write = collector()

    def work(_token, _progress):
        raise InferenceBusy("截图翻译正在进行，请稍后再试")

    stream_work(work, write, TaskRunner(), name="t", timeout=5)

    assert "截图翻译正在进行" in b"".join(frames).decode("utf-8")


def test_binding_is_restricted_to_tailnet_or_loopback_addresses():
    assert resolve_bind_address("127.0.0.1") == "127.0.0.1"
    assert resolve_bind_address("100.101.102.103") == "100.101.102.103"
    for rejected in ("0.0.0.0", "192.168.1.10", "8.8.8.8"):
        with pytest.raises(TailnetUnavailable):
            resolve_bind_address(rejected)


def host_service(**kwargs):
    started = []

    class FakeRemoteService:
        def __init__(self, _service, policy, _tasks, *, address, port, on_paired=None):
            self.policy = policy
            self.on_paired = on_paired
            self.address = address
            self.port = port
            self.stopped = False
            started.append(self)

        def start(self):
            self.status = ServiceStatus(ServiceState.RUNNING, self.address, self.port, "ok")
            return self.status

        def set_device_secrets(self, devices):
            self.device_secrets = tuple((d.device_id, d.secret) for d in devices)

        def stop(self):
            self.stopped = True

    service = HostService(
        ocr_provider=FakeOcr,
        ready_provider=lambda: True,
        model_provider=lambda: "qwen3-14b-q5-k-m",
        inference=InferenceCoordinator(FakePort),
        tasks=TaskRunner(),
        service_factory=FakeRemoteService,
        **kwargs,
    )
    return service, started


def enabled_config(**overrides):
    defaults = {
        "service_enabled": True,
        "service_token": SECRET,
        "service_address": "127.0.0.1",
        "service_port": 8765,
    }
    return replace(Config(), **{**defaults, **overrides})


def test_the_listener_starts_only_when_enabled_and_configured():
    service, started = host_service()

    assert service.apply(Config()).state == ServiceState.STOPPED
    assert service.apply(enabled_config(service_token="")).state == ServiceState.STOPPED
    assert started == []

    assert service.apply(enabled_config()).state == ServiceState.RUNNING
    assert started[0].port == 8765


def test_a_remote_client_refuses_to_also_act_as_a_host():
    service, started = host_service()

    status = service.apply(
        enabled_config(mode="remote", remote_url="http://100.64.0.1:8765", remote_token=SECRET)
    )

    assert status.state == ServiceState.STOPPED
    assert "无法同时作为主机" in status.detail
    assert started == []


def test_saving_unrelated_settings_does_not_restart_the_listener():
    service, started = host_service()
    service.apply(enabled_config())

    service.apply(enabled_config(hotkey="Ctrl+Alt+Y"))

    assert len(started) == 1
    assert started[0].stopped is False


def test_changing_the_port_restarts_the_listener():
    service, started = host_service()
    service.apply(enabled_config())

    service.apply(enabled_config(service_port=9000))

    assert len(started) == 2
    assert started[0].stopped is True
    assert started[1].port == 9000


def test_disabling_the_service_stops_the_listener():
    service, started = host_service()
    service.apply(enabled_config())

    status = service.apply(Config())

    assert started[0].stopped is True
    assert status.state == ServiceState.STOPPED
    assert service.status.state == ServiceState.STOPPED


def test_the_allow_list_reaches_the_policy():
    service, started = host_service()

    service.apply(enabled_config(service_allowed_peers=("100.101.102.103",)))

    assert started[0].policy == AccessPolicy(SECRET, frozenset({"100.101.102.103"}))


def test_service_status_describes_a_running_listener():
    status = ServiceStatus(ServiceState.RUNNING, "100.101.102.103", 8765, "ok")

    assert status.url == "http://100.101.102.103:8765"
    assert "100.101.102.103:8765" in status.describe()
    assert ServiceStatus().url == ""


def test_fake_namespace_ports_still_satisfy_the_service_contract():
    # Guards the provider indirection: swapping the model in settings replaces
    # the engines while the service object stays alive.
    engines = [FakeOcr(), FakeOcr()]
    current = SimpleNamespace(index=0)
    service = TranslationService(
        ocr_provider=lambda: engines[current.index],
        inference=InferenceCoordinator(FakePort),
        ready_provider=lambda: True,
        model_provider=lambda: "qwen3-14b-q5-k-m",
    )

    service.warmup({"scope": "ocr", "source_language": "en"}, _token(), lambda _t: None)
    current.index = 1
    service.warmup({"scope": "ocr", "source_language": "ja"}, _token(), lambda _t: None)

    assert engines[0].warmups == ["en"]
    assert engines[1].warmups == ["ja"]
