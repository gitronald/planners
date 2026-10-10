"""CLI tests for ``implemented``."""

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from tests.helpers import bare_remote, commit_all, git_out, init_git, write_script

runner = CliRunner()

_URL = "https://github.com/owner/repo/pull/7"
_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: {status}\nbranch: feature/my-thing\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:{pr}\n---\n\n"
    "# My thing\n\n## Plan\n\nBody text that must survive verbatim.\n\n"
    "## Log\n\n- **2026-06-08T12:00:00-07:00** — Activated.\n"
    "  - Branch: `feature/my-thing`\n  - Base: `main` at `0000000`\n"
    "  - Worktree: `.worktrees/my-thing`\n  - PR: pending\n\n"
    "## Handoff\n\nWhere to pick up.\n"
)


def _plan_path(root: Path) -> Path:
    return root / ".planners" / "plans" / "005-my-thing" / "plan.md"


def _repo(root: Path, *, status: str = "active", pr: str = "", work: int = 2) -> Path:
    """A repo on ``main`` holding plan 005, then ``work`` commits on its branch."""
    root.mkdir(exist_ok=True)
    init_git(root)
    path = _plan_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        _PLAN.format(status=status, pr=f" {pr}" if pr else ""), encoding="utf-8"
    )
    commit_all(root, "initial commit")
    subprocess.run(["git", "checkout", "-qb", "feature/my-thing"], cwd=root)
    for n in range(work):
        (root / f"work{n}.txt").write_text(f"{n}\n", encoding="utf-8")
        commit_all(root, f"work {n}")
    return path


def _with_remote(root: Path, remote: Path, *, push: bool = True) -> None:
    bare_remote(root, remote)
    if push:
        subprocess.run(
            ["git", "push", "-qu", "origin", "feature/my-thing"],
            cwd=root,
            check=True,
            capture_output=True,
        )


