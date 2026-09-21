"""Resolve the real commit SHA for run manifests.

Manifests must never carry a hand-typed version string. This reads the actual
repository state, preferring the git binary (which also reports whether the
working tree is dirty) and falling back to parsing `.git` directly when git is
not on PATH.

A dirty tree is reported as such: the SHA alone would not describe the code
that produced the run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Git is frequently installed but missing from PATH on Windows.
FALLBACK_GIT = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def resolve_git() -> str | None:
    found = shutil.which("git")
    if found:
        return found
    for candidate in FALLBACK_GIT:
        if os.path.isfile(candidate):
            return candidate
    return None


def _read_git_dir(repo_root: Path) -> str | None:
    """Parse .git/HEAD without invoking git."""
    head = repo_root / ".git" / "HEAD"
    if not head.is_file():
        return None
    content = head.read_text(encoding="utf-8").strip()
    if not content.startswith("ref:"):
        return content or None
    ref = content.split(":", 1)[1].strip()
    direct = repo_root / ".git" / ref
    if direct.is_file():
        return direct.read_text(encoding="utf-8").strip() or None
    packed = repo_root / ".git" / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def code_version(repo_root: Path | None = None) -> dict:
    """Return {commit, dirty, source} describing the code that is running."""
    root = Path(repo_root or REPO_ROOT)
    if not (root / ".git").exists():
        # Without this guard git would walk up and report a parent repository,
        # silently attributing a run to code it did not come from.
        return {"commit": None, "dirty": None, "source": "unavailable"}
    git = resolve_git()
    if git:
        try:
            commit = subprocess.run(
                [git, "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                timeout=30, check=True,
            ).stdout.strip()
            status = subprocess.run(
                [git, "status", "--porcelain"], cwd=root, capture_output=True, text=True,
                timeout=60, check=True,
            ).stdout.strip()
            return {"commit": commit, "dirty": bool(status), "source": "git"}
        except (subprocess.SubprocessError, OSError):
            pass
    commit = _read_git_dir(root)
    # Without git we cannot tell whether the tree was modified.
    return {"commit": commit, "dirty": None, "source": "git-dir" if commit else "unavailable"}


if __name__ == "__main__":
    import json

    print(json.dumps(code_version(), ensure_ascii=False, indent=2))
