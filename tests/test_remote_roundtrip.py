"""End-to-end contract test over a real loopback HTTP server.

The fake engines stand in for PaddleOCR and llama.cpp; everything between the
client port implementations and the host request handler is the production
code path, including authentication, event framing, cancellation and error
mapping.
"""

import logging
import threading
import time

import numpy
import pytest

from screen_translator.core import (
    CancellationToken,
    Cancelled,
    OcrLine,
    OcrResult,
    TextBlock,
    TranslatedBlock,
)
from screen_translator.inference import InferenceCoordinator
from screen_translator.remote.access import AccessPolicy
from screen_translator.remote.client import RemoteBackend, RemoteError
from screen_translator.remote.service import (
    RemoteService,
    ServiceState,
    TranslationService,
)
from screen_translator.tasks import TaskRunner

SECRET = "s" * 32
OTHER_SECRET = "o" * 32


class FakeOcr:
    mode = "CUDA"

    def ready(self):
        return True

    def warmup(self, source_language, token, progress):
        progress("正在加载文字检测模型…")

    def recognize(self, image, source_language, token, progress):
        progress("正在识别文字…")
        height, width = image.shape[:2]
        return OcrResult(
            [
                OcrLine([(1, 2), (width - 1, 2), (width - 1, 20), (1, 20)], "Hello", 0.93, "en"),
                OcrLine([(1, 24), (width - 1, 24), (width - 1, 42), (1, 42)], "World", 0.81, "en"),
            ],
            "en",
            "CUDA",
            {"total": float(height)},
        )


class FakeTranslator:
    mode = "CUDA"
    last_metrics = {"batches": 1, "quality_retries": 0}

    def __init__(self, behaviour=None):
        self.behaviour = behaviour
        self.seen = []

    def ready(self):
        return True

    def start(self, token, progress):
        progress("正在加载模型…")

    def stop(self):
        pass

    def translate(self, blocks, token, progress, source, target, detected):
        self.seen.append((source, target, detected, [block.text for block in blocks]))
        if self.behaviour:
            self.behaviour(token, progress)
        progress("正在翻译 1/1 · CUDA")
        return [TranslatedBlock(block, f"译[{block.text}]") for block in blocks]


class Host:
    def __init__(self, translator=None, ready=True, secret=SECRET):
        self.tasks = TaskRunner()
        self.ocr = FakeOcr()
        self.translator = translator or FakeTranslator()
        self.inference = InferenceCoordinator(lambda: self.translator)
        service = TranslationService(
            ocr_provider=lambda: self.ocr,
            inference=self.inference,
            ready_provider=lambda: ready,
            model_provider=lambda: "qwen3-14b-q5-k-m",
        )
        self.remote = RemoteService(
            service,
            AccessPolicy(secret),
            self.tasks,
            address="127.0.0.1",
            port=0,
        )
        status = self.remote.start()
        assert status.state == ServiceState.RUNNING, status.detail
        self.url = f"http://127.0.0.1:{status.port}"

    def close(self):
        self.remote.stop()
        self.tasks.shutdown(timeout=3)


@pytest.fixture
def host():
    running = Host()
    yield running
    running.close()


def client(url, secret=SECRET):
    backend = RemoteBackend(url, secret)
    backend.refresh()
    return backend


def local_blocks():
    """Blocks as the capturing device holds them, geometry included."""
    return [
        TextBlock("b1", [OcrLine([(1, 2), (60, 2), (60, 20), (1, 20)], "Hello", 0.93)]),
        TextBlock("b2", [OcrLine([(1, 24), (60, 24), (60, 42), (1, 42)], "World", 0.81)]),
    ]


def test_health_reports_a_ready_host(host):
    backend = client(host.url)

    assert backend.ready() is True
    assert backend.health.current.model_id == "qwen3-14b-q5-k-m"
    assert backend.health.current.device == "CUDA"
    backend.stop()


def test_a_capture_runs_ocr_and_translation_on_the_host(host):
    backend = client(host.url)
    messages = []
    image = numpy.zeros((48, 64, 3), numpy.uint8)

    result = backend.ocr.recognize(image, "en", CancellationToken(), messages.append)
    blocks = local_blocks()
    translated = backend.translator.translate(
        blocks, CancellationToken(), messages.append, "en", "zh-Hans", result.detected_language
    )

    assert [line.text for line in result.lines] == ["Hello", "World"]
    assert result.detected_language == "en"
    assert result.lines[0].polygon[0] == (1.0, 2.0)
    assert [item.text for item in translated] == ["译[Hello]", "译[World]"]
    # Geometry came from the client's own blocks, not from the reply.
    assert translated[0].block is blocks[0]
    assert backend.translator.last_metrics == {"batches": 1, "quality_retries": 0}
    assert "正在识别文字…" in messages
    assert "正在翻译 1/1 · CUDA" in messages
    backend.stop()


def test_the_language_pair_reaches_the_host_unchanged(host):
    backend = client(host.url)

    backend.translator.translate(
        local_blocks(), CancellationToken(), lambda _t: None, "ja", "ko", "ja"
    )

    assert host.translator.seen[-1][:3] == ("ja", "ko", "ja")
    backend.stop()


def test_a_wrong_secret_leaves_the_client_not_ready_and_blocks_work(host, caplog):
    backend = client(host.url, OTHER_SECRET)

    with caplog.at_level(logging.WARNING):
        assert backend.ready() is False
        assert "拒绝" in backend.describe()
        with pytest.raises(RemoteError, match="拒绝"):
            backend.translator.translate(
                local_blocks(), CancellationToken(), lambda _t: None, "en", "zh-Hans", None
            )

    # The peer learns only that it was refused; which check failed stays on
    # the host, so a caller cannot probe the allow-list.
    assert "invalid-token" not in backend.describe()
    assert "invalid-token" in "\n".join(record.getMessage() for record in caplog.records)
    backend.stop()


