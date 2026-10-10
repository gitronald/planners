"""CLI tests for ``retire``."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners.cli import app
from planners.metadata import PlanMetadata, Status
from tests.helpers import commit_all, git_out, init_git

runner = CliRunner()

_NOW = "2026-07-01T09:00:00-07:00"


def _plan(number: int, slug: str, status: str = "draft", branch: str = "") -> str:
    return (
        f"---\nid: {number}\nslug: {slug}\nstatus: {status}\nbranch:{branch}\n"
        "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
        f"# {slug}\n\n## Plan\n\nThe spec.\n\n## Retrospective\n\n- insight\n"
    )


_SUBPLAN = "---\nstatus: blocked\nbranch:\n---\n\n# Step\n\n## Plan\n\n## Log\n"


def _repo(root: Path, *, git: bool = False) -> Path:
    if git:
        init_git(root)
    plans = root / ".planners" / "plans"
    for number, slug in ((5, "old-idea"), (15, "follow-up")):
        plan_dir = plans / f"{number:03d}-{slug}"
        plan_dir.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(_plan(number, slug), encoding="utf-8")
    sub = plans / "015-follow-up" / "subplans" / "d-step.md"
    sub.parent.mkdir()
    sub.write_text(_SUBPLAN, encoding="utf-8")
    if git:
        commit_all(root, "initial commit", date="2026-06-20T08:00:00-07:00")
    return plans


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "_now", lambda: _NOW)


def test_retire_no_commit_closes_the_plan_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["retire", "5", "--into", "15", "--note", "Absorbed as a step.", "--no-commit"],
    )
    assert result.exit_code == 0, result.output

    path = plans / "005-old-idea" / "plan.md"
    text = path.read_text(encoding="utf-8")
    meta = PlanMetadata.from_file(path)
    assert meta.status == Status.retired
    # No repo here, so there is no HEAD to date the decision by.
    assert meta.concluded == _NOW
    assert meta.branch is None and meta.pr is None
    assert "branch: null\n" in text and "pr: null\n" in text
    assert meta.validate() == []
    assert (
        "The spec.\n\n## Log\n\n"
        f"- **{_NOW}** — Retired. The work moved to plan 015. Absorbed as a step.\n\n"
        "## Retrospective\n\n- insight\n"
    ) in text
    assert not (tmp_path / ".planners" / "README.md").exists()


def test_retire_keeps_a_branch_that_was_filled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    path = plans / "005-old-idea" / "plan.md"
    path.write_text(_plan(5, "old-idea", "active", " feature/old-idea"))
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["retire", "005", "--no-commit"]).exit_code == 0
    text = path.read_text(encoding="utf-8")
    assert "branch: feature/old-idea\n" in text
    assert f"- **{_NOW}** — Retired.\n" in text


def test_retire_commits_with_the_date_of_head_and_a_fresh_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path, git=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["retire", "005", "--into", "015"])
    assert result.exit_code == 0, result.output

    meta = PlanMetadata.from_file(plans / "005-old-idea" / "plan.md")
    assert meta.concluded == "2026-06-20T08:00:00-07:00"
    assert git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [retire]: 005 - old-idea"
    )
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/README.md",
        ".planners/plans/005-old-idea/plan.md",
    ]
    assert git_out(tmp_path, "status", "--porcelain") == ""
    assert runner.invoke(app, ["validate"]).exit_code == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["retire", "006"], "no plan 006 found"),
        (["retire", "x"], "not a plan reference"),
        (["retire", "005", "--into", "099"], "no plan 099 found"),
        (["retire", "005", "--into", "5"], "cannot be retired into itself"),
    ],
)
def test_retire_refusals_change_nothing(
    args: list[str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*args, "--no-commit"])
    assert result.exit_code == 1
    assert message in result.output
    assert (plans / "005-old-idea" / "plan.md").read_text() == _plan(5, "old-idea")


def test_retire_refuses_a_closed_or_unreadable_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["retire", "005", "--no-commit"]).exit_code == 0
    again = runner.invoke(app, ["retire", "005", "--no-commit"])
    assert again.exit_code == 1
    assert "plan 005 is retired; it is closed" in again.output

    (plans / "015-follow-up" / "plan.md").write_text("# no frontmatter\n")
    unreadable = runner.invoke(app, ["retire", "015", "--no-commit"])
    assert unreadable.exit_code == 1
    assert "missing YAML frontmatter" in unreadable.output


def test_retire_a_nested_subplan_records_where_it_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path, git=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["retire", "015d", "--into", "5"])
    assert result.exit_code == 0, result.output

    sub = (plans / "015-follow-up" / "subplans" / "d-step.md").read_text()
    assert sub == (
        "---\nstatus: retired\nbranch:\nmoved_to: 005\n---\n\n# Step\n\n## Plan\n\n"
        f"## Log\n\n- **{_NOW}** — Retired. The work moved to plan 005.\n"
    )
    umbrella = (plans / "015-follow-up" / "plan.md").read_text()
    assert "| [d](subplans/d-step.md) | Step | retired |  |" in umbrella
    # The umbrella itself stays open: only its step closed.
    assert "status: draft" in umbrella
    assert git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [retire]: 015d - step"
    )
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/plans/015-follow-up/plan.md",
        ".planners/plans/015-follow-up/subplans/d-step.md",
    ]
    assert runner.invoke(app, ["subplans", "015", "--require-closed"]).exit_code == 0

    again = runner.invoke(app, ["retire", "015d"])
    assert again.exit_code == 1
    assert "subplan 015d is retired; it is closed" in again.output


def test_retire_a_nested_subplan_warns_about_an_unreadable_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    (plans / "015-follow-up" / "subplans" / "e-broken.md").write_text("# none\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["retire", "015d", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "warning: e-broken.md: missing YAML frontmatter" in result.output

    broken = runner.invoke(app, ["retire", "015e", "--no-commit"])
    assert broken.exit_code == 1
    assert "cannot read" in broken.output


def test_retire_a_nested_subplan_writes_nothing_when_the_table_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The subplan used to be rewritten first. A table the command may not write
    # then left it retired with no commit, and a rerun refused it as closed.
    plans = _repo(tmp_path)
    plan = plans / "015-follow-up" / "plan.md"
    plan.write_text(
        plan.read_text()
        + "\n<!-- planners:subplans:start -->\n| Step | Scope |\n|---|---|\n"
        "<!-- planners:subplans:end -->\n"
    )
    umbrella = plan.read_text()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["retire", "015d", "--no-commit"])
    assert result.exit_code == 1
    assert "no Status column" in result.output
    assert "retired" not in result.output
    assert (plans / "015-follow-up" / "subplans" / "d-step.md").read_text() == _SUBPLAN
    assert plan.read_text() == umbrella


@pytest.mark.parametrize("status", ["draft", "active", "blocked"])
def test_retire_refuses_an_umbrella_with_unfinished_subplans(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An umbrella does not close over unfinished subplans, by either door.
    plans = _repo(tmp_path)
    sub = plans / "015-follow-up" / "subplans" / "d-step.md"
    sub.write_text(_SUBPLAN.replace("status: blocked", f"status: {status}"))
    before = (plans / "015-follow-up" / "plan.md").read_text()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["retire", "015", "--no-commit"])
    assert result.exit_code == 1
    assert f"plan 015 has unfinished subplans: d ({status})" in result.output
    assert "planners retire 015<letter>" in result.output
    assert (plans / "015-follow-up" / "plan.md").read_text() == before


@pytest.mark.parametrize("status", ["done", "inactive"])
def test_retire_closes_an_umbrella_whose_subplans_are_finished(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    sub = plans / "015-follow-up" / "subplans" / "d-step.md"
    sub.write_text(_SUBPLAN.replace("status: blocked", f"status: {status}"))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["retire", "015", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "status: retired" in (plans / "015-follow-up" / "plan.md").read_text()


def test_retire_keeps_other_staged_changes_out_of_its_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, git=True)
    (tmp_path / "unrelated.txt").write_text("staged by hand\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["retire", "005", "--into", "015"])
    assert result.exit_code == 0, result.output

    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert "unrelated.txt" not in changed
    # Still staged, as the user left it.
    assert git_out(tmp_path, "diff", "--cached", "--name-only").split() == [
        "unrelated.txt"
    ]


def test_retire_refuses_an_umbrella_with_an_unreadable_subplan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = _repo(tmp_path)
    sub = plans / "015-follow-up" / "subplans" / "d-step.md"
    sub.write_text(_SUBPLAN.replace("status: blocked", "status: actve"))
    before = (plans / "015-follow-up" / "plan.md").read_text()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["retire", "015", "--no-commit"])
    assert result.exit_code == 1
    assert "plan 015 has subplans that cannot be read" in result.output
    assert (plans / "015-follow-up" / "plan.md").read_text() == before
