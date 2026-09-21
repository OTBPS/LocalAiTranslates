"""Privacy-preserving local application logging configuration."""

import logging
from logging.handlers import RotatingFileHandler

from .core import local_dir


def configure_logging(level: str) -> None:
    log_directory = local_dir() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_directory / "app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(getattr(logging, str(level).upper(), logging.WARNING))
    performance = logging.getLogger("screen_translator.performance")
    if not performance.handlers:
        performance.addHandler(handler)
    performance.setLevel(logging.INFO)
    performance.propagate = False
