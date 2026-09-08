"""The location-pinned subprocess runner every shell-out goes through.

These are unit tests for the primitive itself: that ``root`` selects the
repository and that git's location variables cannot override it. The end-to-end
consequences — detection describing the right repo, and ``add`` committing into it
— live in ``test_base.py``'s *environment independence* section.
"""

import os
import subprocess
from pathlib import Path

import pytest

from planners import proc


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_pinned_env_drops_only_the_location_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Location variables go; everything else — config overrides included — stays.

    ``GIT_CONFIG_GLOBAL``/``GIT_CEILING_DIRECTORIES`` change what git *reads*, not
    which repository it acts on, and the suite's isolation fixture depends on them
    surviving. Stripping them would silently un-insulate every test.
    """
    monkeypatch.setenv("GIT_DIR", "/nowhere/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/nowhere")
    monkeypatch.setenv("GIT_INDEX_FILE", "/nowhere/.git/index")
    monkeypatch.setenv("PLANNERS_CANARY", "kept")

    env = proc.pinned_env()

    assert not [k for k in proc.LOCATION_ENV if k in env]
    assert env["PLANNERS_CANARY"] == "kept"
    assert env["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"]
    assert env["GIT_CEILING_DIRECTORIES"] == os.environ["GIT_CEILING_DIRECTORIES"]


def test_run_uses_root_not_the_process_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``root`` names the repo, so the caller's cwd is irrelevant."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = proc.run(
        repo, ["git", "rev-parse", "--absolute-git-dir"], capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (repo / ".git").resolve()


def test_run_ignores_an_ambient_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inherited GIT_DIR outranks ``cwd`` in git — but never reaches it here."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo)
    other = tmp_path / "other"
    other.mkdir()
    _init_git(other)

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    result = proc.run(
        repo, ["git", "rev-parse", "--absolute-git-dir"], capture_output=True
    )

    assert Path(result.stdout.strip()).resolve() == (repo / ".git").resolve()


def test_run_reports_a_non_zero_exit_rather_than_raising(tmp_path: Path) -> None:
    """No ``check=True``: callers decide what a failure means (often "no such ref")."""
    result = proc.run(tmp_path, ["git", "rev-parse", "--git-dir"], capture_output=True)

    assert result.returncode != 0


def test_run_propagates_a_missing_binary(tmp_path: Path) -> None:
    """A missing tool raises, so each caller can translate it into its own idiom."""
    with pytest.raises(FileNotFoundError):
        proc.run(tmp_path, ["planners-not-a-real-binary"], capture_output=True)
