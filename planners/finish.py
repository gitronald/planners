"""The routine end of a close: merge, pull, delete the branch, re-point the hooks.

A close used to end with a block of commands for whoever was running it, and a
session could, and did, hand that block to the user instead of running it. Every
step in it is mechanical: remove the worktree, merge the PR, pull the base,
delete the branch on the remote and locally, regenerate the index, re-point any
hook installed from inside the worktree. ``planners finish`` runs them, and stops
only where a person has something to look at.

This module holds the pieces ``finish`` is built from: finding the branch's
worktree, reading and waiting on the PR, the merge subject, the safe branch
deletions, and the hook re-point. Each raises :class:`Stop` for a real issue and
leaves the state as it found it, so a re-run after the issue is dealt with picks
up where the last run ended. A step whose work is already done is a no-op.
"""

from __future__ import annotations

import json
import re
import time
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
    "wait_ready",
]

# The commit-subject limit the merge subject is truncated to.
MERGE_SUBJECT_LIMIT = 60

# CheckRun conclusions and StatusContext states that mean a check failed. A
# skipped or neutral check is not a failure.
_FAILED = frozenset(
    {
        "FAILURE",
        "ERROR",
        "CANCELLED",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "STARTUP_FAILURE",
    }
)
_PENDING_STATES = frozenset({"PENDING", "EXPECTED"})

_PR_FIELDS = (
    "number,state,isDraft,mergeable,baseRefName,headRefName,"
    "isCrossRepository,headRepositoryOwner,statusCheckRollup"
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
    draft: bool
    mergeable: str
    base: str
    head: str
    fork_owner: str | None
    pending: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def label(self) -> str:
        """The branch as a merge subject names it: ``<owner>/<branch>`` for a fork."""
        if self.fork_owner:
            return f"{self.fork_owner}/{self.head}"
        return self.head

    @classmethod
    def from_json(cls, data: dict[str, object]) -> PullRequest:
        pending: list[str] = []
        failed: list[str] = []
        checks: object = data.get("statusCheckRollup") or ()
        for check in checks if isinstance(checks, list) else ():
            if not isinstance(check, dict):
                continue
            name = str(check.get("name") or check.get("context") or "check")
            if check.get("__typename") == "StatusContext":
                state = str(check.get("state") or "")
                if state in _PENDING_STATES:
                    pending.append(name)
                elif state in _FAILED:
                    failed.append(name)
            elif check.get("status") != "COMPLETED":
                pending.append(name)
            elif str(check.get("conclusion") or "") in _FAILED:
                failed.append(name)
        owner = data.get("headRepositoryOwner")
        login = owner.get("login") if isinstance(owner, dict) else None
        number = data.get("number")
        return cls(
            number=number if isinstance(number, int) else 0,
            state=str(data.get("state") or ""),
            draft=bool(data.get("isDraft")),
            mergeable=str(data.get("mergeable") or "UNKNOWN"),
            base=str(data.get("baseRefName") or ""),
            head=str(data.get("headRefName") or ""),
            fork_owner=str(login) if data.get("isCrossRepository") and login else None,
            pending=tuple(pending),
            failed=tuple(failed),
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


def wait_ready(
    root: Path,
    ref: str,
    *,
    timeout: float,
    interval: float,
    say: Say,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PullRequest:
    """The PR once it can be merged, or already is; a :class:`Stop` otherwise.

    GitHub recomputes mergeability after every push, and reports ``UNKNOWN``
    until it has. Checks that a push started are pending for a while. Both are
    waited out, up to ``timeout`` seconds, before either is read as a problem. A
    draft, a closed PR, a failed check, and a conflict stop at once: waiting
    does not change them.
    """
    started = clock()
    waiting_on: str | None = None
    while True:
        pr = view_pr(root, ref)
        if pr.state == "MERGED":
            return pr
        if pr.state == "CLOSED":
            raise Stop(f"PR #{pr.number} is closed without being merged")
        if pr.draft:
            raise Stop(
                f"PR #{pr.number} is a draft; take it out of draft "
                f"(`gh pr ready {pr.number}`) once the review gate has passed"
            )
        if pr.failed:
            raise Stop(f"PR #{pr.number} has failing checks: {', '.join(pr.failed)}")
        if pr.mergeable == "CONFLICTING":
            raise Stop(
                f"PR #{pr.number} conflicts with {pr.base}; merge {pr.base} into "
                f"{pr.head}, resolve, and push"
            )
        if pr.pending:
            now_waiting = f"checks to finish ({', '.join(pr.pending)})"
        elif pr.mergeable == "UNKNOWN":
            now_waiting = "GitHub to compute mergeability"
        else:
            return pr
        if clock() - started >= timeout:
            raise Stop(
                f"PR #{pr.number} is still waiting on {now_waiting} after "
                f"{timeout:g}s; re-run finish once it settles"
            )
        if now_waiting != waiting_on:
            say(f"waiting on {now_waiting}")
            waiting_on = now_waiting
        sleep(interval)


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
