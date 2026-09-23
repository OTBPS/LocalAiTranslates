import logging
import os
import threading
from types import SimpleNamespace

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken, Cancelled, TranslatedBlock
from screen_translator.inference import InferenceBusy, InferenceCoordinator
from screen_translator.manual_translation import (
    EMPTY_INPUT_MESSAGE,
    NOTHING_TO_TRANSLATE_MESSAGE,
    SAME_LANGUAGE_MESSAGE,
    ManualTranslationController,
)
from screen_translator.text_segmenter import MAX_INPUT_CHARACTERS


def qt_app():
    return QApplication.instance() or QApplication([])


class FakePort:
    """Minimal TranslationPort: prefixes every block and records its calls."""

    def __init__(self, behaviour=None):
        self.mode = "CUDA"
        self.model = SimpleNamespace(model_id="qwen3-8b-q5-k-m")
        self.adapter_id = None
        self.calls = []
        self.started = 0
        self.behaviour = behaviour

    def start(self, token, progress):
        self.started += 1

    def stop(self):
        pass

    def translate(self, blocks, token, progress, source_language="auto", target_language="zh-Hans",
                  detected_language=None):
        self.calls.append((list(blocks), source_language, target_language))
        if self.behaviour is not None:
            return self.behaviour(blocks, token, progress)
        progress(f"正在翻译 1/{len(blocks)}")
        return [TranslatedBlock(block, f"译{block.text}") for block in blocks]


class SyncRunner:
    def __init__(self):
        self.names = []

    def start(self, target, *, name):
        self.names.append(name)
        target()
        return None


class DeferredRunner(SyncRunner):
    """Keep tasks pending so overlapping requests can be observed."""

    def __init__(self):
        super().__init__()
        self.pending = []

    def start(self, target, *, name):
        self.names.append(name)
        self.pending.append(target)
        return None

    def run_all(self):
        pending, self.pending = self.pending, []
        for target in pending:
            target()


def build(port=None, runner=None):
    qt_app()
    port = port or FakePort()
    runner = runner or SyncRunner()
    arbiter = InferenceCoordinator(lambda: port)
    controller = ManualTranslationController(arbiter, runner)
    events = {"started": [], "progress": [], "finished": [], "failed": [], "cancelled": []}
    controller.started.connect(lambda rid: events["started"].append(rid))
    controller.progress.connect(lambda rid, text: events["progress"].append((rid, text)))
    controller.finished.connect(lambda rid, text: events["finished"].append((rid, text)))
    controller.failed.connect(lambda rid, text: events["failed"].append((rid, text)))
    controller.cancelled.connect(lambda rid: events["cancelled"].append(rid))
    return controller, port, runner, arbiter, events


@pytest.mark.parametrize("text", ["", "   ", "\n\t\n"])
def test_empty_input_reports_without_touching_the_engine(text):
    controller, port, runner, _arbiter, events = build()

    request_id = controller.translate(text, "en", "zh-Hans")

    assert events["failed"] == [(request_id, EMPTY_INPUT_MESSAGE)]
    assert runner.names == [] and port.calls == [] and port.started == 0


def test_identical_languages_return_the_input_unchanged():
    controller, port, runner, _arbiter, events = build()

    request_id = controller.translate("Hello", "en", "en")

    assert events["finished"] == [(request_id, "Hello")]
    assert (request_id, SAME_LANGUAGE_MESSAGE) in events["progress"]
    assert runner.names == [] and port.calls == []


def test_auto_source_is_never_treated_as_the_same_language():
    controller, port, _runner, _arbiter, events = build()

    controller.translate("Hello", "auto", "zh-Hans")

    assert port.calls and not events["failed"]


@pytest.mark.parametrize("text", ["12345", "!!! ??? ###", "3.14 / 2.71"])
def test_input_without_letters_is_returned_unchanged(text):
    controller, port, runner, _arbiter, events = build()

    request_id = controller.translate(text, "en", "zh-Hans")

    assert events["finished"] == [(request_id, text)]
    assert (request_id, NOTHING_TO_TRANSLATE_MESSAGE) in events["progress"]
    assert runner.names == [] and port.calls == []


def test_input_above_the_character_limit_is_rejected():
    controller, port, _runner, _arbiter, events = build()

    request_id = controller.translate("a" * (MAX_INPUT_CHARACTERS + 1), "en", "zh-Hans")

    assert events["failed"] and events["failed"][0][0] == request_id
    assert str(MAX_INPUT_CHARACTERS) in events["failed"][0][1]
    assert port.calls == []


def test_successful_translation_reassembles_segments_and_keeps_numbering():
    controller, port, runner, _arbiter, events = build()

    request_id = controller.translate("1. Alpha\n2. Beta\n", "en", "zh-Hans")

    assert events["started"] == [request_id]
    assert events["finished"] == [(request_id, "1. 译Alpha\n2. 译Beta\n")]
    assert runner.names == [f"manual-translation-{request_id}"]
    assert [block.block_id for block in port.calls[0][0]] == ["0", "1"]
    assert port.calls[0][1:] == ("en", "zh-Hans")


