"""CLI tests for ``conclude``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners.cli import app
from planners.metadata import PlanMetadata, Status
from tests.helpers import commit_all, git, git_out, init_git

runner = CliRunner()

_NOW = "2026-07-01T09:00:00-07:00"
_START = "2026-06-20T08:00:00-07:00"
_WORK = "2026-06-22T10:00:00-07:00"
_PAPERWORK = "2026-06-23T11:00:00-07:00"

_LOG = (
    "## Log\n\n- **2026-06-20T08:30:00-07:00** — Activated.\n"
    "  - Branch: `feature/parser`\n  - Base: `main` at `abc1234`\n"
)


def _plan(status: str = "implemented", branch: str = " feature/parser") -> str:
    return (
        f"---\nid: 5\nslug: parser\nstatus: {status}\nbranch:{branch}\n"
        "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
        f"# Parser\n\n## Plan\n\nThe spec.\n\n{_LOG}"
    )


def _repo(root: Path, *, git_repo: bool = False, text: str | None = None) -> Path:
    if git_repo:
        init_git(root)
    plan = root / ".planners" / "plans" / "005-parser" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(text or _plan(), encoding="utf-8")
    if git_repo:
        commit_all(root, "initial commit", date=_START)
    return plan


def _branch_with_work(root: Path, plan: Path) -> None:
    """A feature branch: one work commit, then a plan-only commit after it."""
    git(root, "checkout", "-q", "-b", "feature/parser")
    (root / "parser.py").write_text("x = 1\n", encoding="utf-8")
    commit_all(root, "add parser", date=_WORK)
    with plan.open("a", encoding="utf-8") as handle:
        handle.write("\n## Retrospective\n\n- insight\n")
    commit_all(root, "plan log", date=_PAPERWORK)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "_now", lambda: _NOW)


def test_conclude_no_commit_closes_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["conclude", "5", "--no-commit"])
    assert result.exit_code == 0, result.output

    meta = PlanMetadata.from_file(plan)
    assert meta.status == Status.done
    # No repo here, so there is no commit to date it by.
    assert meta.concluded == _NOW
    assert meta.branch == "feature/parser"
    assert meta.pr is None
    text = plan.read_text(encoding="utf-8")
    assert "pr: null\n" in text
    assert text.endswith(_LOG)
    assert meta.validate() == []
    assert not (tmp_path / ".planners" / "README.md").exists()


def test_conclude_dates_the_last_work_commit_not_the_paperwork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repo(tmp_path, git_repo=True)
    _branch_with_work(tmp_path, plan)
    # A Retrospective written by hand and not yet committed rides along.
    with plan.open("a", encoding="utf-8") as handle:
        handle.write("- another insight\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["conclude", "005"])
    assert result.exit_code == 0, result.output

    meta = PlanMetadata.from_file(plan)
    assert meta.status == Status.done
    assert meta.concluded == _WORK
    assert git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [close]: 005 - parser"
    )
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/README.md",
        ".planners/plans/005-parser/plan.md",
    ]
    assert "- another insight\n" in git_out(tmp_path, "show", "HEAD:" + changed[1])
    assert git_out(tmp_path, "status", "--porcelain") == ""
    assert runner.invoke(app, ["validate"]).exit_code == 0

    again = runner.invoke(app, ["conclude", "5"])
    assert again.exit_code == 1
    assert "plan 005 is done; it is closed" in again.output


def test_conclude_falls_back_to_head_without_a_work_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Worked on the mainline: nothing lies past the base, so HEAD dates it.
    plan = _repo(tmp_path, git_repo=True, text=_plan(branch=""))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["conclude", "5"])
    assert result.exit_code == 0, result.output
    meta = PlanMetadata.from_file(plan)
    assert meta.concluded == _START
    assert meta.branch is None
    assert "branch: null\n" in plan.read_text(encoding="utf-8")


def test_conclude_resumes_a_run_whose_commit_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repo(tmp_path, git_repo=True)
    _branch_with_work(tmp_path, plan)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["conclude", "5", "--no-commit"]).exit_code == 0
    written = plan.read_text(encoding="utf-8")

    result = runner.invoke(app, ["conclude", "5"])
    assert result.exit_code == 0, result.output
    assert "committing the earlier change" in result.output
    assert plan.read_text(encoding="utf-8") == written
    assert git_out(tmp_path, "status", "--porcelain") == ""


def test_conclude_refuses_a_head_off_the_plans_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repo(tmp_path, git_repo=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["conclude", "5"])
    assert result.exit_code == 1
    assert "records branch 'feature/parser', but HEAD is on 'main'" in result.output
    assert plan.read_text(encoding="utf-8") == _plan()


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("draft", "plan 005 is draft; only an active or implemented plan"),
        ("blocked", "plan 005 is blocked; only an active or implemented plan"),
        ("retired", "plan 005 is retired; it is closed"),
    ],
)
def test_conclude_refuses_a_plan_that_is_not_open_work(
    status: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _plan(status)
    if status == "retired":
        text = text.replace("concluded:\n", f"concluded: {_START}\n")
    plan = _repo(tmp_path, text=text)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["conclude", "5", "--no-commit"])
    assert result.exit_code == 1
    assert message in result.output
    assert plan.read_text(encoding="utf-8") == text


def test_conclude_refuses_a_nested_subplan_and_unfinished_subplans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _repo(tmp_path)
    sub = plan.parent / "subplans" / "b-lexer.md"
    sub.parent.mkdir()
    sub.write_text("---\nstatus: active\nbranch:\n---\n\n# Lexer\n")
    monkeypatch.chdir(tmp_path)

    nested = runner.invoke(app, ["conclude", "5b", "--no-commit"])
    assert nested.exit_code == 1
    assert "nested subplan" in nested.output

    umbrella = runner.invoke(app, ["conclude", "5", "--no-commit"])
    assert umbrella.exit_code == 1
    assert "plan 005 has unfinished subplans: b (active)" in umbrella.output
    assert plan.read_text(encoding="utf-8") == _plan()

    sub.write_text("# no frontmatter\n")
    unreadable = runner.invoke(app, ["conclude", "5", "--no-commit"])
    assert unreadable.exit_code == 1
    assert "fix them before concluding it" in unreadable.output
