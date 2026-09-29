"""Git helpers shared by the CLI test modules."""

import subprocess
from pathlib import Path


def init_git(path: Path) -> None:
    """Make ``path`` a repo on ``main`` with a commit identity."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


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
