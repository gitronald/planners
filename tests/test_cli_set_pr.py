"""CLI tests for ``set-pr``."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app

runner = CliRunner()

_URL = "https://github.com/owner/repo/pull/7"
_PLAN = (
    "---\nid: 5\nslug: my-thing\nstatus: active\nbranch: feature/my-thing\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
    "# My thing\n\n## Plan\n\nBody text that must survive verbatim.\n"
)
_SUBPLAN = "---\nstatus: active\nbranch: other-repo-branch\n---\n\n# Step\n"


def _repo(root: Path, *, git: bool = False) -> Path:
    if git:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    plan_dir = root / ".planners" / "plans" / "005-my-thing"
    (plan_dir / "subplans").mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN, encoding="utf-8")
    (plan_dir / "subplans" / "d-step.md").write_text(_SUBPLAN, encoding="utf-8")
    if git:
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial commit"], cwd=root, check=True)
    return plan_dir


def _git_out(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    ).stdout


def test_set_pr_no_commit_writes_only_the_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["set-pr", "5", _URL, "--no-commit"])
    assert result.exit_code == 0, result.output
    text = (plan_dir / "plan.md").read_text(encoding="utf-8")
    assert text == _PLAN.replace("pr:\n", f"pr: {_URL}\n")
    assert not (tmp_path / ".planners" / "README.md").exists()

    again = runner.invoke(app, ["set-pr", "5", _URL, "--no-commit"])
    assert again.exit_code == 0
    assert "nothing to do" in again.output


@pytest.mark.parametrize(
    "url", ["7", "#7", "github.com/owner/repo/pull/7", "http:// x"]
)
def test_set_pr_rejects_what_is_not_a_url(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["set-pr", "005", url, "--no-commit"])
    assert result.exit_code == 1
    assert "not a PR URL" in result.output
    assert (plan_dir / "plan.md").read_text(encoding="utf-8") == _PLAN


def test_set_pr_reports_a_missing_or_unreadable_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    missing = runner.invoke(app, ["set-pr", "006", _URL])
    assert missing.exit_code == 1
    assert "no plan 006 found" in missing.output
    no_letter = runner.invoke(app, ["set-pr", "005e", _URL])
    assert no_letter.exit_code == 1
    assert "no plan 005e found" in no_letter.output

    (plan_dir / "plan.md").write_text(_PLAN.replace("status: active", "status: x"))
    unreadable = runner.invoke(app, ["set-pr", "005", _URL])
    assert unreadable.exit_code == 1
    assert "invalid status" in unreadable.output


def test_set_pr_commits_the_plan_with_a_refreshed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, git=True)
    subprocess.run(
        ["git", "checkout", "-qb", "feature/my-thing"], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["set-pr", "005", _URL])
    assert result.exit_code == 0, result.output
    assert _git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [pr]: 005 - my-thing"
    )
    changed = _git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/README.md",
        ".planners/plans/005-my-thing/plan.md",
    ]
    assert "[#7]" in (tmp_path / ".planners" / "README.md").read_text(encoding="utf-8")
    assert runner.invoke(app, ["validate"]).exit_code == 0

    before = _git_out(tmp_path, "rev-parse", "HEAD")
    again = runner.invoke(app, ["set-pr", "005", _URL])
    assert again.exit_code == 0
    assert "nothing to do" in again.output
    assert _git_out(tmp_path, "rev-parse", "HEAD") == before


def test_set_pr_finishes_a_write_that_was_never_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, git=True)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["set-pr", "005", _URL, "--no-commit"]).exit_code == 0
    result = runner.invoke(app, ["set-pr", "005", _URL])
    assert result.exit_code == 0, result.output
    assert "nothing to do" not in result.output
    assert _git_out(tmp_path, "status", "--porcelain") == ""
    assert "plan [pr]: 005 - my-thing" in _git_out(tmp_path, "log", "--oneline")


def test_set_pr_on_a_nested_subplan_writes_its_own_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, git=True)
    monkeypatch.chdir(tmp_path)
    url = "https://github.com/owner/other/pull/3"
    result = runner.invoke(app, ["set-pr", "005d", url])
    assert result.exit_code == 0, result.output
    sub = (plan_dir / "subplans" / "d-step.md").read_text(encoding="utf-8")
    assert sub == _SUBPLAN.replace(
        "branch: other-repo-branch\n", f"branch: other-repo-branch\npr: {url}\n"
    )
    # The umbrella's own pr: is a different field and stays pending.
    assert (plan_dir / "plan.md").read_text(encoding="utf-8") == _PLAN
    assert _git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [pr]: 005d - step"
    )
    changed = _git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == [".planners/plans/005-my-thing/subplans/d-step.md"]
