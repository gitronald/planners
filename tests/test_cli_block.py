"""CLI tests for ``block``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from tests.helpers import bare_remote, commit_all, git, git_out, init_git

runner = CliRunner()

_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: {status}\nbranch:{branch}\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:{concluded}\npr:\n---\n\n"
    "# My thing\n\n## Plan\n\nBody text that must survive verbatim.\n\n"
    "## Handoff\n\nWaits on a decision.\n"
)


def _path(root: Path) -> Path:
    return root / ".planners" / "plans" / "005-my-thing" / "plan.md"


def _repo(root: Path, status: str = "active", concluded: str = "") -> Path:
    init_git(root)
    path = _path(root)
    path.parent.mkdir(parents=True)
    path.write_text(
        _PLAN.format(
            status=status,
            branch=" feature/my-thing" if status != "draft" else "",
            concluded=f" {concluded}" if concluded else "",
        ),
        encoding="utf-8",
    )
    assert runner.invoke(app, ["index", str(root)]).exit_code == 0
    commit_all(root, "initial commit")
    return path


@pytest.mark.parametrize("status", ["draft", "active"])
def test_block_sets_the_status_refreshes_the_index_and_commits(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, status)
    body = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["block", "5"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert "status: blocked\n" in text
    assert text.split("---\n", 2)[2] == body
    assert "| blocked |" in (tmp_path / ".planners" / "README.md").read_text(
        encoding="utf-8"
    )
    assert (
        git_out(tmp_path, "log", "-1", "--format=%s").strip()
        == "plan [block]: 005 - my-thing"
    )
    assert git_out(tmp_path, "status", "--porcelain") == ""
    assert runner.invoke(app, ["validate", "."]).exit_code == 0


def test_block_commits_a_reason_already_written_in_the_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    reason = "Waits on the owner's call."
    path.write_text(
        path.read_text(encoding="utf-8").replace("Waits on a decision.", reason),
        encoding="utf-8",
    )
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    assert reason in git_out(tmp_path, "show", f"HEAD:{_rel(path, tmp_path)}")
    assert git_out(tmp_path, "status", "--porcelain") == ""


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def test_block_no_commit_writes_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path)
    head = git_out(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["block", "005", "--no-commit"]).exit_code == 0
    assert "status: blocked\n" in path.read_text(encoding="utf-8")
    assert git_out(tmp_path, "rev-parse", "HEAD") == head


def test_block_finishes_an_earlier_run_that_did_not_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["block", "005", "--no-commit"]).exit_code == 0
    result = runner.invoke(app, ["block", "005"])
    assert result.exit_code == 0, result.output
    assert "committing the earlier change" in result.output
    assert (
        git_out(tmp_path, "log", "-1", "--format=%s").strip()
        == "plan [block]: 005 - my-thing"
    )


@pytest.mark.parametrize(
    ("status", "concluded"),
    [
        ("blocked", ""),
        ("implemented", ""),
        ("inactive", ""),
        ("done", "2026-06-09T12:00:00-07:00"),
        ("retired", "2026-06-09T12:00:00-07:00"),
    ],
)
def test_block_refuses_any_other_status(
    status: str, concluded: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, status, concluded)
    before = path.read_text(encoding="utf-8")
    head = git_out(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["block", "005"])
    assert result.exit_code == 1
    assert f"plan 005 is {status}; only a draft or active plan" in result.output
    assert path.read_text(encoding="utf-8") == before
    assert git_out(tmp_path, "rev-parse", "HEAD") == head


def test_block_points_a_nested_subplan_at_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path)
    sub = path.parent / "subplans" / "d-step.md"
    sub.parent.mkdir()
    sub.write_text("---\nstatus: draft\nbranch:\n---\n\n# Step\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["block", "005d"])
    assert result.exit_code == 1
    assert "planners subplans 005 --set d=<status>" in result.output


def test_block_refuses_an_edit_to_a_plan_already_blocked_at_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, "blocked")
    head = git_out(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "\nAn edit.\n", encoding="utf-8")
    result = runner.invoke(app, ["block", "005"])
    assert result.exit_code == 1
    assert "plan 005 is blocked; only a draft or active plan" in result.output
    assert git_out(tmp_path, "rev-parse", "HEAD") == head
    assert "An edit." in path.read_text(encoding="utf-8")


def _activated_on_its_branch(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A plan activated on ``main``, on its recorded branch, with a Log entry."""
    path = _repo(root, "draft")
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["activate", "005"]).exit_code == 0
    git(root, "checkout", "-qb", "feature/005-my-thing")
    assert runner.invoke(app, ["log", "005", "a note"]).exit_code == 0
    return path


