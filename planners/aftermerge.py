"""Put the index repair that follows a merge into the merge commit itself.

A merge resolves the tracked index with ``merge=union``, which can leave a row
duplicated or out of order, and only once the merge commit exists are both sides'
plan files on disk to regenerate from. The ``post-merge`` hook therefore runs after
the commit, and its repair used to be left as an uncommitted change that a session
committed by hand, in a commit holding nothing else.

:func:`repair` rewrites the merge commit to carry the regenerated index: same
parents, same message, same author, a tree that differs in that one file.

**Why plumbing and not ``git commit --amend``.** Git runs ``post-merge`` before it
clears the merge state, so ``MERGE_HEAD`` is still there, and ``commit --amend``
refuses ("in the middle of a merge") while a plain ``commit`` would record a second
merge. ``commit-tree`` and ``update-ref`` do not read that state. The tree is built
in a scratch index, so nothing else staged or modified is swept in.

The rewrite is refused, and the repair left uncommitted with the reason, whenever
it could touch something it should not: a commit that is not a merge, one a remote
branch already holds, a signed one (the signature would be dropped), or any
operation in progress other than the merge git has just committed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from planners import proc

__all__ = ["repair"]

# State that means git is in the middle of something a rewrite of HEAD would break.
_IN_PROGRESS = ("CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


class _Refused(Exception):
    """A git call in the rewrite failed; the repair stays uncommitted."""


def _git(
    root: Path,
    args: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> str:
    """Stdout of a git command in ``root``, raising :class:`_Refused` on failure."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            input=stdin,
            env={**proc.pinned_env(), **(env or {})},
        )
    except OSError as exc:
        raise _Refused(f"git could not run ({exc})") from None
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        raise _Refused(
            f"`git {args[0]}` failed ({lines[-1] if lines else 'no output'})"
        )
    return done.stdout


def _git_path(root: Path, name: str) -> Path:
    """Where git keeps ``name`` for this worktree."""
    return root / _git(root, ["rev-parse", "--git-path", name]).strip()


def _blocker(root: Path, head: str, parents: list[str]) -> str | None:
    """Why HEAD cannot be rewritten, or ``None`` when it can."""
    if len(parents) < 2:
        return "HEAD is not a merge commit"
    for marker in _IN_PROGRESS:
        if _git_path(root, marker).exists():
            return f"an operation is in progress ({marker})"
    # Git clears MERGE_HEAD only after post-merge returns, so its presence is
    # expected here. It is a different merge only when it does not name the
    # parents HEAD already has.
    merge_head = _git_path(root, "MERGE_HEAD")
    if merge_head.exists():
        merging = merge_head.read_text(encoding="utf-8").split()
        if merging != parents[1:]:
            return "an operation is in progress (MERGE_HEAD)"
    remote = _git(root, ["branch", "-r", "--contains", head]).split()
    if remote:
        return f"the merge commit is already on {remote[0]}"
    if "\ngpgsig" in "\n" + _git(root, ["cat-file", "commit", head]).split("\n\n")[0]:
        return "the merge commit is signed"
    return None


def _rewrite(root: Path, head: str, parents: list[str], index: str) -> str:
    """Commit HEAD again with ``index`` as it is on disk, and move HEAD to it."""
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": os.path.join(scratch, "index")}
        _git(root, ["read-tree", head], env=env)
        _git(root, ["update-index", "--add", "--", index], env=env)
        tree = _git(root, ["write-tree"], env=env).strip()
    name, email, date = _git(
        root, ["log", "-1", "--format=%an%n%ae%n%aI", head]
    ).splitlines()
    message = _git(root, ["log", "-1", "--format=%B", head])
    author = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": date,
    }
    wanted = [arg for parent in parents for arg in ("-p", parent)]
    new = _git(
        root, ["commit-tree", tree, *wanted, "-F", "-"], env=author, stdin=message
    ).strip()
    _git(
        root,
        ["update-ref", "-m", "planners: index repair after merge", "HEAD", new, head],
    )
    # The real index still holds the merge's copy of the file; bring it level.
    _git(root, ["update-index", "--", index])
    return new


def repair(root: Path, index: str) -> str:
    """Move a regenerated ``index`` into the merge commit at HEAD; say what happened.

    ``index`` is the repo-relative path of the generated index, already rewritten on
    disk. Returns one line for the caller to print: that nothing needed repair, that
    the merge commit now carries it, or that it was left uncommitted and why.
    """
    left = f"left {index} uncommitted"
    try:
        if not _git(root, ["status", "--porcelain", "--", index]).strip():
            return "the index needed no repair after the merge"
        head, *parents = _git(
            root, ["rev-list", "--parents", "-n", "1", "HEAD"]
        ).split()
        blocker = _blocker(root, head, parents)
        if blocker:
            return f"{left}: {blocker}"
        new = _rewrite(root, head, parents, index)
    except _Refused as exc:
        return f"{left}: {exc}"
    return f"amended {index} into the merge commit {new[:7]}"
