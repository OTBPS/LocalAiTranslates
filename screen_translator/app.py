import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from . import design
from .core import local_dir
from .instance import InstanceCoordinator
from .native import app_theme_is_light
from .settings import Settings
from .theme import create_app_icon
from .version import __version__


def main():
    import multiprocessing

    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        import json
        import traceback

        from .diagnostics import main as diagnose

        index = sys.argv.index("--self-test")
        root, report = sys.argv[index + 1 : index + 3]
        try:
            diagnose(root, report)
            return 0
        except Exception:
            Path(report).write_text(
                json.dumps({"error": traceback.format_exc()}, ensure_ascii=False), encoding="utf-8"
            )
            return 1
    app = QApplication(sys.argv)
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    # Follow the system appearance, decided once at start-up. Switching
    # at run time would mean re-polishing the whole widget tree and
    # re-running every self-painted control for the sake of not
    # restarting; see the "not doing" list in the plan.
    design.apply(app, theme=design.theme_for(dark=not app_theme_is_light()))
    app.setWindowIcon(create_app_icon())
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ScreenTranslator")
    app.setApplicationVersion(__version__)
    command = "show-settings" if "--show-settings" in sys.argv else "ping"
    coordinator = InstanceCoordinator(local_dir())
    if not coordinator.acquire_or_notify(command):
        return 0
    from .controller import Controller
    from .onboarding import intent_from_arguments

    controller = Controller(app, Settings, intent=intent_from_arguments(sys.argv))
    coordinator.command_received.connect(
        lambda received: controller.activate_settings() if received == "show-settings" else None
    )
    app.aboutToQuit.connect(coordinator.close)
    app.aboutToQuit.connect(controller.host_service.stop)
    # Bound lazily: changing the model in settings replaces the backend.
    app.aboutToQuit.connect(lambda: controller.backend.stop())
    if command == "show-settings":
        QTimer.singleShot(0, controller.activate_settings)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
