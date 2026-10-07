"""The unpushed-commit report ``activate`` prints after its commit.

The report tells the implement skill whether the push that follows carries only
the plan's own commits or someone else's work too. Every test builds a real repo
with a real (local, bare) remote, because the question is what the upstream ref
says — the parsing is unit-tested on its own.
"""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import ahead
from planners.cli import app

from .helpers import commit_all, init_git

runner = CliRunner()

_DRAFT_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: draft\nbranch:\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n# My thing\n"
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _repo_with_remote(tmp_path: Path) -> Path:
    """A repo on ``main`` whose upstream is a bare remote, in sync after one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git(repo)
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    commit_all(repo, "init")
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _seed_plan(repo: Path) -> Path:
    plan_dir = repo / ".planners" / "plans" / "005-my-thing"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / "plan.md"
    plan.write_text(_DRAFT_PLAN, encoding="utf-8")
    commit_all(repo, "plan [add]: 005 - my-thing")
    return plan


# --- parsing -----------------------------------------------------------------


def test_parse_log_splits_records_and_paths() -> None:
    text = (
        "\x1eabc1234 plan [add]: 005 - my-thing\n\n"
        ".planners/plans/005-my-thing/plan.md\n.planners/README.md\n"
        "\x1edef5678 update widget\n\nsrc/widget.py\n"
    )
    commits = ahead.parse_log(text)
    assert [c.sha for c in commits] == ["abc1234", "def5678"]
    assert commits[0].subject == "plan [add]: 005 - my-thing"
    assert commits[0].paths == (
        ".planners/plans/005-my-thing/plan.md",
        ".planners/README.md",
    )
    assert commits[1].paths == ("src/widget.py",)


def test_parse_log_of_nothing_is_empty() -> None:
    assert ahead.parse_log("") == []
    assert ahead.parse_log("\n") == []


@pytest.mark.parametrize(
    ("paths", "own"),
    [
        ((".planners/plans/005-my-thing/plan.md",), True),
        ((".planners/plans/005-my-thing/subplans/b-step.md",), True),
        ((".planners/plans/005-my-thing/plan.md", ".planners/README.md"), True),
        ((".planners/README.md",), True),
        ((".planners/plans/005-my-thing/plan.md", "src/widget.py"), False),
        ((".planners/plans/006-other/plan.md",), False),
        # A sibling whose name shares the prefix is a different plan.
        ((".planners/plans/005-my-thing-else/plan.md",), False),
        # A merge or empty commit touches nothing; that is not "the plan's own".
        ((), False),
    ],
)
def test_commit_ownership(paths: tuple[str, ...], own: bool) -> None:
    commit = ahead.Commit(sha="abc1234", subject="x", paths=paths)
    assert commit.is_own(".planners/plans/005-my-thing") is own


def test_report_lists_only_the_other_commits() -> None:
    own = ahead.Commit("aaa1111", "plan [add]: 008 - thing", ("x",))
    other = ahead.Commit("bbb2222", "update widget", ("src/widget.py",))
    lines = ahead.report(
        ahead.Ahead("dev", "origin/dev", own=(own,) * 3, other=(other,)), "008"
    )
    assert lines == [
        "dev is 4 ahead of origin/dev (as last fetched): 3 are plan 008's own, "
        "1 are other",
        "  bbb2222 update widget",
    ]


# --- the activate report -----------------------------------------------------


def test_activate_reports_only_its_own_commit_when_the_base_was_in_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_remote(tmp_path)
    _seed_plan(repo)
    _git(repo, "push", "-q")
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert (
        "main is 1 ahead of origin/main (as last fetched): 1 are plan 005's own, "
        "0 are other" in result.output
    )


def test_activate_counts_the_plans_own_unpushed_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan edited and split before activation arrives with several commits."""
    repo = _repo_with_remote(tmp_path)
    plan = _seed_plan(repo)
    plan.write_text(plan.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
    commit_all(repo, "update plan 005")
    sub = plan.parent / "subplans"
    sub.mkdir()
    (sub / "b-step.md").write_text(
        "---\nstatus: draft\n---\n# Step\n", encoding="utf-8"
    )
    commit_all(repo, "plan [add]: 005b - step")
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert "4 ahead of origin/main" in result.output
    assert "4 are plan 005's own, 0 are other" in result.output
    # Nothing to list when every commit is the plan's own.
    assert result.output.rstrip().endswith("0 are other")


def test_activate_lists_the_other_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_remote(tmp_path)
    _seed_plan(repo)
    (repo / "src").mkdir()
    (repo / "src" / "widget.py").write_text("x = 1\n", encoding="utf-8")
    commit_all(repo, "update widget")
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert "3 ahead of origin/main" in result.output
    assert "2 are plan 005's own, 1 are other" in result.output
    lines = result.output.splitlines()
    assert lines[-1].startswith("  ") and lines[-1].endswith(" update widget")
    assert "plan [add]: 005" not in lines[-1]


def test_activate_is_quiet_without_an_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No remote means nothing to compare against; the report is withheld, not zero."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git(repo)
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    commit_all(repo, "init")
    _seed_plan(repo)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["activate", "005"])
    assert result.exit_code == 0, result.output
    assert "committed the activation on main" in result.output
    assert "ahead of" not in result.output


def test_activate_no_commit_prints_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_remote(tmp_path)
    _seed_plan(repo)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["activate", "005", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert "ahead of" not in result.output
