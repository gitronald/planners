"""CLI tests for ``log``."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners import cli as cli_mod
from planners.cli import app
from tests.helpers import commit_all, git_out, init_git, write_script

runner = CliRunner()

_NOW = "2026-07-01T09:00:00-07:00"

_PLAN = (
    "---\nid: 5\nslug: parser\nstatus: active\nbranch: feature/parser\n"
    "created: 2026-06-07T12:00:00-07:00\nconcluded:\npr:\n---\n\n"
    "# Parser\n\n## Plan\n\nThe spec.\n\n## Handoff\n\n- state\n"
)

_SUBPLAN = (
    "---\nstatus: active\nbranch:\n---\n\n# Step\n\n## Plan\n\n## Log\n\n"
    "- **2026-06-30T08:00:00-07:00** — Started.\n"
)


def _repo(root: Path, *, committed: bool = False) -> Path:
    if committed:
        init_git(root)
    plan_dir = root / ".planners" / "plans" / "005-parser"
    (plan_dir / "subplans").mkdir(parents=True)
    (plan_dir / "plan.md").write_text(_PLAN, encoding="utf-8")
    (plan_dir / "subplans" / "b-lexer.md").write_text(_SUBPLAN, encoding="utf-8")
    (root / "staged.txt").write_text("unrelated\n", encoding="utf-8")
    if committed:
        commit_all(root, "initial commit")
    return plan_dir


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "_now", lambda: _NOW)


def test_log_creates_the_section_ahead_of_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["log", "5", "Wrote the lexer.", "--no-commit"])
    assert result.exit_code == 0, result.output
    assert (plan_dir / "plan.md").read_text() == _PLAN.replace(
        "## Handoff",
        f"## Log\n\n- **{_NOW}** — Wrote the lexer.\n\n## Handoff",
    )


def test_log_appends_to_an_existing_log_and_commits_only_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, committed=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "staged.txt").write_text("changed\n", encoding="utf-8")
    assert runner.invoke(app, ["log", "005", "First."]).exit_code == 0
    result = runner.invoke(app, ["log", "005", "Second.", "--summary", "lexer done"])
    assert result.exit_code == 0, result.output

    text = (plan_dir / "plan.md").read_text()
    assert f"## Log\n\n- **{_NOW}** — First.\n- **{_NOW}** — Second.\n\n" in text
    subjects = git_out(tmp_path, "log", "-2", "--format=%s").splitlines()
    assert subjects == ["plan [log]: 005 - lexer done", "plan [log]: 005 - parser"]
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == [".planners/plans/005-parser/plan.md"]
    # Other work in the checkout is left out of the commit, and the index alone.
    assert git_out(tmp_path, "status", "--porcelain") == " M staged.txt\n"
    assert not (tmp_path / ".planners" / "README.md").exists()


def test_log_to_a_nested_subplan_reads_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path, committed=True)
    monkeypatch.chdir(tmp_path)
    note = "Done.\n- What changed: the lexer.\n- Not verified: Windows paths.\n"
    result = runner.invoke(app, ["log", "5b", "-"], input=note)
    assert result.exit_code == 0, result.output

    sub = (plan_dir / "subplans" / "b-lexer.md").read_text()
    assert sub == _SUBPLAN + (
        f"- **{_NOW}** — Done.\n"
        "  - What changed: the lexer.\n"
        "  - Not verified: Windows paths.\n"
    )
    assert (plan_dir / "plan.md").read_text() == _PLAN
    assert git_out(tmp_path, "log", "-1", "--format=%s").strip() == (
        "plan [log]: 005b - lexer"
    )


@pytest.mark.parametrize(
    ("args", "stdin", "message"),
    [
        (["log", "5", "   "], None, "the note is empty"),
        (["log", "5", "-"], "\n\n", "the note is empty"),
        (["log", "5", "x", "--summary", " "], None, "--summary must be one line"),
        (["log", "5", "x", "--summary", "a\nb"], None, "--summary must be one line"),
        (["log", "6", "x"], None, "no plan 006 found"),
        (["log", "5c", "x"], None, "no plan 005c found"),
    ],
)
def test_log_refusals_change_nothing(
    args: list[str],
    stdin: str | None,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*args, "--no-commit"], input=stdin)
    assert result.exit_code == 1
    assert message in result.output
    assert (plan_dir / "plan.md").read_text() == _PLAN


def test_log_has_no_option_that_sets_the_time() -> None:
    result = runner.invoke(app, ["log", "--help"])
    assert result.exit_code == 0
    for flag in ("--when", "--date", "--time", "--at"):
        assert flag not in result.output


def _duplicate_rows_hook(root: Path) -> None:
    """A pre-commit hook that fails on a committed index with a duplicated row.

    What the validate hook caught in the field: a local merge resolved the index
    with ``merge=union`` and committed a duplicate, and a commit of the plan alone
    carried that index forward.
    """
    write_script(
        root / ".git" / "hooks" / "pre-commit",
        "git show :.planners/README.md | grep '^| ' | sort | uniq -d | grep -q . "
        "&& exit 1\nexit 0\n",
    )


def test_log_refreshes_and_commits_a_stale_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, committed=True)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", "."]).exit_code == 0
    index = tmp_path / ".planners" / "README.md"
    row = next(line for line in index.read_text().splitlines() if "| 005 |" in line)
    index.write_text(index.read_text() + row + "\n", encoding="utf-8")
    commit_all(tmp_path, "merge with a union-duplicated row")
    _duplicate_rows_hook(tmp_path)

    result = runner.invoke(app, ["log", "005", "Merged the base."])
    assert result.exit_code == 0, result.output
    assert "refreshed the stale index" in result.output
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == [
        ".planners/README.md",
        ".planners/plans/005-parser/plan.md",
    ]
    assert index.read_text().count("| 005 |") == 1
    assert git_out(tmp_path, "status", "--porcelain") == ""


def test_log_leaves_a_fresh_index_out_of_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, committed=True)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["index", "."]).exit_code == 0
    commit_all(tmp_path, "index")

    result = runner.invoke(app, ["log", "005", "Wrote the lexer."])
    assert result.exit_code == 0, result.output
    assert "refreshed" not in result.output
    changed = git_out(tmp_path, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == [".planners/plans/005-parser/plan.md"]


@pytest.mark.parametrize(
    ("note", "named"),
    [
        ("Probe passed: `uv run pyrefly check /tmp/probe.py`.", "/tmp/probe.py"),
        ("Edited ~/.claude/rules/git.md.", "~/.claude/rules/git.md."),
        ("Copied to C:\\Users\\me\\out.csv", "C:\\Users\\me\\out.csv"),
    ],
)
def test_log_refuses_a_local_path(
    note: str, named: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_dir = _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["log", "5", note, "--no-commit"])
    assert result.exit_code == 1
    assert "names a local path" in result.output
    assert named in result.output
    assert (plan_dir / "plan.md").read_text() == _PLAN

    allowed = ["log", "5", note, "--no-commit", "--allow-local-paths"]
    assert runner.invoke(app, allowed).exit_code == 0
    assert note in (plan_dir / "plan.md").read_text()


def test_log_keeps_repo_paths_urls_and_branch_names() -> None:
    from planners.entries import local_paths

    note = (
        "Wrote `.planners/plans/005-parser/probe.py` and docs/a/b.md on "
        "feature/005-parser; see https://github.com/owner/repo/pull/1 and/or "
        "run /planners log."
    )
    assert local_paths(note) == []
