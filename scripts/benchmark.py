"""20-line, 1080p synthetic acceptance fixture; blocks external Python sockets."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken, merge_lines
from screen_translator.engines import OcrEngine, TranslationEngine
from screen_translator.graphics import OverlayRenderer, to_array
from screen_translator.models import DEFAULT_SHARED_MODEL_ROOT

LINES = [
    "Open settings to change your keyboard shortcut.",
    "Save your changes before closing this window.",
    "The download will resume after the connection is restored.",
    "Your screenshots are processed entirely on this computer.",
    "Select an area containing the text you want to translate.",
    "Press Escape to return to your desktop.",
    "The application continues running in the system tray.",
    "Check available disk space before downloading the model.",
    "Click anywhere to switch between the original and translation.",
    "You can change the model directory in settings.",
    "設定を開いてください。",
    "変更を保存してからウィンドウを閉じてください。",
    "설정을 열어 주세요.",
    "변경 사항을 저장해 주세요.",
    "Bonjour, veuillez ouvrir les paramètres.",
    "Enregistrez vos modifications avant de fermer la fenêtre.",
    "Bitte öffnen Sie die Einstellungen.",
    "Speichern Sie Ihre Änderungen vor dem Schließen.",
    "Abra la configuración para cambiar el idioma.",
    "Guarde los cambios antes de cerrar la ventana.",
]


def main():
    _app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgun.ttf")
    out = Path("build/fixtures")
    out.mkdir(parents=True, exist_ok=True)
    source = QImage(1920, 1080, QImage.Format.Format_RGB888)
    source.fill(QColor("#f5f5f5"))
    painter = QPainter(source)
    font = QFont("Microsoft YaHei UI")
    font.setFamilies(["Microsoft YaHei UI", "Malgun Gothic"])
    font.setPixelSize(26)
    painter.setFont(font)
    painter.setPen(QColor("#202020"))
    for i, text in enumerate(LINES):
        painter.drawText(40, 45 + i * 50, text)
    painter.end()
    source.save(str(out / "20-lines-1080p.png"))
    connect = socket.socket.connect

    def offline(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("Unexpected external connection")
        return connect(sock, address)

    socket.socket.connect = offline
    token = CancellationToken()
    ocr = OcrEngine(DEFAULT_SHARED_MODEL_ROOT.resolve(), allow_cpu=True)
    translator = TranslationEngine(DEFAULT_SHARED_MODEL_ROOT.resolve())
    results = []
    try:
        for run in range(2):
            start = time.monotonic()
            if run == 0:
                threading.Thread(target=translator.start, args=(token, lambda _: None), daemon=True).start()
            ocr_result = ocr.recognize(
                cv2.cvtColor(to_array(source), cv2.COLOR_RGB2BGR), "auto", token, lambda _: None
            )
            blocks = merge_lines(ocr_result.lines)
            ocr_time = time.monotonic() - start
            translated = translator.translate(blocks, token, lambda _: None, "auto", "zh-Hans")
            result = OverlayRenderer().render(source, translated, token, "zh-Hans")
            result.save(str(out / "20-lines-translated.png"))
            record = {
                "run": run,
                "lines": sum(len(b.lines) for b in blocks),
                "blocks": len(blocks),
                "ocr_seconds": round(ocr_time, 2),
                "total_seconds": round(time.monotonic() - start, 2),
                "ocr_mode": ocr_result.device,
                "ocr_timings_ms": ocr_result.timings_ms,
            }
            results.append(record)
            print(record, flush=True)
    finally:
        translator.stop()
        (out / "benchmark.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
