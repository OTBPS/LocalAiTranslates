"""Benchmark the complete offline OCR, translation, and rendering pipeline."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken, merge_lines
from screen_translator.graphics import OverlayRenderer, to_array
from screen_translator.models import DEFAULT_MODEL_ID, DEFAULT_SHARED_MODEL_ROOT, TRANSLATION_MODELS
from screen_translator.ocr_engine import OcrEngine
from screen_translator.translation_engine import TranslationEngine
from screen_translator.version import __version__


def block_external_network() -> None:
    original_connect = socket.socket.connect

    def offline(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError(f"benchmark attempted an external connection: {address[0]}")
        return original_connect(sock, address)

    socket.socket.connect = offline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--models", type=Path, default=DEFAULT_SHARED_MODEL_ROOT)
    parser.add_argument("--output", type=Path, default=Path("build/image-benchmark.json"))
    parser.add_argument("--rendered", type=Path, default=Path("build/image-benchmark-translated.png"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--source", default="auto")
    parser.add_argument("--target", default="zh-Hans")
    parser.add_argument("--model", choices=tuple(TRANSLATION_MODELS), default=DEFAULT_MODEL_ID)
    parser.add_argument("--parallel-slots", type=int, choices=(1, 2), default=1)
    parser.add_argument("--prewarm-ocr", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    source = QImage(str(args.image.resolve()))
    if source.isNull():
        raise FileNotFoundError(f"unable to load image: {args.image}")
    block_external_network()

    image = cv2.cvtColor(to_array(source), cv2.COLOR_RGB2BGR)
    token = CancellationToken()
    ocr = OcrEngine(args.models.resolve(), allow_cpu=True)
    translator = TranslationEngine(
        args.models.resolve(), model_id=args.model, parallel_slots=args.parallel_slots
    )
    renderer = OverlayRenderer()
    results = []

    try:
        if args.prewarm_ocr:
            ocr.warmup(args.source, token, lambda _message: None)
        for run in range(args.runs):
            started = time.monotonic()
            if run == 0:
                threading.Thread(
                    target=translator.start,
                    args=(token, lambda _message: None),
                    name="benchmark-qwen-warmup",
                    daemon=True,
                ).start()

            ocr_started = time.monotonic()
            ocr_result = ocr.recognize(image, args.source, token, lambda _message: None)
            ocr_finished = time.monotonic()

            merge_started = time.monotonic()
            blocks = merge_lines(ocr_result.lines)
            merge_finished = time.monotonic()

            translation_started = time.monotonic()
            translated = translator.translate(
                blocks,
                token,
                lambda _message: None,
                args.source,
                args.target,
            )
            translation_finished = time.monotonic()

            render_started = time.monotonic()
            rendered = renderer.render(source, translated, token, args.target)
            render_finished = time.monotonic()

            record = {
                "run": run,
                "kind": "cold" if run == 0 else "warm",
                "app_version": __version__,
                "model_id": args.model,
                "translation_mode": translator.mode,
                "parallel_slots": args.parallel_slots,
                "source_language": args.source,
                "target_language": args.target,
                "image_pixels": [source.width(), source.height()],
                "detected_language": ocr_result.detected_language,
                "ocr_device": ocr_result.device,
                "lines": len(ocr_result.lines),
                "blocks": len(blocks),
                "recognized_characters": sum(len(line.text) for line in ocr_result.lines),
                "ocr_seconds": round(ocr_finished - ocr_started, 3),
                "merge_seconds": round(merge_finished - merge_started, 3),
                "translation_seconds": round(translation_finished - translation_started, 3),
                "render_seconds": round(render_finished - render_started, 3),
                "total_seconds": round(render_finished - started, 3),
                "ocr_timings_ms": ocr_result.timings_ms,
                "translation_metrics": dict(translator.last_metrics),
                "translations": [
                    {
                        "block_id": item.block.block_id,
                        "source_text": item.block.text,
                        "translated_text": item.text,
                    }
                    for item in translated
                ],
            }
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if run == args.runs - 1:
                args.rendered.parent.mkdir(parents=True, exist_ok=True)
                rendered.save(str(args.rendered))
    finally:
        translator.stop()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