def _fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int) -> Path:
    """Put a ``gh`` on PATH that records its arguments and exits with ``code``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.txt"
    write_script(
        bin_dir / "gh",
        f'echo "$@" >> "{calls}"\n'
        f'[ {code} -eq 0 ] || echo "gh says no" >&2\nexit {code}\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return calls


def test_implemented_marks_the_plan_and_counts_the_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output

    text = path.read_text(encoding="utf-8")
    assert "status: implemented" in text
    assert "concluded:\n" in text
    # The entry follows the activation one, ahead of the Handoff, and counts the
    # commits past the base the activation recorded.
    log = text.split("## Handoff")[0]
    assert "— Implemented: 2 commits ahead of `main`.\n" in log
    assert "Body text that must survive verbatim." in text
    assert git_out(root, "log", "-1", "--format=%s").strip() == (
        "plan [implemented]: 005 - my-thing"
    )
    assert "implemented" in (root / ".planners" / "README.md").read_text(
        encoding="utf-8"
    )
    assert git_out(root, "status", "--porcelain") == ""
    assert "push feature/my-thing" in result.output


@pytest.mark.parametrize("status", ["draft", "blocked", "implemented"])
def test_implemented_refuses_a_plan_that_is_not_active(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, status=status)
    before = path.read_text(encoding="utf-8")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert f"plan 005 is {status}" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_implemented_refuses_uncommitted_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root)
    before = path.read_text(encoding="utf-8")
    (root / "loose.txt").write_text("not committed\n", encoding="utf-8")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "1 uncommitted change(s)" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_implemented_refuses_unpushed_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _repo(root)
    _with_remote(root, tmp_path / "remote.git")
    (root / "late.txt").write_text("late\n", encoding="utf-8")
    commit_all(root, "late work")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "1 commit(s) not pushed to origin/feature/my-thing" in result.output


def test_implemented_refuses_a_branch_with_no_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _repo(root)
    _with_remote(root, tmp_path / "remote.git", push=False)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "feature/my-thing has no upstream" in result.output


def test_implemented_takes_the_pr_out_of_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _repo(root, pr=_URL)
    _with_remote(root, tmp_path / "remote.git")
    calls = _fake_gh(tmp_path, monkeypatch, 0)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output
    assert calls.read_text(encoding="utf-8") == f"pr ready {_URL}\n"
    assert f"marked {_URL} ready for review" in result.output


def test_implemented_warns_when_gh_fails_and_keeps_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _repo(root, pr=_URL)
    _fake_gh(tmp_path, monkeypatch, 1)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output
    assert "gh says no" in result.output
    assert "run it by hand" in result.output
    assert "plan [implemented]" in git_out(root, "log", "-1", "--format=%s")


def test_implemented_no_commit_writes_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, pr=_URL)
    calls = _fake_gh(tmp_path, monkeypatch, 0)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "status: implemented" in path.read_text(encoding="utf-8")
    assert "plan [implemented]" not in git_out(root, "log", "--format=%s")
    # The PR stays a draft until the change it announces is committed.
    assert not calls.exists()


def test_implemented_without_an_activation_entry_uses_the_mainline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, work=0)
    path.write_text(
        _PLAN.format(status="active", pr="").split("## Log")[0], encoding="utf-8"
    )
    commit_all(root, "a plan activated before the entry existed")
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output
    assert "— Implemented: 1 commit ahead of `main`." in path.read_text(
        encoding="utf-8"
    )


def test_implemented_on_a_nested_subplan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, work=0)
    step = path.parent / "subplans" / "b-build.md"
    step.parent.mkdir()
    step.write_text("---\nstatus: active\nbranch:\n---\n\n# Build\n\n## Log\n")
    commit_all(root, "split")
    (root / "built.txt").write_text("built\n", encoding="utf-8")
    commit_all(root, "build it")
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005b"])
    assert result.exit_code == 0, result.output
    sub = step.read_text(encoding="utf-8")
    assert "status: implemented" in sub
    # The base comes from the umbrella's activation entry.
    assert "— Implemented: 2 commits ahead of `main`." in sub
    # The umbrella's table follows the subplan, and its own status does not move.
    umbrella = path.read_text(encoding="utf-8")
    assert "| implemented |" in umbrella
    assert "status: active" in umbrella
    assert git_out(root, "log", "-1", "--format=%s").strip() == (
        "plan [implemented]: 005b - build"
    )
    assert git_out(root, "status", "--porcelain") == ""


def test_implemented_refuses_the_mainline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, work=0)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
    before = path.read_text(encoding="utf-8")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "HEAD is on the mainline branch 'main'" in result.output
    assert path.read_text(encoding="utf-8") == before
    assert "plan [implemented]" not in git_out(root, "log", "--format=%s")


def test_implemented_refuses_a_detached_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _repo(root)
    _with_remote(root, tmp_path / "remote.git")
    subprocess.run(["git", "checkout", "-q", "--detach"], cwd=root, check=True)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "HEAD is detached" in result.output
    assert "origin a detached HEAD" not in result.output


def test_implemented_finishes_a_run_whose_commit_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root)
    hook = root / ".git" / "hooks" / "pre-commit"
    write_script(hook, "exit 1\n")
    monkeypatch.chdir(root)

    assert runner.invoke(app, ["implemented", "005"]).exit_code == 1
    assert "status: implemented" in path.read_text(encoding="utf-8")

    hook.unlink()
    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output
    assert "committing the earlier change" in result.output
    # The retry commits the first run's entry and writes no second one.
    assert path.read_text(encoding="utf-8").count("— Implemented:") == 1
    assert git_out(root, "log", "-1", "--format=%s").strip() == (
        "plan [implemented]: 005 - my-thing"
    )
    assert git_out(root, "status", "--porcelain") == ""


def test_implemented_resume_still_refuses_other_uncommitted_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["implemented", "005", "--no-commit"]).exit_code == 0
    assert "status: implemented" in path.read_text(encoding="utf-8")
    (root / "loose.txt").write_text("not committed\n", encoding="utf-8")

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 1
    assert "1 uncommitted change(s)" in result.output


def test_implemented_puts_a_new_subplan_log_before_its_retrospective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, work=0)
    step = path.parent / "subplans" / "b-build.md"
    step.parent.mkdir()
    step.write_text(
        "---\nstatus: active\nbranch:\n---\n\n# Build\n\n## Retrospective\n\nDone.\n"
    )
    commit_all(root, "split")
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005b"])
    assert result.exit_code == 0, result.output
    sub = step.read_text(encoding="utf-8")
    assert sub.index("## Log") < sub.index("## Retrospective")


def test_implemented_counts_against_the_remote_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    path = _repo(root, work=0)
    _with_remote(root, tmp_path / "remote.git")
    # origin/main moves ahead while the local main lags; the branch starts there.
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
    (root / "upstream.txt").write_text("upstream\n", encoding="utf-8")
    commit_all(root, "upstream work")
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=root, check=True)
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=root, check=True)
    subprocess.run(
        ["git", "checkout", "-q", "-B", "feature/my-thing", "origin/main"],
        cwd=root,
        check=True,
    )
    (root / "mine.txt").write_text("mine\n", encoding="utf-8")
    commit_all(root, "my work")
    subprocess.run(
        ["git", "push", "-qfu", "origin", "feature/my-thing"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["implemented", "005"])
    assert result.exit_code == 0, result.output
    assert "— Implemented: 1 commit ahead of `main`." in path.read_text(
        encoding="utf-8"
    )
