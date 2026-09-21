"""Render the settings window offscreen for repeatable visual review."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.core import LANGUAGE_NAMES, Config  # noqa: E402
from screen_translator.settings import Settings  # noqa: E402
from screen_translator.theme import application_stylesheet  # noqa: E402


class PreviewController:
    def __init__(self, model_dir: Path):
        self.config = Config(
            hotkey="Ctrl+Alt+Q",
            model_dir=str(model_dir),
            source_language="en",
            target_language="zh-Hans",
            translation_model="qwen3-8b-q5-k-m",
            startup=False,
            allow_cpu=False,
        )
        self.busy = False
        self.download_token = None
        self.detected_source_language = None
        self.ocr = SimpleNamespace(mode="CUDA")
        self.translator = SimpleNamespace(mode="CUDA")

    def language_pair_text(self):
        return (
            f"{LANGUAGE_NAMES[self.config.source_language]} → "
            f"{LANGUAGE_NAMES[self.config.target_language]}"
        )

    def set_language_pair(self, source, target):
        self.config = replace(self.config, source_language=source, target_language=target)

    def refresh_language_actions(self):
        return None

    def replace_engines(self):
        return None

    def toggle(self):
        return None


def main() -> int:
    root = PROJECT_ROOT
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else root / "artifacts" / "ui" / "settings-ios18.png"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(application_stylesheet())
    window = Settings(PreviewController(root / "models"))
    if len(sys.argv) >= 4:
        window.resize(int(sys.argv[2]), int(sys.argv[3]))
    window.show()
    app.processEvents()
    if not window.grab().save(str(output)):
        raise RuntimeError(f"无法写入预览图：{output}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
