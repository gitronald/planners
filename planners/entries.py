"""The standard Log entries the lifecycle commands write, and reading them back.

``activate``, ``set-pr``, and ``implemented`` each append a dated entry to a
plan's ``## Log``, so every plan records where its work lives and when it moved
in the same words: activated, PR opened, implemented. The entries are generated
here rather than hand-written, which is what keeps their fields the same from
plan to plan, and what lets a later command read one back.

Everything here is a pure transform of strings: no filesystem, no git, no clock.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

from planners.body import fenced_lines, section_span

__all__ = [
    "NO_WORKTREE",
    "activation_entry",
    "default_worktree",
    "implemented_entry",
    "pr_entry",
    "reactivation_entry",
    "recorded_base",
    "worktree_error",
]

# What the Worktree field says when the work happens in the main checkout.
NO_WORKTREE = "none (main checkout)"

# The base branch as the activation entry records it: "- Base: `dev` at `abc1234`".
_BASE_RE = re.compile(r"^\s*-\s+Base:\s+`([^`]+)`")


def _stamp(when: str, sentence: str) -> str:
    return f"- **{when}** — {sentence}"


def default_worktree(branch: str) -> str:
    """The worktree the implement skill creates for ``branch``.

    ``.worktrees/<branch-suffix>``, where the suffix is the branch's final path
    component, so ``feature/<slug>`` works in ``.worktrees/<slug>``.
    """
    return f".worktrees/{branch.rstrip('/').rsplit('/', 1)[-1]}"


def worktree_error(path: str) -> str | None:
    """Why ``path`` cannot be recorded as a worktree, or ``None`` when it can.

    A plan is a shared record, so the path must be repo-relative. An absolute
    path, in either POSIX or Windows form, or one under a home directory, names
    a single machine and is refused.
    """
    if not path.strip():
        return "the worktree path is empty"
    if (
        PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or path.startswith("~")
    ):
        return (
            f"worktree {path!r} is not repo-relative; record a path from the "
            "repo root, such as .worktrees/<name>"
        )
    return None


def activation_entry(
    when: str,
    *,
    branch: str,
    base: str | None,
    sha: str | None,
    worktree: str,
    pr: str | None,
) -> str:
    """The entry ``activate`` writes: where the work will happen.

    ``base`` is the branch the activation is committed on and ``sha`` the commit
    it sits on, HEAD before the activation commit. Either can be unknown: a
    detached HEAD has no branch, and an unborn one has no commit.
    """
    if base is None:
        where = "a detached HEAD"
    else:
        where = f"`{base}`"
    where += f" at `{sha}`" if sha else " (no commits yet)"
    return "\n".join(
        [
            _stamp(when, "Activated."),
            f"  - Branch: `{branch}`",
            f"  - Base: {where}",
            f"  - Worktree: {worktree if worktree == NO_WORKTREE else f'`{worktree}`'}",
            f"  - PR: {pr or 'pending'}",
        ]
    )


def reactivation_entry(when: str) -> str:
    """The entry ``activate`` writes when review sends a plan back to work."""
    return _stamp(when, "Reactivated: back to active after review.")


def pr_entry(when: str, url: str) -> str:
    """The entry ``set-pr`` writes."""
    return _stamp(when, f"PR opened: {url}")


def implemented_entry(when: str, ahead: int | None, base: str | None) -> str:
    """The entry ``implemented`` writes, with how far the work runs past its base.

    The count is left out when it cannot be measured (no base recorded or found,
    or the base branch is not in this clone), rather than guessed.
    """
    if ahead is None or base is None:
        return _stamp(when, "Implemented.")
    noun = "commit" if ahead == 1 else "commits"
    return _stamp(when, f"Implemented: {ahead} {noun} ahead of `{base}`.")


def recorded_base(text: str) -> str | None:
    """The base branch the last activation entry in ``text``'s Log recorded.

    Only the ``## Log`` section is read, and nothing inside a code fence, so a
    spec that shows an example entry is not taken for the record. The last entry
    wins, so a plan activated twice (a draft reopened after it was set aside)
    reports the base its current work came from. ``None`` when there is no entry.
    """
    span = section_span(text, "Log")
    if span is None:
        return None
    lines = text.splitlines()[span[0] : span[1]]
    found: str | None = None
    for line, fenced in zip(lines, fenced_lines(lines), strict=True):
        match = None if fenced else _BASE_RE.match(line)
        if match:
            found = match.group(1)
    return found
