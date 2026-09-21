import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from screen_translator.core import CancellationToken, Cancelled
from screen_translator.models import AdapterBinding
from screen_translator.translation_engine import TranslationEngine


class FakeProcess:
    """A llama-server stand-in that records the lifecycle calls it receives."""

    def __init__(self, args, exit_code=None, ignore_terminate=False):
        self.args = args
        self.exit_code = exit_code
        self.ignore_terminate = ignore_terminate
        self.terminated = 0
        self.killed = 0
        self.waits = []

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated += 1
        if not self.ignore_terminate:
            self.exit_code = 0

    def kill(self):
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.ignore_terminate and timeout is not None:
            raise subprocess.TimeoutExpired("llama-server", timeout)
        return self.exit_code


def prepare(monkeypatch, tmp_path, *, healthy=True, exit_code=None, adapter=None, ignore_terminate=False):
    runtime = tmp_path / "runtime" / "llama"
    runtime.mkdir(parents=True)
    (runtime / "llama-server.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "screen_translator.translation_engine.resolve_model_path",
        lambda root, model_id, role: tmp_path / "model.gguf",
    )
    monkeypatch.setattr(
        "screen_translator.translation_engine.resolve_translation_adapter",
        lambda root, model_id: adapter,
    )
    jobs = []

    class FakeJob:
        def __init__(self):
            self.attached = []
            self.closed = 0
            jobs.append(self)

        def attach(self, process):
            self.attached.append(process)

        def close(self):
            self.closed += 1

    monkeypatch.setattr("screen_translator.native.Job", FakeJob)
    started = []

    def fake_popen(args, **_kwargs):
        process = FakeProcess(args, exit_code, ignore_terminate)
        started.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m")
    engine.session = Mock()
    engine.session.get.return_value = Mock(ok=healthy)
    return engine, started, jobs


def test_start_launches_a_loopback_only_cuda_server(monkeypatch, tmp_path):
    engine, started, jobs = prepare(monkeypatch, tmp_path)

    engine.start(CancellationToken(), lambda _message: None)

    args = started[0].args
    assert Path(args[0]).name == "llama-server.exe"
    assert args[args.index("-m") + 1] == str(tmp_path / "model.gguf")
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("-ngl") + 1] == "99"
    assert args[args.index("--parallel") + 1] == "2"
    assert args[args.index("-c") + 1] == "16384"
    assert "--no-webui" in args and "--jinja" in args
    assert len(args[args.index("--api-key") + 1]) >= 32
    assert "--lora" not in args and "--lora-scaled" not in args
    assert engine.mode == "CUDA"
    assert engine.adapter_id is None
    assert jobs[0].attached == [started[0]]


def test_a_released_adapter_is_passed_to_llama_cpp(monkeypatch, tmp_path):
    binding = AdapterBinding("screen-translator-8b-lora-v1", tmp_path / "adapter.gguf", 4.0)
    engine, started, _jobs = prepare(monkeypatch, tmp_path, adapter=binding)

    engine.start(CancellationToken(), lambda _message: None)

    args = started[0].args
    assert args[args.index("--lora-scaled") + 1] == f"{tmp_path / 'adapter.gguf'}:4"
    assert engine.adapter_id == "screen-translator-8b-lora-v1"


def test_start_is_idempotent_while_the_server_is_alive(monkeypatch, tmp_path):
    engine, started, _jobs = prepare(monkeypatch, tmp_path)

    engine.start(CancellationToken(), lambda _message: None)
    engine.start(CancellationToken(), lambda _message: None)

    assert len(started) == 1


def test_cancelling_during_startup_stops_the_server(monkeypatch, tmp_path):
    engine, started, jobs = prepare(monkeypatch, tmp_path, healthy=False)
    token = CancellationToken()
    engine.session.get.side_effect = lambda *_args, **_kwargs: token.cancel() or Mock(ok=False)

    with pytest.raises(Cancelled):
        engine.start(token, lambda _message: None)

    assert started[0].terminated == 1
    assert jobs[0].closed == 1
    assert engine.process is None
    assert engine.mode == "未加载"


def test_a_dead_server_without_cpu_fallback_reports_a_memory_hint(monkeypatch, tmp_path):
    engine, started, _jobs = prepare(monkeypatch, tmp_path, healthy=False, exit_code=1)

    with pytest.raises(RuntimeError, match="显存"):
        engine.start(CancellationToken(), lambda _message: None)

    assert len(started) == 1
    assert engine.mode == "未加载"


def test_cpu_fallback_retries_without_gpu_layers(monkeypatch, tmp_path):
    engine, started, _jobs = prepare(monkeypatch, tmp_path, healthy=False, exit_code=1)
    engine.allow_cpu = True

    with pytest.raises(RuntimeError):
        engine.start(CancellationToken(), lambda _message: None)

    assert [process.args[process.args.index("-ngl") + 1] for process in started] == ["99", "0"]


def test_stop_terminates_the_server_and_releases_the_job(monkeypatch, tmp_path):
    engine, started, jobs = prepare(monkeypatch, tmp_path)
    engine.start(CancellationToken(), lambda _message: None)

    engine.stop()

    assert started[0].terminated == 1 and started[0].killed == 0
    assert started[0].waits == [5]
    assert jobs[0].closed == 1
    assert engine.process is None and engine.job is None
    assert engine.mode == "未加载"


def test_stop_kills_a_server_that_ignores_terminate(monkeypatch, tmp_path):
    engine, started, jobs = prepare(monkeypatch, tmp_path, ignore_terminate=True)
    engine.start(CancellationToken(), lambda _message: None)

    engine.stop()

    assert started[0].terminated == 1 and started[0].killed == 1
    assert jobs[0].closed == 1
    assert engine.process is None


def test_stop_is_safe_when_nothing_was_started(monkeypatch, tmp_path):
    engine, started, _jobs = prepare(monkeypatch, tmp_path)

    engine.stop()

    assert started == [] and engine.process is None
