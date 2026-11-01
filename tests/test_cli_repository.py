"""The CLI refuses to run outside a git repository, and says so before it writes."""

import subprocess
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from planners.cli import app
from tests.helpers import commit_all, init_git

pytestmark = pytest.mark.no_repo

runner = CliRunner()

URL = "https://github.com/owner/repo/pull/1"

# Every command the guard stops when the current directory has no repository.
GUARDED = {
    "activate": ["activate", "001"],
    "add": ["add", "probe"],
    "block": ["block", "001"],
    "conclude": ["conclude", "001"],
    "finalize": ["finalize"],
    "finish": ["finish", "001"],
    "implemented": ["implemented", "001"],
    "install": ["install"],
    "log": ["log", "001", "a note"],
    "retire": ["retire", "001"],
    "review": ["review"],
    "set-pr": ["set-pr", "001", URL],
    "start": ["start", "001"],
    "subplans": ["subplans", "001"],
}

# Commands that check the path they are given, which defaults to the current one.
PATH_CHECKED = {
    "base": ["base"],
    "index": ["index"],
    "remote": ["remote"],
}

# Commands that run anywhere, each with arguments that succeed.
ANYWHERE = {
    "doc": ["doc", "orchestrated-run"],
    "permissions": ["permissions"],
    "rule": ["rule"],
    "schema": ["schema"],
    "skill": ["skill"],
    "validate": ["validate", "--allow-empty"],
}

REFUSED = [
    *GUARDED.values(),
    *PATH_CHECKED.values(),
    ["install", "--global"],
    ["install", "--local"],
    ["install", "--check"],
    ["install", "--force"],
]


def _tree(path: Path) -> list[str]:
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*"))


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory with no repository, under a sandboxed ``$HOME``."""
    home = tmp_path / "home"
    start = home / "notes"
    start.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(start)
    return start


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit, beside ``bare`` rather than around it."""
    path = tmp_path / "repo"
    path.mkdir()
    init_git(path)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    commit_all(path, "first")
    return path


def test_every_command_is_accounted_for() -> None:
    """A new command is guarded by default; this makes its author say so."""
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    assert set(commands) == {*GUARDED, *PATH_CHECKED, *ANYWHERE}


@pytest.mark.parametrize("args", REFUSED, ids=" ".join)
def test_refuses_and_writes_nothing(
    args: list[str], bare: Path, tmp_path: Path
) -> None:
    before = _tree(tmp_path)

    result = runner.invoke(app, args)

    assert result.exit_code == 1, result.output
    assert "needs a git repository" in result.stderr
    assert "nothing to repair" in result.stderr
    assert str(bare) in result.stderr
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "args",
    [
        ["add", "probe", "--title", "--help", "--no-commit"],
        ["log", "001", "--", "--help"],
    ],
    ids=" ".join,
)
def test_the_word_help_as_a_value_is_not_a_request_for_help(
    args: list[str], bare: Path, tmp_path: Path
) -> None:
    before = _tree(tmp_path)

    result = runner.invoke(app, args)

    assert result.exit_code == 1, result.output
    assert "needs a git repository" in result.stderr
    assert _tree(tmp_path) == before


def test_a_missing_git_is_not_reported_as_a_missing_repository(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", "")

    result = runner.invoke(app, ["add", "probe", "--no-commit"])

    assert result.exit_code == 1, result.output
    assert "needs git" in result.stderr
    assert "git init" not in result.stderr
    assert not (repo / ".planners").exists()


def test_a_repository_git_refuses_is_refused_with_git_s_reason(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    # Git's own test switch for a repository owned by someone else.
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")

    result = runner.invoke(app, ["add", "probe", "--no-commit"])

    assert result.exit_code == 1, result.output
    assert "safe.directory" in result.stderr
    assert not (repo / ".planners").exists()


def test_a_file_named_as_the_repository_is_refused(bare: Path) -> None:
    named = bare / "not-a-directory"
    named.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["index", str(named)])

    assert result.exit_code == 1, result.output
    assert "not a directory" in result.stderr


def test_a_stray_empty_git_directory_is_not_a_repository(bare: Path) -> None:
    """It passes a look at the filesystem, but every commit would fail there."""
    (bare / ".git").mkdir()

    result = runner.invoke(app, ["install", "--global"])

    assert result.exit_code == 1, result.output
    assert not (bare / ".gitattributes").exists()
    assert not (bare / ".pre-commit-config.yaml").exists()


def test_a_bare_repository_is_not_a_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
    monkeypatch.chdir(path)

    assert runner.invoke(app, ["add", "probe"]).exit_code == 1
    assert not (path / ".planners").exists()


def test_an_ambient_git_dir_does_not_answer_for_the_directory(
    bare: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git exports ``GIT_DIR`` to hooks, so it can name a repository elsewhere."""
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))

    assert runner.invoke(app, ["add", "probe"]).exit_code == 1
    assert not (bare / ".planners").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["--version"],
        ["add", "--help"],
        ["install", "--help"],
        ["index", "--help"],
    ],
    ids=" ".join,
)
def test_help_and_version_run_anywhere(args: list[str], bare: Path) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("args", ANYWHERE.values(), ids=" ".join)
def test_exempt_commands_run_anywhere(
    args: list[str], bare: Path, tmp_path: Path
) -> None:
    before = _tree(tmp_path)

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    assert _tree(tmp_path) == before


def test_commands_run_from_a_subdirectory_of_a_repository(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    below = repo / "docs" / "deep"
    below.mkdir(parents=True)
    monkeypatch.chdir(below)

    result = runner.invoke(app, ["add", "probe", "--no-commit"])

    assert result.exit_code == 0, result.output


def test_commands_run_from_a_linked_worktree(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "side", str(linked)],
        cwd=repo,
        check=True,
    )
    monkeypatch.chdir(linked)

    result = runner.invoke(app, ["add", "probe", "--no-commit"])

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("command", ["index", "base", "remote"])
def test_a_named_path_is_what_gets_checked(
    command: str, bare: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = runner.invoke(app, [command, str(repo)])
    assert "needs a git repository" not in result.stderr
    assert result.exit_code == 0, result.output

    # And the other way round: from a repository, naming a directory outside one.
    monkeypatch.chdir(repo)
    result = runner.invoke(app, [command, str(bare)])
    assert result.exit_code == 1, result.output
    assert "needs a git repository" in result.stderr
    assert not (bare / ".planners").exists()


def test_install_from_a_repository_still_writes_its_wiring(
    bare: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["install", "--global"])

    assert result.exit_code == 0, result.output
    assert (repo / ".gitattributes").exists()
    assert (repo / ".pre-commit-config.yaml").exists()
