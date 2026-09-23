"""Manual translation must complete with every non-loopback socket blocked."""

import os
import socket
from types import SimpleNamespace

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.core import Config, TranslatedBlock
from screen_translator.feedback import Occupancy
from screen_translator.inference import InferenceCoordinator
from screen_translator.manual_translation import ManualTranslationController
from screen_translator.text_segmenter import segment_text
from screen_translator.text_translation_page import TextTranslationPage

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class LoopbackPort:
    """Talks to a llama.cpp server exactly the way the real engine does."""

    mode = "CUDA"
    model = SimpleNamespace(model_id="qwen3-8b-q5-k-m")
    adapter_id = None

    def start(self, token, progress):
        pass

    def stop(self):
        pass

    def translate(self, blocks, token, progress, *_args, **_kwargs):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            with pytest.raises(OSError):
                probe.connect(("huggingface.co", 443))
        return [TranslatedBlock(block, f"译{block.text}") for block in blocks]


class SyncRunner:
    def start(self, target, *, name):
        target()


@pytest.fixture
def offline(monkeypatch):
    original = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise OSError(f"external connection blocked: {host}")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    return guarded


def test_manual_translation_completes_while_offline(offline):
    QApplication.instance() or QApplication([])
    port = LoopbackPort()
    controller = ManualTranslationController(InferenceCoordinator(lambda: port), SyncRunner())
    results = []
    controller.finished.connect(lambda _rid, text: results.append(text))
    failures = []
    controller.failed.connect(lambda _rid, text: failures.append(text))

    controller.translate("1. Hello\n2. World\n", "en", "zh-Hans")

    assert failures == []
    assert results == ["1. 译Hello\n2. 译World\n"]


def test_segmentation_and_the_page_never_touch_the_network(offline):
    QApplication.instance() or QApplication([])
    port = LoopbackPort()
    arbiter = InferenceCoordinator(lambda: port)
    manual = ManualTranslationController(arbiter, SyncRunner())
    page = TextTranslationPage(
        SimpleNamespace(
            config=Config(translation_model="qwen3-8b-q5-k-m", source_language="en", target_language="zh-Hans"),
            busy=False,
            occupancy=lambda: Occupancy(),
            detected_source_language=None,
            translator=port,
            backend=SimpleNamespace(ready=lambda: True, describe=lambda: "本地模型就绪"),
            manual=manual,
            inference=arbiter,
            set_language_pair=lambda *_args: True,
        )
    )

    assert segment_text("Hello\n\nWorld\n").translatable_count == 2

    page.source_text.setPlainText("Hello")
    page.translate_button.click()

    assert page.target_text.toPlainText() == "译Hello"
    page.deleteLater()