def test_block_and_activate_on_the_plans_branch_merge_without_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _activated_on_its_branch(tmp_path, monkeypatch)
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert "status: active\n" in text
    assert "Reactivated: back to active after a block." in text
    assert text.count("Activated.") == 1
    assert "committed the return from the block on feature/005" in result.output
    git(tmp_path, "checkout", "-q", "main")
    git(tmp_path, "merge", "-q", "--no-ff", "feature/005-my-thing", "-m", "merge")
    assert git_out(tmp_path, "status", "--porcelain") == ""


def test_activate_from_a_block_warns_that_a_worktree_is_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activated_on_its_branch(tmp_path, monkeypatch)
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    result = runner.invoke(app, ["activate", "005", "--no-worktree"])
    assert result.exit_code == 0, result.output
    assert "--worktree and --no-worktree are not recorded" in result.output


def test_activate_from_a_block_on_another_branch_is_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _activated_on_its_branch(tmp_path, monkeypatch)
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    git(tmp_path, "checkout", "-qb", "feature/other")
    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 1
    assert "mainline" in result.output
    assert "status: blocked\n" in path.read_text(encoding="utf-8")


def test_activate_of_a_never_activated_plan_on_its_branch_is_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded branch alone is not a return: nothing was activated to return to."""
    path = _repo(tmp_path, "blocked")
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "checkout", "-qb", "feature/my-thing")
    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 1
    assert "mainline" in result.output
    assert "status: blocked\n" in path.read_text(encoding="utf-8")


def test_activate_from_a_block_on_the_mainline_writes_an_activation_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, "draft")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["activate", "005"]).exit_code == 0
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    assert runner.invoke(app, ["activate", "005"]).exit_code == 0
    text = path.read_text(encoding="utf-8")
    assert text.count("Activated.") == 2
    assert "Reactivated" not in text


def test_block_commits_a_blocked_plan_head_does_not_have(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git(tmp_path)
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    commit_all(tmp_path, "initial commit")
    path = _path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        _PLAN.format(status="blocked", branch="", concluded=""), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["block", "005"])
    assert result.exit_code == 0, result.output
    assert "committing the earlier change" in result.output
    assert git_out(tmp_path, "status", "--porcelain") == ""


def test_block_resumes_over_a_head_copy_that_does_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, "blocked")
    good = path.read_text(encoding="utf-8")
    path.write_text("no frontmatter\n", encoding="utf-8")
    commit_all(tmp_path, "break the plan")
    path.write_text(good, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["block", "005"])
    assert result.exit_code == 0, result.output
    assert "committing the earlier change" in result.output


def test_activate_from_a_block_does_not_report_branch_work_as_other_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _activated_on_its_branch(tmp_path, monkeypatch)
    remote = tmp_path.parent / "remote.git"
    bare_remote(tmp_path, remote)
    git(tmp_path, "push", "-qu", "origin", "feature/005-my-thing")
    (tmp_path / "work.txt").write_text("work\n", encoding="utf-8")
    commit_all(tmp_path, "add code")
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert "other" not in result.output
    assert "add code" not in result.output
    assert "status: active\n" in path.read_text(encoding="utf-8")
