"""Mainline detection and the add/finalize base-branch guard.

Every test builds a real git repo, because the whole point of the module is what
git's refs say — a mocked ``subprocess`` would only assert that the code calls the
commands it calls. The ``_isolate_git_env`` autouse fixture keeps the machine's
global config and any enclosing repo out of the way (see ``conftest.py``).
"""

import os
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


def _unredirected(path: Path, args: list[str]) -> str:
    """Run a read-only git command against ``path``, immune to an ambient GIT_DIR.

    The environment-independence tests below *export* ``GIT_DIR``, which would
    redirect the assertions themselves — ``git log`` with ``cwd=repo`` would report
    the other repo's history and the test could pass for the wrong reason. Dropping
    the variable here (rather than reusing the package's own sanitizing runner)
    keeps the check independent of the code under test.
    """
    env = {k: v for k, v in os.environ.items() if k != "GIT_DIR"}
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


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


def test_base_notes_the_remedy_when_resolution_is_thin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guessed-by-name answer says so, and names the command that fixes it."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)  # no origin/HEAD -> fallback to the local 'main'
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["base"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "main"
    assert "git remote set-head origin --auto" in result.output


def test_base_accepts_an_explicit_repo_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positional argument is honored, not silently replaced by the cwd."""
    repo = tmp_path / "elsewhere"
    repo.mkdir()
    _init_git(repo, branch="main")
    _commit(repo)
    _set_origin_head(repo, "main")
    # Stand somewhere that is deliberately NOT a git repo, so a cwd-based
    # implementation would resolve nothing and fail this test.
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = runner.invoke(app, ["base", str(repo)])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "main"


# --- environment independence ------------------------------------------------


def test_detection_ignores_an_ambient_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inherited GIT_DIR must not redirect detection to another repository.

    GIT_DIR outranks ``cwd``, so without stripping it the guard would clear a
    branch it never looked at — a guard that fails *open*, which is worse than no
    guard. Git exports GIT_DIR to its own hooks, so this is a reachable state.
    """
    other = tmp_path / "other"
    other.mkdir()
    _init_git(other, branch="dev")
    _commit(other)

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo, branch="main")
    _commit(repo)
    _branch(repo, "feature/x")

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    mainline = base_mod.detect(repo)
    # Describes `repo` (on feature/x, off its mainline), not `other` (on dev).
    assert mainline.current == "feature/x"
    assert mainline.on_mainline is False
    assert base_mod.guard_message(mainline, "plan [add]") is not None


def test_add_refuses_despite_an_ambient_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: the guard still refuses, and nothing is written anywhere."""
    other = tmp_path / "other"
    other.mkdir()
    _init_git(other, branch="dev")
    _commit(other)

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo, branch="main")
    _commit(repo)
    _branch(repo, "feature/x")

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["add", "my-plan"])
    assert result.exit_code == 1
    assert "not a mainline branch" in result.output
    assert not (repo / ".planners" / "plans").exists()
    # The unrelated repo is untouched — no stray plan commit landed in it.
    assert "plan [add]" not in _unredirected(other, ["log", "--oneline"])


def test_add_commits_into_the_repo_it_ran_in_despite_an_ambient_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit follows the working directory, never an inherited GIT_DIR.

    The commit-side counterpart of the detection test above, and the reproduction
    of the reported bug: HEAD here is on ``dev``, so the guard legitimately clears
    the repo — and the commit was then still redirected, landing ``plan [add]`` in
    the *other* repo's history and leaving this one with orphaned, untracked
    ``.planners`` files. Git exports ``GIT_DIR`` to every hook it runs, so this is
    a state a wrapper or hook reaches without anyone setting it deliberately.
    """
    other = tmp_path / "other"
    other.mkdir()
    _init_git(other, branch="dev")
    _commit(other)

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git(repo, branch="dev")
    _commit(repo)

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["add", "my-plan"])
    assert result.exit_code == 0, result.output

    # The plan commit landed here...
    assert "plan [add]: 000 - my-plan" in _unredirected(repo, ["log", "--oneline"])
    # ...and only here.
    assert "plan [add]" not in _unredirected(other, ["log", "--oneline"])
    # Nothing orphaned: the plan and the index are committed, not left untracked.
    assert _unredirected(repo, ["status", "--porcelain"]).strip() == ""


# --- resolution edge cases ---------------------------------------------------


