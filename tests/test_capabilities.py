from types import SimpleNamespace

import pytest

from screen_translator import capabilities
from screen_translator.backend import LocalBackend
from screen_translator.core import Config


@pytest.fixture(autouse=True)
def clear_capability_cache():
    # The answer is fixed for a real process but not for a test session.
    capabilities.llama_runtime_available.cache_clear()
    capabilities.ocr_runtime_available.cache_clear()
    yield
    capabilities.llama_runtime_available.cache_clear()
    capabilities.ocr_runtime_available.cache_clear()


def stub_engines():
    return (
        lambda root, allow_cpu: SimpleNamespace(mode="未加载"),
        lambda root, allow_cpu, model_id: SimpleNamespace(mode="未加载", stop=lambda: None),
    )


def test_a_full_build_reports_no_missing_runtime(monkeypatch):
    monkeypatch.setattr(capabilities, "llama_runtime_available", lambda: True)
    monkeypatch.setattr(capabilities, "ocr_runtime_available", lambda: True)

    assert capabilities.local_runtime_available() is True
    assert capabilities.describe_missing_runtime() == ""


@pytest.mark.parametrize(
    ("llama", "ocr", "expected"),
    [
        (False, True, "llama.cpp"),
        (True, False, "PaddleOCR"),
        (False, False, "PaddleOCR、llama.cpp"),
    ],
)
def test_a_missing_runtime_is_named_in_the_message(monkeypatch, llama, ocr, expected):
    monkeypatch.setattr(capabilities, "llama_runtime_available", lambda: llama)
    monkeypatch.setattr(capabilities, "ocr_runtime_available", lambda: ocr)

    message = capabilities.describe_missing_runtime()

    assert capabilities.local_runtime_available() is False
    assert expected in message
    assert "远程主机模式" in message


def test_the_ocr_probe_does_not_import_the_package(monkeypatch):
    imported = []
    monkeypatch.setattr(
        capabilities.importlib.util,
        "find_spec",
        lambda name: imported.append(name) or object(),
    )

    assert capabilities.ocr_runtime_available() is True
    assert imported == ["paddleocr"]


def test_a_client_build_is_never_ready_for_local_models(monkeypatch, tmp_path):
    monkeypatch.setattr("screen_translator.backend.local_runtime_available", lambda: False)
    monkeypatch.setattr(
        "screen_translator.backend.describe_missing_runtime",
        lambda: "此版本未包含本地推理运行时（缺少 PaddleOCR、llama.cpp），请切换到远程主机模式",
    )
    monkeypatch.setattr("screen_translator.backend.models_ready", lambda *_args: True)
    ocr_factory, translator_factory = stub_engines()

    backend = LocalBackend(
        Config(model_dir=str(tmp_path)),
        ocr_factory=ocr_factory,
        translator_factory=translator_factory,
    )

    assert backend.ready() is False
    assert "远程主机模式" in backend.describe()


def test_a_full_build_with_models_is_ready(monkeypatch, tmp_path):
    monkeypatch.setattr("screen_translator.backend.local_runtime_available", lambda: True)
    monkeypatch.setattr("screen_translator.backend.describe_missing_runtime", lambda: "")
    monkeypatch.setattr("screen_translator.backend.models_ready", lambda *_args: True)
    ocr_factory, translator_factory = stub_engines()

    backend = LocalBackend(
        Config(model_dir=str(tmp_path)),
        ocr_factory=ocr_factory,
        translator_factory=translator_factory,
    )

    assert backend.ready() is True
    assert backend.describe() == "本地模型就绪"