@pytest.mark.parametrize(
    ("source", "target"),
    [("en", "zh-Hans"), ("zh-Hans", "en"), ("ja", "zh-Hans"), ("ko", "zh-Hans"),
     ("zh-Hans", "ja"), ("zh-Hans", "ko"), ("auto", "en")],
)
def test_every_supported_direction_reaches_the_engine(source, target):
    controller, port, _runner, _arbiter, events = build()

    controller.translate("Hello world", source, target)

    assert port.calls[0][1:] == (source, target)
    assert events["finished"] and not events["failed"]


def test_progress_messages_carry_the_request_id():
    controller, _port, _runner, _arbiter, events = build()

    request_id = controller.translate("Hello", "en", "zh-Hans")

    assert (request_id, "正在翻译 1/1") in events["progress"]


def test_a_new_request_cancels_the_previous_task_and_discards_its_result():
    controller, _port, runner, arbiter, events = build(runner=DeferredRunner())
    first_id = controller.translate("first", "en", "zh-Hans")
    (first_token,) = arbiter.preemptable_tokens
    second_id = controller.translate("second", "en", "zh-Hans")

    assert second_id == first_id + 1
    assert first_token.event.is_set()

    runner.run_all()

    assert events["finished"] == [(second_id, "译second")]
    assert events["cancelled"] == []


def test_cancel_marks_the_task_cancelled_and_clears_the_active_flag():
    def behaviour(blocks, token, progress):
        token.cancel()
        token.check()

    controller, _port, _runner, arbiter, events = build(FakePort(behaviour))
    request_id = controller.translate("Hello", "en", "zh-Hans")

    assert events["cancelled"] == [request_id]
    assert events["finished"] == []
    assert controller.active is False
    assert arbiter.cancel_manual() is False


def test_cancel_before_completion_cancels_the_registered_token():
    released = threading.Event()
    seen = []

    def behaviour(blocks, token, progress):
        seen.append(token)
        released.wait(2)
        token.check()
        return []

    qt_app()
    port = FakePort(behaviour)
    from screen_translator.tasks import TaskRunner

    runner = TaskRunner()
    arbiter = InferenceCoordinator(lambda: port)
    controller = ManualTranslationController(arbiter, runner)
    cancelled = []
    controller.cancelled.connect(lambda rid: cancelled.append(rid))

    request_id = controller.translate("Hello", "en", "zh-Hans")
    while not seen:
        pass
    controller.cancel()
    released.set()
    runner.shutdown(2)
    QApplication.processEvents()

    assert seen[0].event.is_set()
    assert cancelled == [request_id]
    assert controller.active is False


def test_a_superseded_result_never_reaches_the_view():
    controller, _port, _runner, _arbiter, events = build()
    stale_id = controller.request_id

    controller._is_current = lambda request_id: request_id != stale_id + 1
    controller.translate("Hello", "en", "zh-Hans")

    assert events["finished"] == []
    assert events["failed"] == []


def test_a_busy_engine_is_reported_without_a_traceback():
    controller, port, _runner, arbiter, events = build()
    arbiter.begin_capture()

    request_id = controller.translate("Hello", "en", "zh-Hans")

    assert events["failed"] == [(request_id, "截图翻译正在进行，请稍后再试")]
    assert port.calls == []
    assert isinstance(InferenceBusy("x"), RuntimeError)


def test_runtime_errors_reach_the_user_and_other_errors_are_sanitized():
    def runtime_failure(blocks, token, progress):
        raise RuntimeError("模型启动失败或显存不足")

    controller, _port, _runner, _arbiter, events = build(FakePort(runtime_failure))
    controller.translate("Hello", "en", "zh-Hans")
    assert events["failed"][0][1] == "模型启动失败或显存不足"

    def opaque_failure(blocks, token, progress):
        raise ValueError("D:/private/secret-document.txt")

    controller, _port, _runner, _arbiter, events = build(FakePort(opaque_failure))
    controller.translate("Hello", "en", "zh-Hans")
    assert events["failed"][0][1] == "翻译失败（ValueError），请稍后重试"


def test_cancellation_inside_the_engine_is_not_reported_as_a_failure():
    def cancelled(blocks, token, progress):
        raise Cancelled()

    controller, _port, _runner, _arbiter, events = build(FakePort(cancelled))
    request_id = controller.translate("Hello", "en", "zh-Hans")

    assert events["cancelled"] == [request_id]
    assert events["failed"] == []


def test_logs_record_counts_and_never_user_content(caplog):
    secret = "机密合同编号 A-1024 请勿外传"
    controller, _port, _runner, _arbiter, _events = build()

    with caplog.at_level(logging.INFO, logger="screen_translator.manual_translation"):
        controller.translate(secret, "zh-Hans", "en")

    record = caplog.records[-1]
    message = record.getMessage()
    assert f"chars={len(secret)}" in message
    assert "segments=1" in message
    assert "status=ok" in message
    assert "model=qwen3-8b-q5-k-m" in message
    assert secret not in message
    assert "译" not in message


def test_manual_token_is_registered_so_capture_can_preempt_it():
    seen = []

    def behaviour(blocks, token, progress):
        seen.append(token)
        return [TranslatedBlock(block, block.text) for block in blocks]

    controller, _port, _runner, arbiter, _events = build(FakePort(behaviour))
    registered = []
    original = arbiter.register_manual
    arbiter.register_manual = lambda token: (registered.append(token), original(token))[1]

    controller.translate("Hello", "en", "zh-Hans")

    assert registered and registered[0] is seen[0]
    assert isinstance(registered[0], CancellationToken)
