"""Synthetic fixture only: no user's screen/text is captured or logged."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken, merge_lines
from screen_translator.engines import OcrEngine, TranslationEngine
from screen_translator.graphics import OverlayRenderer, to_array
from screen_translator.models import DEFAULT_MODEL_ID, DEFAULT_SHARED_MODEL_ROOT


def _emit(*values):
    """Best-effort diagnostic output; windowed builds do not own a console."""
    try:
        print(*values, flush=True)
    except OSError:
        pass


def main(root=None, report=None, model_id=DEFAULT_MODEL_ID):
    import socket

    connect = socket.socket.connect

    def offline_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("External network attempted during inference")
        return connect(sock, address)

    socket.socket.connect = offline_connect
    _app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    root = Path(root or DEFAULT_SHARED_MODEL_ROOT)
    results = []
    image = QImage(1000, 420, QImage.Format.Format_RGB888)
    image.fill(QColor("white"))
    painter = QPainter(image)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(28)
    painter.setFont(font)
    painter.setPen(QColor("black"))
    for y, text in enumerate(
        [
            "Open the settings to change your keyboard shortcut.",
            "Save changes before closing this window.",
            "設定を開いてください。",
            "Bonjour, veuillez ouvrir les paramètres.",
        ]
    ):
        painter.drawText(25, 50 + y * 80, text)
    painter.end()
    token = CancellationToken()

    def progress(message):
        _emit(message)

    engine = TranslationEngine(root, model_id=model_id)
    ocr = OcrEngine(root, allow_cpu=True)
    try:
        for run in range(2):
            start = time.monotonic()
            ocr_result = ocr.recognize(
                cv2.cvtColor(to_array(image), cv2.COLOR_RGB2BGR), "auto", token, progress
            )
            blocks = merge_lines(ocr_result.lines)
            ocr_seconds = time.monotonic() - start
            assert blocks, "No OCR text"
            translated = engine.translate(blocks, token, progress, "auto", "zh-Hans")
            result = OverlayRenderer().render(image, translated, token, "zh-Hans")
            assert len(translated) == len(blocks)
            record = {
                "run": run,
                "seconds": round(time.monotonic() - start, 2),
                "ocr_seconds": round(ocr_seconds, 2),
                "blocks": len(blocks),
                "ocr_mode": ocr_result.device,
                "ocr_timings_ms": ocr_result.timings_ms,
                "mode": engine.mode,
            }
            results.append(record)
            _emit(record)
            for item in translated:
                _emit(item.block.text, "=>", item.text)
            result.save(str(root.parent / "build" / "smoke-result.png"))
    finally:
        engine.stop()
        if report:
            Path(report).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
