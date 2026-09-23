"""What this build can actually do.

The client edition ships without PaddleOCR, CUDA and llama.cpp so that a
laptop only has to install tens of megabytes instead of several gigabytes.
That build can still import every module — the model runtimes are imported
lazily — so something has to state plainly that local inference is not
available, rather than letting a capture fail halfway through.

The answer cannot change while the process runs: a payload is either in the
bundle or it is not.  It is therefore computed once and cached.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path


def runtime_root() -> Path:
    """The directory holding bundled runtimes, in both frozen and source trees."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


@lru_cache(maxsize=1)
def llama_runtime_available() -> bool:
    return (runtime_root() / "runtime" / "llama" / "llama-server.exe").is_file()


@lru_cache(maxsize=1)
def ocr_runtime_available() -> bool:
    # ``find_spec`` answers the question without paying for the import, which
    # costs seconds and allocates GPU memory.
    try:
        return importlib.util.find_spec("paddleocr") is not None
    except (ImportError, ValueError):
        return False


def local_runtime_available() -> bool:
    return llama_runtime_available() and ocr_runtime_available()


def describe_missing_runtime() -> str:
    missing = []
    if not ocr_runtime_available():
        missing.append("PaddleOCR")
    if not llama_runtime_available():
        missing.append("llama.cpp")
    if not missing:
        return ""
    return f"此版本未包含本地推理运行时（缺少 {'、'.join(missing)}），请切换到远程主机模式"
