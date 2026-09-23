"""Where bundled files live, in both a source tree and a frozen build.

Duplicated from `theme.asset_path` on purpose: `design` imports nothing
from the rest of the application, so that the import-direction test can
be absolute rather than "absolute except for this one". It is four lines.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def asset_path(name: str) -> str:
    return (resource_root() / "screen_translator" / "assets" / name).as_posix()
