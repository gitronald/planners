"""``index --after-merge``: the post-merge hook's repair goes into the merge commit."""

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planners.cli import app
from planners.host import HOOKS
from tests.helpers import bare_remote, commit_all, git, git_out, init_git, write_script

runner = CliRunner()

INDEX = ".planners/README.md"


def _plan(root: Path, number: str, slug: str) -> None:
    path = root / ".planners" / "plans" / f"{number}-{slug}" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nid: {int(number)}\nslug: {slug}\nstatus: draft\nbranch:\n"
        "created: 2026-01-01T12:00:00-08:00\nconcluded:\npr:\n---\n\n"
        f"# Plan {slug}\n\n## Plan\n\nDo it.\n",
        encoding="utf-8",
    )


def _repo(root: Path) -> Path:
    """A repo on ``main`` with one indexed plan, and a ``side`` branch level with it."""
    root.mkdir()
    init_git(root)
    _plan(root, "005", "first")
    assert runner.invoke(app, ["index", str(root)]).exit_code == 0
    commit_all(root, "base")
    git(root, "branch", "side")
    return root


def _diverge(root: Path) -> None:
    """Add a plan on ``side`` that its index lacks, and a commit on ``main``."""
    git(root, "checkout", "-q", "side")
    _plan(root, "006", "second")
    commit_all(root, "add a plan without its index row")
    git(root, "checkout", "-q", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    commit_all(root, "main moves")


def _merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``side`` merged into ``main`` with a merge commit whose index lacks a row."""
    root = _repo(tmp_path / "repo")
    _diverge(root)
    git(root, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    monkeypatch.chdir(root)
    return root


def test_the_hook_passes_after_merge() -> None:
    (hook,) = (h for h in HOOKS if h.id == "planners-index")
    assert hook.args == ("index", ".", "--after-merge")


def test_after_merge_amends_the_repair_into_the_merge_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _merged(tmp_path, monkeypatch)
    before = git_out(root, "rev-parse", "HEAD").strip()

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert f"amended {INDEX} into the merge commit" in result.output
    assert git_out(root, "status", "--porcelain") == ""
    # Still the one merge commit, with its message and both parents, now rewritten.
    assert git_out(root, "rev-parse", "HEAD").strip() != before
    assert git_out(root, "log", "-1", "--format=%s").strip() == "merge side"
    assert len(git_out(root, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3
    assert "006" in git_out(root, "show", f"HEAD:{INDEX}")


def test_a_plain_index_never_amends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _merged(tmp_path, monkeypatch)
    before = git_out(root, "rev-parse", "HEAD").strip()

    result = runner.invoke(app, ["index", "."])
    assert result.exit_code == 0, result.output
    assert "amended" not in result.output
    assert git_out(root, "rev-parse", "HEAD").strip() == before
    assert git_out(root, "status", "--porcelain").strip() == f"M {INDEX}"


def test_after_merge_leaves_a_pushed_merge_commit_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _merged(tmp_path, monkeypatch)
    bare_remote(root, tmp_path / "remote.git")
    git(root, "push", "-q", "-u", "origin", "main")
    before = git_out(root, "rev-parse", "HEAD").strip()

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert f"left {INDEX} uncommitted: the merge commit is already on origin/main" in (
        result.output
    )
    assert git_out(root, "rev-parse", "HEAD").strip() == before
    assert git_out(root, "status", "--porcelain").strip() == f"M {INDEX}"


def test_after_merge_leaves_a_fast_forward_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path / "repo")
    git(root, "checkout", "-q", "side")
    _plan(root, "006", "second")
    commit_all(root, "add a plan without its index row")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--ff-only", "side")
    before = git_out(root, "rev-parse", "HEAD").strip()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert f"left {INDEX} uncommitted: HEAD is not a merge commit" in result.output
    assert git_out(root, "rev-parse", "HEAD").strip() == before


def test_after_merge_says_so_when_the_index_needed_no_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path / "repo")
    git(root, "checkout", "-q", "side")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    commit_all(root, "side")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    before = git_out(root, "rev-parse", "HEAD").strip()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert "the index needed no repair after the merge" in result.output
    assert git_out(root, "rev-parse", "HEAD").strip() == before


def test_after_merge_amends_the_index_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _merged(tmp_path, monkeypatch)
    (root / "a.txt").write_text("staged\n", encoding="utf-8")
    git(root, "add", "a.txt")
    (root / "c.txt").write_text("untracked\n", encoding="utf-8")

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert "amended" in result.output
    # What was staged is still staged, and is not in the merge commit.
    assert git_out(root, "status", "--porcelain").split("\n")[:2] == [
        "M  a.txt",
        "?? c.txt",
    ]
    assert git_out(root, "show", "HEAD:a.txt") == "a\n"


def test_after_merge_leaves_the_index_while_an_operation_is_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _merged(tmp_path, monkeypatch)
    before = git_out(root, "rev-parse", "HEAD").strip()
    (root / ".git" / "CHERRY_PICK_HEAD").write_text(before + "\n", encoding="utf-8")

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert "an operation is in progress (CHERRY_PICK_HEAD)" in result.output
    assert git_out(root, "rev-parse", "HEAD").strip() == before


def test_after_merge_leaves_the_index_while_another_merge_is_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MERGE_HEAD naming HEAD's own second parent is the merge git has just
    # committed. Naming anything else, it is a merge still to be concluded.
    root = _merged(tmp_path, monkeypatch)
    before = git_out(root, "rev-parse", "HEAD").strip()
    first_parent = git_out(root, "rev-parse", "HEAD^1")
    (root / ".git" / "MERGE_HEAD").write_text(first_parent, encoding="utf-8")

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert "an operation is in progress (MERGE_HEAD)" in result.output
    assert git_out(root, "rev-parse", "HEAD").strip() == before


def test_after_merge_keeps_the_author_and_leaves_a_reflog_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path / "repo")
    _diverge(root)
    git(
        root,
        "-c",
        "user.name=Someone Else",
        "-c",
        "user.email=else@example.com",
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "merge side\n\nwith a body",
        "side",
    )
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["index", ".", "--after-merge"])
    assert result.exit_code == 0, result.output
    assert git_out(root, "log", "-1", "--format=%an <%ae>").strip() == (
        "Someone Else <else@example.com>"
    )
    assert git_out(root, "log", "-1", "--format=%B").strip() == (
        "merge side\n\nwith a body"
    )
    assert "planners: index repair after merge" in git_out(root, "reflog", "-1")


def test_the_repair_lands_in_the_merge_commit_when_git_runs_the_hook(
    tmp_path: Path,
) -> None:
    # The real path: git runs post-merge once the merge commit exists, and the
    # amend happens from inside that hook.
    root = _repo(tmp_path / "repo")
    _diverge(root)
    write_script(
        root / ".git" / "hooks" / "post-merge",
        f'exec "{sys.executable}" -c "from planners.cli import app; app()" '
        "index . --after-merge\n",
    )

    git(root, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    assert git_out(root, "status", "--porcelain") == ""
    assert git_out(root, "log", "-1", "--format=%s").strip() == "merge side"
    assert "006" in git_out(root, "show", f"HEAD:{INDEX}")
