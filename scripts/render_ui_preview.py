"""Render the settings window offscreen for repeatable visual review."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.config_store import ConfigStore  # noqa: E402
from screen_translator.core import LANGUAGE_NAMES, Config  # noqa: E402
from screen_translator.feedback import Occupancy  # noqa: E402
from screen_translator.inference import InferenceCoordinator  # noqa: E402
from screen_translator.manual_translation import ManualTranslationController  # noqa: E402
from screen_translator.settings import Settings  # noqa: E402
from screen_translator.tasks import TaskRunner  # noqa: E402
from screen_translator.theme import application_stylesheet  # noqa: E402
from screen_translator.version import __version__  # noqa: E402


class PreviewController:
    """Everything the settings window reads, and nothing else.

    Kept in step with the real controller by
    ``tests/test_ui_preview.py``; without that, this script rots silently
    because nothing else constructs the window outside the application.
    """

    def __init__(self, model_dir: Path):
        self.configuration = ConfigStore(
            Config(
                hotkey="Ctrl+Alt+Q",
                model_dir=str(model_dir),
                source_language="en",
                target_language="zh-Hans",
                translation_model="qwen3-8b-q5-k-m",
                startup=False,
                allow_cpu=False,
            ),
            writer=lambda _config: None,
        )
        self.busy = False
        self.download_token = None
        self.detected_source_language = None
        self.ocr = SimpleNamespace(mode="CUDA")
        self.translator = SimpleNamespace(mode="CUDA")
        self.backend = SimpleNamespace(
            kind="local", ready=lambda: True, describe=lambda: "本地模型就绪"
        )
        self.host_service = SimpleNamespace(
            status=SimpleNamespace(describe=lambda: "远程服务未启用")
        )
        self.hotkey = SimpleNamespace(current="Ctrl+Alt+Q")
        self.inference = InferenceCoordinator(lambda: self.translator)
        self.manual = ManualTranslationController(self.inference, TaskRunner())

    @property
    def config(self):
        return self.configuration.current

    def occupancy(self):
        return Occupancy()

    def language_pair_text(self):
        return (
            f"{LANGUAGE_NAMES[self.config.source_language]} → "
            f"{LANGUAGE_NAMES[self.config.target_language]}"
        )

    def set_language_pair(self, source, target):
        self.configuration.update(source_language=source, target_language=target)

    def refresh_language_actions(self):
        return None

    def replace_engines(self):
        return None

    def apply_host_service(self):
        return None

    def toggle(self):
        return None


def main() -> int:
    root = PROJECT_ROOT
    # Named for the current version rather than a design direction retired
    # three versions ago.
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else root / "artifacts" / "ui" / f"settings-v{__version__}.png"
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
    if len(sys.argv) >= 5:
        window.tabs.setCurrentIndex(int(sys.argv[4]))
    window.show()
    app.processEvents()
    if not window.grab().save(str(output)):
        raise RuntimeError(f"无法写入预览图：{output}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
