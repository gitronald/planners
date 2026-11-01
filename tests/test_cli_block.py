"""CLI tests for ``block``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from tests.helpers import commit_all, git, git_out, init_git

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


def test_block_commits_on_a_feature_branch_and_activate_returns_it_on_the_mainline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The return is guarded where the block is not, which the skill text explains."""
    path = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "checkout", "-qb", "feature/my-thing")
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    assert "status: blocked\n" in path.read_text(encoding="utf-8")
    refused = runner.invoke(app, ["activate", "005"])
    assert refused.exit_code == 1
    assert "mainline" in refused.output
    git(tmp_path, "checkout", "-q", "main")
    assert runner.invoke(app, ["block", "005"]).exit_code == 0
    assert runner.invoke(app, ["activate", "005"]).exit_code == 0
    assert "status: active\n" in path.read_text(encoding="utf-8")


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
