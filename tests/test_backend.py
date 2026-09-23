from dataclasses import replace
from types import SimpleNamespace

import pytest

from screen_translator.backend import LocalBackend, create_backend
from screen_translator.core import Config

SECRET = "s" * 32


def fake_engines():
    calls = {}

    def ocr_factory(root, allow_cpu):
        calls["ocr"] = (root, allow_cpu)
        return SimpleNamespace(mode="未加载")

    def translator_factory(root, allow_cpu, model_id):
        calls["translator"] = (root, allow_cpu, model_id)
        return SimpleNamespace(mode="未加载", stop=lambda: calls.setdefault("stopped", True))

    return ocr_factory, translator_factory, calls


def test_local_backend_passes_configuration_to_both_engines(tmp_path):
    ocr_factory, translator_factory, calls = fake_engines()
    config = Config(model_dir=str(tmp_path), allow_cpu=True, translation_model="qwen3-8b-q5-k-m")

    backend = LocalBackend(config, ocr_factory=ocr_factory, translator_factory=translator_factory)

    assert calls["ocr"] == (str(tmp_path), True)
    assert calls["translator"] == (str(tmp_path), True, "qwen3-8b-q5-k-m")
    assert backend.kind == "local"


def test_local_backend_is_not_ready_without_registered_models(tmp_path):
    ocr_factory, translator_factory, _calls = fake_engines()
    config = Config(model_dir=str(tmp_path))

    backend = LocalBackend(config, ocr_factory=ocr_factory, translator_factory=translator_factory)

    assert backend.ready() is False
    assert backend.describe() == "本地模型未下载"


def test_stopping_a_local_backend_stops_the_translation_server(tmp_path):
    ocr_factory, translator_factory, calls = fake_engines()

    LocalBackend(
        Config(model_dir=str(tmp_path)),
        ocr_factory=ocr_factory,
        translator_factory=translator_factory,
    ).stop()

    assert calls["stopped"] is True


def test_default_configuration_selects_the_local_backend(tmp_path):
    backend = create_backend(Config(model_dir=str(tmp_path)))

    assert backend.kind == "local"
    backend.stop()


def test_remote_configuration_selects_the_remote_backend():
    config = replace(
        Config(),
        mode="remote",
        remote_url="http://100.101.102.103:8765",
        remote_token=SECRET,
    )

    backend = create_backend(config)

    assert backend.kind == "remote"
    # No network touched yet: readiness starts false until a refresh succeeds.
    assert backend.ready() is False
    backend.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [("remote_url", ""), ("remote_token", "")],
)
def test_incomplete_remote_configuration_fails_loudly(field, value):
    complete = {
        "mode": "remote",
        "remote_url": "http://100.101.102.103:8765",
        "remote_token": SECRET,
    }
    config = replace(Config(), **{**complete, field: value})

    with pytest.raises(ValueError):
        create_backend(config)
