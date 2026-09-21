import logging
import os
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.core import TranslatedBlock
from screen_translator.inference import InferenceCoordinator
from screen_translator.logging_setup import configure_logging
from screen_translator.manual_translation import ManualTranslationController

SECRET = "员工薪资表 2026 Q3 · password Hunter2 · D:/私人文档/合同.docx"
TRANSLATION = "Employee salary sheet 2026 Q3"


class RecordingPort:
    mode = "CUDA"
    model = SimpleNamespace(model_id="qwen3-8b-q5-k-m")
    adapter_id = None

    def __init__(self, failure=None):
        self.failure = failure

    def start(self, token, progress):
        pass

    def stop(self):
        pass

    def translate(self, blocks, token, progress, *_args, **_kwargs):
        if self.failure is not None:
            raise self.failure
        progress("正在翻译 1/1 · CUDA")
        return [TranslatedBlock(block, TRANSLATION) for block in blocks]


class SyncRunner:
    def start(self, target, *, name):
        target()


def build(port):
    QApplication.instance() or QApplication([])
    return ManualTranslationController(InferenceCoordinator(lambda: port), SyncRunner())


def logged_text(caplog):
    return "\n".join(record.getMessage() for record in caplog.records)


def test_a_successful_translation_logs_counts_but_no_content(caplog):
    controller = build(RecordingPort())

    with caplog.at_level(logging.DEBUG):
        controller.translate(SECRET, "zh-Hans", "en")

    text = logged_text(caplog)
    assert "status=ok" in text and "segments=1" in text
    assert SECRET not in text
    assert TRANSLATION not in text
    assert "Hunter2" not in text
    assert "合同.docx" not in text


def test_a_failure_logs_the_exception_class_and_not_the_document(caplog):
    controller = build(RecordingPort(ValueError(SECRET)))

    with caplog.at_level(logging.DEBUG):
        controller.translate(SECRET, "zh-Hans", "en")

    text = logged_text(caplog)
    assert "status=error:ValueError" in text
    assert SECRET not in text
    assert "私人文档" not in text


def test_a_cancelled_translation_logs_only_its_status(caplog):
    def cancel(blocks, token, progress, *_args, **_kwargs):
        token.cancel()
        token.check()

    port = RecordingPort()
    port.translate = cancel
    controller = build(port)

    with caplog.at_level(logging.DEBUG):
        controller.translate(SECRET, "zh-Hans", "en")

    text = logged_text(caplog)
    assert "status=cancelled" in text
    assert SECRET not in text


def test_logging_setup_writes_to_the_application_log_without_content(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = logging.getLogger()
    performance = logging.getLogger("screen_translator.performance")
    saved = (root.handlers[:], root.level, performance.handlers[:], performance.propagate)
    root.handlers = []
    performance.handlers = []
    try:
        configure_logging("INFO")
        logging.getLogger("screen_translator.manual_translation").info("chars=%d", len(SECRET))
        for handler in root.handlers:
            handler.flush()
        written = (tmp_path / "ScreenTranslator" / "logs" / "app.log").read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers, root.level, performance.handlers, performance.propagate = saved

    assert f"chars={len(SECRET)}" in written
    assert "screen_translator.manual_translation" in written
    assert SECRET not in written