def test_dangling_origin_head_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symbolic ref to a missing branch must not become the advertised remedy.

    ``git symbolic-ref`` reports a dangling target happily. Trusting it names a
    branch the user cannot check out, and marks the answer confident.
    """
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/repo.git"],
        cwd=tmp_path,
        check=True,
    )
    # Point origin/HEAD at a branch that does not exist.
    subprocess.run(
        [
            "git",
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/ghost",
        ],
        cwd=tmp_path,
        check=True,
    )

    mainline = base_mod.detect(tmp_path)
    assert "ghost" not in mainline.branches
    # Falls back to the local 'main', and admits the answer was a guess.
    assert mainline.branches == ("main",)
    assert mainline.thin is True


def test_detect_falls_back_to_master(tmp_path: Path) -> None:
    """The second fallback name resolves, not only the first."""
    _init_git(tmp_path, branch="master")
    _commit(tmp_path)
    mainline = base_mod.detect(tmp_path)
    assert mainline.branches == ("master",)
    assert mainline.on_mainline is True


def test_detect_unresolved_when_head_is_born_but_nothing_matches(
    tmp_path: Path,
) -> None:
    """Commits exist, but no dev, no origin/HEAD, and no main/master -> inert.

    Distinct from the unborn and non-repo paths, which return earlier.
    """
    _init_git(tmp_path, branch="trunk")
    _commit(tmp_path)
    mainline = base_mod.detect(tmp_path)
    assert mainline.resolved is False
    assert mainline.unborn is False
    assert base_mod.guard_message(mainline, "plan [add]") is None


def test_detect_is_unresolved_without_git_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No git binary must degrade to inert, never raise."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-bin"))

    mainline = base_mod.detect(tmp_path)
    assert mainline.resolved is False
    assert base_mod.guard_message(mainline, "plan [add]") is None


def test_unresolved_sentinel_is_not_marked_thin() -> None:
    """Nothing resolved is not the same as a guessed-by-name answer."""
    assert base_mod.UNRESOLVED.resolved is False
    assert base_mod.UNRESOLVED.thin is False


# --- finalize's permit path --------------------------------------------------


def test_finalize_commits_on_a_mainline_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """finalize's *allow* path, with HEAD genuinely resolved and on the mainline.

    The pre-existing finalize tests init a repo with no commit, so HEAD is unborn
    and the guard is inert there — they pass without ever reaching this path.
    """
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "my-plan", "--defer"]).exit_code == 0

    result = runner.invoke(app, ["finalize"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-my-plan" / "plan.md").exists()
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "plan [add]: 000 - my-plan" in log


def test_finalize_allow_branch_overrides_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The override is threaded through finalize's call site, not just add's."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "my-plan", "--defer"]).exit_code == 0
    _branch(tmp_path, "feature/x")

    result = runner.invoke(app, ["finalize", "--allow-branch"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".planners" / "plans" / "000-my-plan" / "plan.md").exists()


# --- the activate guard -------------------------------------------------------

_DRAFT_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: draft\nbranch:\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n# My thing\n"
)


def _seed_plan(path: Path) -> Path:
    """A draft plan 005 committed on the current branch, ready to activate."""
    plan_dir = path / ".planners" / "plans" / "005-my-thing"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    plan.write_text(_DRAFT_PLAN, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "plan [add]: 005 - my-thing"], cwd=path, check=True
    )
    return plan


def test_activate_refuses_on_a_feature_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The activation commit belongs on the mainline, before the branch exists."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    plan = _seed_plan(tmp_path)
    original = plan.read_text(encoding="utf-8")
    _branch(tmp_path, "feature/my-thing")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 1
    assert "not a mainline branch" in result.output
    # Refused before writing: the plan is left exactly as it was.
    assert plan.read_text(encoding="utf-8") == original


def test_activate_allow_branch_overrides_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    plan = _seed_plan(tmp_path)
    _branch(tmp_path, "feature/my-thing")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005", "--allow-branch"])
    assert result.exit_code == 0, result.output
    assert "status: active" in plan.read_text(encoding="utf-8")


def test_activate_allows_a_mainline_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    _seed_plan(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    log = _unredirected(tmp_path, ["log", "--oneline"])
    assert "plan [activate]: 005 - my-thing" in log


def test_activate_no_commit_is_unguarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-commit makes no commit, so no branch can strand one."""
    _init_git(tmp_path, branch="main")
    _commit(tmp_path)
    plan = _seed_plan(tmp_path)
    _branch(tmp_path, "feature/my-thing")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "status: active" in plan.read_text(encoding="utf-8")