def test_an_unlisted_device_is_refused_indistinguishably_from_a_wrong_secret():
    running = Host()
    running.remote.stop()
    try:
        service = TranslationService(
            ocr_provider=lambda: running.ocr,
            inference=running.inference,
            ready_provider=lambda: True,
            model_provider=lambda: "qwen3-14b-q5-k-m",
        )
        restricted = RemoteService(
            service,
            AccessPolicy(SECRET, frozenset({"100.64.0.1"}), allow_loopback=False),
            running.tasks,
            address="127.0.0.1",
            port=0,
        )
        status = restricted.start()
        backend = RemoteBackend(f"http://127.0.0.1:{status.port}", SECRET)
        backend.refresh()

        assert backend.ready() is False
        assert "拒绝" in backend.describe()
        assert "peer" not in backend.describe()
        backend.stop()
        restricted.stop()
    finally:
        running.close()


def test_an_unreachable_host_is_reported_rather_than_falling_back(host):
    host.close()
    backend = client(host.url)

    assert backend.ready() is False
    assert "不可用" in backend.describe()
    with pytest.raises(RemoteError):
        backend.translator.translate(
            local_blocks(), CancellationToken(), lambda _t: None, "en", "zh-Hans", None
        )
    backend.stop()


def test_cancelling_on_the_client_cancels_the_work_on_the_host():
    observed = threading.Event()
    releasing = threading.Event()

    def behaviour(token, progress):
        progress("开始长任务")
        releasing.wait(5)
        while not token.event.is_set():
            time.sleep(0.01)
        observed.set()
        raise Cancelled()

    running = Host(FakeTranslator(behaviour))
    try:
        backend = client(running.url)
        token = CancellationToken()

        def on_progress(_text):
            token.cancel()
            releasing.set()

        with pytest.raises(Cancelled):
            backend.translator.translate(
                local_blocks(), token, on_progress, "en", "zh-Hans", None
            )

        assert observed.wait(10), "host never observed the cancellation"
        backend.stop()
    finally:
        running.close()


def test_a_host_failure_arrives_as_a_readable_message():
    def behaviour(_token, _progress):
        raise RuntimeError("14B 回退也失败")

    running = Host(FakeTranslator(behaviour))
    try:
        backend = client(running.url)
        with pytest.raises(RemoteError, match="14B 回退也失败"):
            backend.translator.translate(
                local_blocks(), CancellationToken(), lambda _t: None, "en", "zh-Hans", None
            )
        backend.stop()
    finally:
        running.close()


def test_a_host_with_no_models_reports_not_ready_instead_of_failing_late():
    running = Host(ready=False)
    try:
        backend = client(running.url)
        assert backend.ready() is False
        assert "未就绪" in backend.describe()
        backend.stop()
    finally:
        running.close()


def test_warmup_reaches_both_engines(host):
    backend = client(host.url)
    messages = []

    backend.ocr.warmup("en", CancellationToken(), messages.append)
    backend.translator.start(CancellationToken(), messages.append)

    assert "正在加载文字检测模型…" in messages
    assert "正在加载模型…" in messages
    backend.stop()


def test_a_client_never_unloads_the_host_model(host):
    backend = client(host.url)

    backend.translator.stop()

    assert backend.ready() is True
    backend.stop()


def test_the_service_tells_the_policy_which_address_it_bound(host):
    # Without this the host cannot self-test through its own allow-list, and
    # a loopback-only probe would miss the interface the peers actually use.
    assert host.remote._context.policy.local_address == "127.0.0.1"
    assert host.remote.status.url == host.url


def test_a_protocol_mismatch_names_both_versions(host, monkeypatch):
    monkeypatch.setattr("screen_translator.remote.client.PROTOCOL_VERSION", 99)
    backend = RemoteBackend(host.url, SECRET)

    backend.refresh()

    # The host's own explanation reaches the user instead of "HTTP 400".
    assert "协议版本不一致" in backend.describe()
    with pytest.raises(RemoteError, match="协议版本不一致"):
        backend.translator.translate(
            local_blocks(), CancellationToken(), lambda _t: None, "en", "zh-Hans", None
        )
    backend.stop()


def test_an_oversized_upload_is_refused_by_the_host(host, monkeypatch):
    monkeypatch.setattr("screen_translator.remote.protocol.MAX_IMAGE_BYTES", 32)
    monkeypatch.setattr("screen_translator.remote.service.MAX_IMAGE_BYTES", 32)
    backend = client(host.url)

    with pytest.raises(RemoteError):
        backend.ocr.recognize(
            numpy.zeros((64, 64, 3), numpy.uint8), "en", CancellationToken(), lambda _t: None
        )
    backend.stop()


def test_remote_traffic_does_not_write_user_text_to_the_log(host, caplog):
    backend = client(host.url)
    image = numpy.zeros((48, 64, 3), numpy.uint8)

    with caplog.at_level(logging.DEBUG):
        backend.ocr.recognize(image, "en", CancellationToken(), lambda _t: None)
        backend.translator.translate(
            local_blocks(), CancellationToken(), lambda _t: None, "en", "zh-Hans", "en"
        )

    recorded = "\n".join(record.getMessage() for record in caplog.records)
    for secret_content in ("Hello", "World", "译[", SECRET):
        assert secret_content not in recorded
    backend.stop()
