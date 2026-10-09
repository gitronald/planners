"""The routine end of a close: the worktree, the branches, the index, the hooks.

A close used to end with a block of commands for whoever was running it, and a
session could, and did, hand that block to the user instead of running it. The
steps after the merge are mechanical: remove the worktree, pull the base, delete
the branch on the remote and locally, regenerate the index, and re-point any
hook installed from inside the worktree. ``planners finish`` runs them, and stops
only where a person has something to look at.

**The merge itself is not here.** It stays a ``gh pr merge`` (or ``git merge``
and ``git push``) that the session runs as its own command. A permission rule
can only see the command a session runs, not what that command runs in turn.
Under a profile that allows ``planners``, a merge made from inside ``finish``
would skip the gate that the ``full`` automation level exists to open. For the
same reason ``finish`` publishes no code. Its one remote write deletes a branch
that the remote's base already contains.

This module holds the pieces ``finish`` is built from. Each raises :class:`Stop`
for a real issue and leaves the state as it found it, so a re-run after the
issue is dealt with picks up where the last run ended. A step whose work is
already done is a no-op.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from planners import proc

__all__ = [
    "MERGE_SUBJECT_LIMIT",
    "PullRequest",
    "Stop",
    "delete_local_branch",
    "delete_remote_branch",
    "find_worktree",
    "is_ancestor",
    "merge_subject",
    "must",
    "repoint_hooks",
    "stale_hooks",
    "view_pr",
]

# The commit-subject limit the merge subject is truncated to.
MERGE_SUBJECT_LIMIT = 60

_PR_FIELDS = (
    "number,state,baseRefName,headRefName,isCrossRepository,headRepositoryOwner"
)

_INSTALL_PYTHON_RE = re.compile(r"^INSTALL_PYTHON=(.*)$", re.MULTILINE)


class Stop(Exception):
    """A real issue: ``finish`` stops here and leaves the state as it was."""


Say = Callable[[str], None]


def _call(root: Path, argv: Sequence[str]) -> tuple[int, str, str]:
    """Run ``argv`` in ``root``; a missing binary is a :class:`Stop`, not a crash."""
    try:
        result = proc.run(root, argv, capture_output=True)
    except OSError as exc:
        raise Stop(f"cannot run {argv[0]}: {exc}") from None
    return result.returncode, result.stdout, result.stderr


def must(root: Path, argv: Sequence[str]) -> str:
    """Stdout of ``argv`` run in ``root``, or a :class:`Stop` quoting the refusal.

    The refusal is quoted whole, since it is what the user needs to see: a
    permission denial, a failed auth, a conflict.
    """
    code, out, err = _call(root, argv)
    if code != 0:
        detail = (err or out).strip()
        raise Stop(
            f"`{' '.join(argv)}` failed (exit {code})"
            + (f":\n{detail}" if detail else "")
        )
    return out


def merge_subject(label: str, number: int | None = None) -> str:
    """``merge: PR #<N> - <label>``, or ``merge: <label>`` for a merge without a PR.

    The label is cut with a trailing ``...`` when the subject would pass
    :data:`MERGE_SUBJECT_LIMIT`; the prefix is never cut.
    """
    prefix = "merge: " if number is None else f"merge: PR #{number} - "
    room = MERGE_SUBJECT_LIMIT - len(prefix)
    if len(label) > room:
        label = label[: room - 3] + "..."
    return prefix + label


def find_worktree(root: Path, branch: str) -> Path | None:
    """The worktree that has ``branch`` checked out, or ``None``."""
    listing = proc.git_out(root, ["worktree", "list", "--porcelain"])
    if listing is None:
        return None
    for block in listing.split("\n\n"):
        path: str | None = None
        checked_out: str | None = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
            elif line.startswith("branch "):
                checked_out = line[len("branch ") :]
        if path is not None and checked_out == f"refs/heads/{branch}":
            return Path(path)
    return None


def is_ancestor(root: Path, commit: str, of: str) -> bool:
    """True when ``of`` contains ``commit``."""
    code, _, _ = _call(root, ["git", "merge-base", "--is-ancestor", commit, of])
    return code == 0


@dataclass(frozen=True)
class PullRequest:
    """What ``finish`` needs to know about a PR, read from ``gh pr view``."""

    number: int
    state: str
    base: str
    head: str
    fork_owner: str | None

    @property
    def label(self) -> str:
        """The branch as a merge subject names it: ``<owner>/<branch>`` for a fork."""
        if self.fork_owner:
            return f"{self.fork_owner}/{self.head}"
        return self.head

    @classmethod
    def from_json(cls, data: dict[str, object]) -> PullRequest:
        owner = data.get("headRepositoryOwner")
        login = owner.get("login") if isinstance(owner, dict) else None
        number = data.get("number")
        return cls(
            number=number if isinstance(number, int) else 0,
            state=str(data.get("state") or ""),
            base=str(data.get("baseRefName") or ""),
            head=str(data.get("headRefName") or ""),
            fork_owner=str(login) if data.get("isCrossRepository") and login else None,
        )


def view_pr(root: Path, ref: str) -> PullRequest:
    """The PR ``ref`` (a number or URL) as ``gh pr view`` reports it now."""
    out = must(root, ["gh", "pr", "view", ref, "--json", _PR_FIELDS])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise Stop(f"`gh pr view {ref}` printed something that is not JSON") from None
    if not isinstance(data, dict):
        raise Stop(f"`gh pr view {ref}` printed something that is not a PR")
    return PullRequest.from_json(data)


def delete_remote_branch(root: Path, branch: str, base: str, say: Say) -> None:
    """Delete ``branch`` on ``origin`` if it is still there and ``base`` holds it.

    Compared as last fetched, so the caller fetches first. A remote branch with
    commits the base lacks is a stop: deleting it would lose them.
    """
    remotes = (proc.git_out(root, ["remote"]) or "").split()
    if "origin" not in remotes:
        return
    listed = must(root, ["git", "ls-remote", "--heads", "origin", branch])
    if not listed.strip():
        say(f"{branch} is already gone from origin")
        return
    tracking = f"refs/remotes/origin/{branch}"
    if not is_ancestor(root, tracking, base):
        raise Stop(f"origin/{branch} holds commits {base} does not; it was not deleted")
    must(root, ["git", "push", "origin", "--delete", branch])
    say(f"deleted {branch} on origin")


def delete_local_branch(root: Path, branch: str, base: str, say: Say) -> None:
    """Delete the local ``branch`` when ``base`` contains it. Never ``-D``."""
    exists = proc.git_out(root, ["rev-parse", "--verify", "-q", f"refs/heads/{branch}"])
    if exists is None:
        say(f"{branch} is already gone locally")
        return
    if not is_ancestor(root, f"refs/heads/{branch}", base):
        raise Stop(
            f"{branch} holds commits {base} does not; it was not deleted. "
            f"`git log {base}..{branch}` lists them"
        )
    must(root, ["git", "branch", "-d", branch])
    say(f"deleted {branch} locally")


def stale_hooks(root: Path) -> list[str]:
    """The installed hooks whose ``INSTALL_PYTHON`` points into ``.worktrees/``.

    pre-commit writes the interpreter it was installed with into each hook, and
    worktrees share one ``hooks`` directory. A hook installed from inside a
    worktree therefore runs that worktree's ``.venv``, which goes with the
    worktree. Worse, the generated script skips quietly when the interpreter is
    missing, so the hook stops running with no error at all.
    """
    hooks = proc.git_out(
        root, ["rev-parse", "--path-format=absolute", "--git-path", "hooks"]
    )
    if hooks is None:
        return []
    directory = Path(hooks.strip())
    if not directory.is_dir():
        return []
    found: list[str] = []
    for hook in sorted(directory.iterdir()):
        if not hook.is_file() or hook.suffix == ".sample":
            continue
        try:
            text = hook.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = _INSTALL_PYTHON_RE.search(text)
        if match and "/.worktrees/" in match.group(1):
            found.append(hook.name)
    return found


def repoint_hooks(root: Path, say: Say) -> None:
    """Re-install every hook :func:`stale_hooks` finds, from ``root``."""
    for name in stale_hooks(root):
        must(root, ["uv", "run", "pre-commit", "install", "--hook-type", name])
        say(f"re-installed the {name} hook from the main checkout")
