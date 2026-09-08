"""Mainline detection and the add/finalize base-branch guard.

Every test builds a real git repo, because the whole point of the module is what
git's refs say — a mocked ``subprocess`` would only assert that the code calls the
commands it calls. The ``_isolate_git_env`` autouse fixture keeps the machine's
global config and any enclosing repo out of the way (see ``conftest.py``).
"""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import base as base_mod
from planners.cli import app

runner = CliRunner()


def _init_git(path: Path, *, branch: str = "main") -> None:
    """A committer-configured repo on ``branch``, with no commits yet."""
    subprocess.run(
        ["git", "init", "-q", "--initial-branch", branch], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _commit(path: Path, message: str = "init") -> None:
    """An empty commit, so HEAD is born and branches actually exist."""
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", message], cwd=path, check=True
    )


def _branch(path: Path, name: str) -> None:
    """Create and switch to ``name``."""
    subprocess.run(["git", "checkout", "-q", "-b", name], cwd=path, check=True)


def _set_origin_head(path: Path, branch: str) -> None:
    """Record ``origin/HEAD`` -> ``branch`` without needing a reachable remote.

    ``git remote set-head --auto`` would query the network; writing the symbolic
    ref directly produces the same local state a clone leaves behind, which is
    what detection actually reads.
    """
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/repo.git"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{branch}", "HEAD"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            f"refs/remotes/origin/{branch}",
        ],
        cwd=path,
        check=True,
    )


# --- detection ---------------------------------------------------------------


def test_detect_unresolved_outside_a_git_repo(tmp_path: Path) -> None:
    mainline = base_mod.detect(tmp_path)
    assert mainline.resolved is False
    # Inert, not an error: a non-repo must never block a plan commit.
    assert base_mod.guard_message(mainline, "plan [add]") is None


def test_detect_unborn_head_is_inert(tmp_path: Path) -> None:
    """A fresh repo has no mainline to be off of, so the first add is never blocked."""
    _init_git(tmp_path)
    mainline = base_mod.detect(tmp_path)
    assert mainline.unborn is True
    assert mainline.resolved is False
    assert base_mod.guard_message(mainline, "plan [add]") is None


def test_detect_falls_back_to_local_main_and_is_thin(tmp_path: Path) -> None:
    """No origin/HEAD -> guess by name, and say the detection was a guess."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    mainline = base_mod.detect(tmp_path)
    assert mainline.branches == ("main",)
    assert mainline.current == "main"
    assert mainline.thin is True
    assert mainline.on_mainline is True


def test_detect_prefers_origin_head_over_conventional_names(tmp_path: Path) -> None:
    """A repo whose default branch is named nothing conventional is still resolved."""
    _init_git(tmp_path, branch="trunk")
    _commit(tmp_path)
    _set_origin_head(tmp_path, "trunk")
    mainline = base_mod.detect(tmp_path)
    assert mainline.branches == ("trunk",)
    # origin/HEAD answered, so detection is not a guess.
    assert mainline.thin is False


def test_detect_accepts_dev_and_default_as_a_set(tmp_path: Path) -> None:
    """Both mainlines are accepted; a plan on `main` in a dev repo is not lost."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _set_origin_head(tmp_path, "main")
    _branch(tmp_path, "dev")
    mainline = base_mod.detect(tmp_path)
    assert mainline.branches == ("dev", "main")
    assert mainline.current == "dev"
    assert mainline.on_mainline is True


def test_detect_reports_feature_branch_as_off_mainline(tmp_path: Path) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    mainline = base_mod.detect(tmp_path)
    assert mainline.current == "feature/x"
    assert mainline.on_mainline is False
    message = base_mod.guard_message(mainline, "plan [add]")
    assert message is not None
    assert "feature/x" in message
    assert "--allow-branch" in message


def test_detect_flags_detached_head_distinctly(tmp_path: Path) -> None:
    """A detached HEAD is worse than a feature branch, and says so."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", sha], cwd=tmp_path, check=True)
    mainline = base_mod.detect(tmp_path)
    assert mainline.detached is True
    assert mainline.current is None
    message = base_mod.guard_message(mainline, "plan [add]")
    assert message is not None
    assert "detached" in message
    assert "lost on the next checkout" in message


def test_guard_message_notes_stale_origin_head_remedy(tmp_path: Path) -> None:
    """When detection is thin, the refusal names the command that fixes it."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    message = base_mod.guard_message(base_mod.detect(tmp_path), "plan [add]")
    assert message is not None
    assert "git remote set-head origin --auto" in message


# --- the add / finalize guard ------------------------------------------------


def test_add_refuses_on_a_feature_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan"])
    assert result.exit_code == 1
    assert "not a mainline branch" in result.output
    # Refused before writing: no half-scaffolded plan directory is left behind.
    assert not (tmp_path / ".planners" / "plans").exists()


def test_add_allow_branch_overrides_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan", "--allow-branch"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-my-plan" / "plan.md").exists()


def test_add_allows_a_mainline_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan"])
    assert result.exit_code == 0, result.output
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "plan [add]: 000 - my-plan" in log


def test_add_no_commit_is_unguarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-commit makes no commit, so no branch can strand one."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-my-plan" / "plan.md").exists()


def test_add_defer_is_unguarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Staging writes no commit; the guard belongs on finalize, which does."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _branch(tmp_path, "feature/x")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan", "--defer"])
    assert result.exit_code == 0, result.output
    assert list((tmp_path / ".planners" / "staging").glob("*-my-plan/plan.md"))


def test_finalize_refuses_on_a_feature_branch_and_keeps_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused finalize leaves the batch staged and recoverable."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "my-plan", "--defer"]).exit_code == 0
    _branch(tmp_path, "feature/x")

    result = runner.invoke(app, ["finalize"])
    assert result.exit_code == 1
    assert "not a mainline branch" in result.output
    # Nothing was materialized out of staging.
    assert list((tmp_path / ".planners" / "staging").glob("*-my-plan/plan.md"))
    assert not (tmp_path / ".planners" / "plans").exists()


def test_add_is_inert_in_a_repo_with_no_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The very first plan in a fresh repo is not blocked by an unborn HEAD."""
    _init_git(tmp_path, branch="main")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["add", "my-plan"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-my-plan" / "plan.md").exists()


# --- the `base` command ------------------------------------------------------


def test_base_prints_the_first_mainline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _set_origin_head(tmp_path, "main")
    _branch(tmp_path, "dev")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["base"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "dev"


def test_base_all_prints_every_mainline_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _set_origin_head(tmp_path, "main")
    _branch(tmp_path, "dev")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["base", "--all"])
    assert result.exit_code == 0, result.output
    assert result.stdout.split() == ["dev", "main"]


def test_base_exits_nonzero_outside_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A script can branch on the exit code; stdout stays empty."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["base"])
    assert result.exit_code == 1
    assert result.stdout.strip() == ""


def test_base_exits_nonzero_with_no_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["base"])
    assert result.exit_code == 1
    assert "no commits yet" in result.output
