"""评测链路改造：GGUF 注入点与翻译方向必须可控，且不影响产品默认路径。"""

import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from screen_translator.translation_engine import TranslationEngine
from scripts.training.evaluate_models import main as evaluate_main
from scripts.training.evaluate_models import translate_batch


def test_product_path_still_resolves_through_the_registry(monkeypatch, tmp_path):
    resolved = tmp_path / "registry-model.gguf"
    calls = []
    monkeypatch.setattr(
        "screen_translator.translation_engine.resolve_model_path",
        lambda root, model_id, role: calls.append(model_id) or resolved,
    )

    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m")

    assert engine.model_path_override is None
    assert engine.model.display_name == "Qwen3 8B（平衡）"
    assert calls == []  # resolution is deferred to start()


def test_override_points_the_engine_at_an_arbitrary_gguf(tmp_path):
    gguf = tmp_path / "candidate-q5.gguf"
    gguf.write_bytes(b"GGUF")

    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m", model_path_override=gguf)

    assert engine.model_path_override == gguf


def test_override_accepts_an_unregistered_label(tmp_path):
    gguf = tmp_path / "screen-translator-8b-enzh-v1-Q5_K_M.gguf"
    gguf.write_bytes(b"GGUF")

    engine = TranslationEngine(
        tmp_path, model_id="screen-translator-8b-enzh-v1", parallel_slots=2, model_path_override=gguf
    )

    assert engine.model.model_id == "screen-translator-8b-enzh-v1"
    assert engine.model.filename == gguf.name
    assert engine.model.fallback_languages == ()


def test_unregistered_label_without_override_is_still_rejected(tmp_path):
    with pytest.raises(ValueError, match="不支持的翻译模型"):
        TranslationEngine(tmp_path, model_id="not-a-model")


def test_override_start_fails_clearly_when_the_file_is_missing(tmp_path):
    gguf = tmp_path / "gone.gguf"
    gguf.write_bytes(b"GGUF")
    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m", model_path_override=gguf)
    gguf.unlink()

    with pytest.raises(RuntimeError, match="模型文件不存在"):
        engine.start(SimpleNamespace(check=lambda: None), lambda _m: None)


def test_override_skips_registry_and_adapter_resolution(monkeypatch, tmp_path):
    gguf = tmp_path / "candidate.gguf"
    gguf.write_bytes(b"GGUF")
    monkeypatch.setattr(
        "screen_translator.translation_engine.resolve_translation_adapter",
        Mock(side_effect=AssertionError("adapters must not be resolved for an override")),
    )
    monkeypatch.setattr(
        "screen_translator.translation_engine.resolve_model_path",
        Mock(side_effect=AssertionError("the registry must not be consulted for an override")),
    )
    # Point the runtime lookup at an empty tree so start() stops before spawning llama-server.
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "no-runtime"), raising=False)
    engine = TranslationEngine(tmp_path, model_id="qwen3-8b-q5-k-m", model_path_override=gguf)

    with pytest.raises(RuntimeError, match="llama.cpp"):
        engine.start(SimpleNamespace(check=lambda: None), lambda _m: None)

    assert engine.model_path == gguf
    assert engine.adapter_id is None


@pytest.mark.parametrize("target", ["zh-Hans", "en"])
def test_translate_batch_forwards_the_target_language(target):
    engine = SimpleNamespace(request=Mock(return_value={"1": "out"}))
    records = [{"id": "1", "source_text": "text", "source_language": "en"}]

    translate_batch(engine, records, SimpleNamespace(check=lambda: None), target)

    assert engine.request.call_args[0][3] == target


def test_translate_batch_defaults_to_chinese():
    engine = SimpleNamespace(request=Mock(return_value={"1": "out"}))
    records = [{"id": "1", "source_text": "text", "source_language": "en"}]

    translate_batch(engine, records, SimpleNamespace(check=lambda: None))

    assert engine.request.call_args[0][3] == "zh-Hans"


def test_cli_rejects_an_unknown_model_without_a_gguf_path(capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(["--model", "nope"])

    assert exit_info.value.code == 2
    assert "--gguf-path" in capsys.readouterr().err


def test_cli_rejects_a_missing_gguf_path(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(["--model", "candidate", "--gguf-path", str(tmp_path / "absent.gguf")])
    assert exit_info.value.code == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_accepts_a_registered_model_unchanged(tmp_path, monkeypatch):
    """A registered ID must keep working with no new flags (backward compatibility)."""
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        json.dumps({"id": "1", "source_text": "a", "reference_text": "b",
                    "source_language": "en", "domain": "news_web"}) + "\n",
        encoding="utf-8",
    )
    started = {}

    class FakeEngine:
        parallel_slots = 2

        def __init__(self, *args, **kwargs):
            started["kwargs"] = kwargs

        def start(self, token, progress):
            raise RuntimeError("stop before inference")

        def stop(self):
            pass

    monkeypatch.setattr("scripts.training.evaluate_models.TranslationEngine", FakeEngine)
    with pytest.raises(RuntimeError, match="stop before inference"):
        _run(["--model", "qwen3-8b-q5-k-m", "--dataset", str(dataset),
              "--output-dir", str(tmp_path / "out")])

    assert started["kwargs"]["model_path_override"] is None


def _run(argv):
    original = sys.argv
    sys.argv = ["evaluate_models.py", *argv]
    try:
        return evaluate_main()
    finally:
        sys.argv = original
