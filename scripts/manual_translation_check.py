"""Offline acceptance check for the text translation workspace.

Runs the real segmenter, the real `InferenceCoordinator` and a real llama.cpp
server against synthetic fixture text — no user content is read or written.
Every non-loopback socket is blocked for the duration, so a pass proves the
workspace works with no network.

    .venv\\Scripts\\python.exe scripts\\manual_translation_check.py --report build\\manual-translation-check.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.inference import MANUAL, InferenceBusy, InferenceCoordinator  # noqa: E402
from screen_translator.manual_translation import ManualTranslationController  # noqa: E402
from screen_translator.models import DEFAULT_SHARED_MODEL_ROOT  # noqa: E402
from screen_translator.tasks import TaskRunner  # noqa: E402
from screen_translator.text_segmenter import segment_text  # noqa: E402
from screen_translator.translation_engine import TranslationEngine  # noqa: E402

# Synthetic fixtures only; none of this is user content.
FIXTURES = {
    "en": (
        "en",
        "zh-Hans",
        "Release Checklist\n"
        "1. Open the settings window and confirm the shortcut.\n"
        "2. Select the input and output languages.\n"
        "3. Paste the document and press the translate button.\n\n"
        "The application keeps working without a network connection.\n",
    ),
    "ja": ("ja", "zh-Hans", "設定ウィンドウを開いてください。\n\nショートカットを確認してから保存します。\n"),
    "ko": ("ko", "zh-Hans", "설정 창을 열어 주세요.\n\n단축키를 확인한 뒤 저장합니다.\n"),
    "zh": ("zh-Hans", "en", "请打开设置窗口。\n\n确认快捷键后保存。\n"),
}


def block_external_sockets():
    connect = socket.socket.connect

    def offline_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("External network attempted during manual translation")
        return connect(sock, address)

    socket.socket.connect = offline_connect


def run_case(app, controller, name, source, target, text):
    outcome = {}
    controller.finished.connect(lambda rid, value: outcome.update(status="ok", request=rid, output=value))
    controller.failed.connect(lambda rid, value: outcome.update(status="failed", request=rid, message=value))
    controller.cancelled.connect(lambda rid: outcome.update(status="cancelled", request=rid))
    started = time.monotonic()
    controller.translate(text, source, target)
    deadline = started + 300
    while not outcome and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    elapsed = time.monotonic() - started
    document = segment_text(text)
    output = outcome.get("output", "")
    return {
        "case": name,
        "source": source,
        "target": target,
        "status": outcome.get("status", "timeout"),
        "message": outcome.get("message"),
        "characters": len(text),
        "segments": len(document.segments),
        "translatable_segments": document.translatable_count,
        "output_characters": len(output),
        "structure_preserved": _structure_preserved(text, output),
        "seconds": round(elapsed, 3),
    }


def _structure_preserved(source: str, output: str) -> bool:
    """Compare only the framing: blank lines and list markers, never content."""
    if not output:
        return False
    original = segment_text(source)
    translated = segment_text(output)
    return [segment.prefix for segment in original.segments] == [
        segment.prefix for segment in translated.segments
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-root", type=Path, default=DEFAULT_SHARED_MODEL_ROOT)
    parser.add_argument("--model-id", default="qwen3-8b-q5-k-m")
    parser.add_argument("--report", type=Path, default=Path("build") / "manual-translation-check.json")
    args = parser.parse_args(argv)

    block_external_sockets()
    app = QApplication.instance() or QApplication([])
    engine = TranslationEngine(args.model_root, model_id=args.model_id)
    tasks = TaskRunner()
    coordinator = InferenceCoordinator(lambda: engine)
    controller = ManualTranslationController(coordinator, tasks)
    report = {"model_id": args.model_id, "adapter_id": None, "cases": []}
    try:
        for name, (source, target, text) in FIXTURES.items():
            record = run_case(app, controller, name, source, target, text)
            report["cases"].append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)

        report["device"] = engine.mode
        report["adapter_id"] = engine.adapter_id

        # A capture must be able to take the slot away from a manual translation.
        coordinator.begin_capture()
        try:
            with coordinator.reserve(MANUAL):
                report["capture_exclusion"] = "not-enforced"
        except InferenceBusy:
            report["capture_exclusion"] = "enforced"
        coordinator.end_capture()

        # Cancellation must leave the workspace idle.
        controller.translate(FIXTURES["en"][2] * 4, "en", "zh-Hans")
        time.sleep(0.2)
        controller.cancel()
        deadline = time.monotonic() + 60
        while controller.active and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        report["cancel_returns_to_idle"] = not controller.active
    finally:
        engine.stop()
        tasks.shutdown()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = (
        all(case["status"] == "ok" and case["structure_preserved"] for case in report["cases"])
        and report.get("capture_exclusion") == "enforced"
        and report.get("cancel_returns_to_idle") is True
        and report.get("device") == "CUDA"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
