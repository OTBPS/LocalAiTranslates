"""Synthetic, local-only OCR language routing smoke test."""

import json
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken
from screen_translator.engines import OcrEngine
from screen_translator.graphics import to_array
from screen_translator.models import DEFAULT_SHARED_MODEL_ROOT

SAMPLES = {
    "zh-Hans": ("打开设置并保存更改", ["Microsoft YaHei UI"]),
    "en": ("Open settings and save your changes", ["Segoe UI"]),
    "ja": ("設定を開いて変更を保存してください。", ["Yu Gothic UI", "Meiryo UI"]),
    "ko": ("설정을 열고 변경 사항을 저장하세요", ["Malgun Gothic"]),
}


def main():
    _app = QApplication.instance() or QApplication([])
    for font_path in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/YuGothR.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ):
        QFontDatabase.addApplicationFont(font_path)
    output = Path("build/fixtures/languages")
    output.mkdir(parents=True, exist_ok=True)
    engine = OcrEngine(DEFAULT_SHARED_MODEL_ROOT.resolve())
    token = CancellationToken()
    report = {}
    for expected, (text, families) in SAMPLES.items():
        image = QImage(1100, 180, QImage.Format.Format_RGB888)
        image.fill(QColor("white"))
        painter = QPainter(image)
        font = QFont()
        font.setFamilies(families)
        font.setPixelSize(44)
        painter.setFont(font)
        painter.setPen(QColor("black"))
        painter.drawText(30, 105, text)
        painter.end()
        path = output / f"{expected}.png"
        image.save(str(path))
        result = engine.recognize(
            cv2.cvtColor(to_array(image), cv2.COLOR_RGB2BGR), "auto", token, lambda _: None
        )
        report[expected] = {
            "detected": result.detected_language,
            "device": result.device,
            "timings_ms": result.timings_ms,
            "line_count": len(result.lines),
        }
        if result.detected_language != expected or not result.lines:
            raise AssertionError(f"{expected} routing failed: {report[expected]}")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
