"""run manifest 的代码版本必须来自仓库真实状态，不能手填。"""

import subprocess

from scripts.training.code_version import _read_git_dir, code_version, resolve_git


def test_reports_a_real_commit_for_this_repository():
    result = code_version()

    assert result["source"] in {"git", "git-dir"}
    assert result["commit"] and len(result["commit"]) == 40
    assert all(ch in "0123456789abcdef" for ch in result["commit"])


def test_git_binary_and_git_dir_agree():
    """两条路径必须指向同一个 commit，否则回退实现就是错的。"""
    if resolve_git() is None:
        return
    from scripts.training.code_version import REPO_ROOT

    assert _read_git_dir(REPO_ROOT) == code_version()["commit"]


def test_dirty_state_is_reported_when_git_is_available():
    result = code_version()

    if result["source"] == "git":
        assert isinstance(result["dirty"], bool)
    else:
        # Without the binary we cannot know, and must say so rather than guess.
        assert result["dirty"] is None


def test_missing_repository_is_reported_as_unavailable(tmp_path):
    """不得沿目录树向上找到父仓库，把运行归因到不相干的代码。"""
    result = code_version(tmp_path)

    assert result["commit"] is None
    assert result["source"] == "unavailable"


def test_head_pointing_straight_at_a_sha_is_read(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    sha = "a" * 40
    (git_dir / "HEAD").write_text(sha, encoding="utf-8")

    assert _read_git_dir(tmp_path) == sha


def test_packed_refs_are_consulted(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    sha = "b" * 40
    (git_dir / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{sha} refs/heads/main\n", encoding="utf-8"
    )

    assert _read_git_dir(tmp_path) == sha


def test_resolved_git_binary_actually_runs():
    binary = resolve_git()
    if binary is None:
        return

    output = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)

    assert output.returncode == 0
    assert "git version" in output.stdout
