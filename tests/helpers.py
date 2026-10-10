"""Git helpers shared by the CLI test modules."""

import stat
import subprocess
from pathlib import Path


def git(path: Path, *args: str) -> None:
    """Run a git command in ``path``, quietly, failing the test on error."""
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def set_identity(path: Path) -> None:
    """Give the repo at ``path`` a commit identity."""
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")


def init_git(path: Path) -> None:
    """Make ``path`` a repo on ``main`` with a commit identity."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    set_identity(path)


def bare_remote(root: Path, remote: Path) -> None:
    """Create a bare repo at ``remote`` and add it to ``root`` as ``origin``."""
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(root, "remote", "add", "origin", str(remote))


def write_script(path: Path, body: str) -> None:
    """Write an executable ``sh`` script: a fake binary or a hook."""
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def commit_all(path: Path, message: str, date: str | None = None) -> None:
    """Stage everything and commit, optionally with a fixed authored date."""
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    args = ["git", "commit", "-qm", message]
    if date is not None:
        args.append(f"--date={date}")
    subprocess.run(args, cwd=path, check=True)


def git_out(path: Path, *args: str) -> str:
    """The stdout of a git command run in ``path``."""
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    ).stdout
