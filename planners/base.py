"""Mainline-branch detection — which branches a ``plan [add]`` commit belongs on.

A plan's ``add`` and ``activate`` commits are supposed to land on the repo's
mainline *before* the feature branch exists, so the plan is recorded there
regardless of whether the branch ever merges. Nothing enforced that: ``add``
committed on whatever HEAD pointed at, and the ordering lived only in the
implement skill's prose — which a session can and did ignore, leaving both
commits reachable only from a branch that never merged.

This module answers the one question the guard needs: *is HEAD somewhere a plan
commit will survive?* It reports what git's refs currently say the mainline
branches are. That is a heuristic over present state, **not** a record of where
plans were actually committed — see :func:`detect` for what it cannot know.

Everything here is best-effort and read-only. A repo whose mainline cannot be
resolved yields :data:`UNRESOLVED`, which leaves the guard inert: this module
never blocks a repo it cannot reason about.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Mainline",
    "UNRESOLVED",
    "detect",
    "guard_message",
]

# Environment variables that relocate git's idea of "the repository". Left in
# place they outrank ``cwd``, so every command below would answer about a
# *different* repo than ``root`` — and the guard would clear a branch it never
# looked at. A guard that fails open is worse than no guard, so they are stripped
# for the duration of detection.
_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
)

# Checked in order when ``origin/HEAD`` gives us nothing. These are conventional
# names, so they are a fallback rather than the primary signal — a repo using
# neither is resolved by ``origin/HEAD`` above, or falls through to UNRESOLVED.
_FALLBACK_DEFAULTS = ("main", "master")

# The development-mainline branch, accepted alongside the default branch. Plans
# added on either one reach the mainline, so the guard takes a *set*: refusing a
# plan added on `main` in a repo that also has `dev` would block a commit that is
# not in fact lost.
_DEV = "dev"

# Said wherever a thin resolution is reported, so the refusal and the `base`
# command cannot drift into describing the same condition two different ways.
THIN_NOTE = (
    "refs/remotes/origin/HEAD is unset or dangling, so the default branch was "
    "guessed by name; `git remote set-head origin --auto` re-derives it from "
    "the remote."
)


@dataclass(frozen=True)
class Mainline:
    """The branches a plan commit may be committed on, and how they were found.

    ``branches`` is in resolution order, so ``branches[0]`` is the branch to name
    first in a message. ``current`` is HEAD's branch, or ``None`` when HEAD is
    detached. ``thin`` marks detection that fell back past ``origin/HEAD`` and so
    may be wrong in a way worth telling the user about.
    """

    branches: tuple[str, ...]
    current: str | None
    detached: bool
    unborn: bool
    thin: bool

    @property
    def resolved(self) -> bool:
        """True when at least one mainline branch was identified."""
        return bool(self.branches)

    @property
    def on_mainline(self) -> bool:
        """True when HEAD is on one of the detected mainline branches."""
        return self.current is not None and self.current in self.branches


# A repo we cannot reason about: not a git worktree, git missing, or no branches
# resolved. The guard treats this as "do not block". `thin` is False because
# nothing was resolved at all — there is no guessed-by-name answer to qualify, and
# every consumer checks `resolved` before ever reading it.
UNRESOLVED = Mainline(
    branches=(), current=None, detached=False, unborn=False, thin=False
)


def _git_out(root: Path, args: list[str]) -> str | None:
    """Run a read-only git command in ``root``; stdout stripped, or ``None``.

    ``None`` covers every failure uniformly — git missing from PATH, ``root`` not
    a worktree, or a non-zero exit (which for the ``--verify``/``-q`` forms used
    here simply means "that ref does not exist"). Callers treat it as absence,
    never as an error to surface, because detection degrades to
    :data:`UNRESOLVED` rather than failing a command.

    ``cwd=root`` alone does **not** pin the repository: ``GIT_DIR`` and friends
    outrank it, so an inherited one silently answers about another repo entirely
    and the guard clears a branch it never inspected. :data:`_GIT_LOCATION_ENV`
    is stripped so detection describes ``root`` and nothing else.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            env=env,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_repo(root: Path) -> bool:
    """True when ``root`` is inside a git worktree (asks git, so worktrees count)."""
    return _git_out(root, ["rev-parse", "--git-dir"]) is not None


def _has_branch(root: Path, name: str) -> bool:
    """True when a local branch ``name`` exists."""
    return (
        _git_out(root, ["rev-parse", "--verify", "-q", f"refs/heads/{name}"])
        is not None
    )


def _default_branch(root: Path) -> str | None:
    """The remote's default branch per ``refs/remotes/origin/HEAD``, or ``None``.

    This is a *local* ref written at clone time (and by ``git remote set-head``);
    ``git fetch`` does not refresh it. So it is absent in clones made by tooling
    that skips it — the known weakness of this detection, reported as
    :attr:`Mainline.thin`.

    ``symbolic-ref`` happily reports a **dangling** target, so the name it gives
    is verified to exist before being trusted. Without that check a pruned or
    renamed-away default resolves to a branch nobody can check out, and the guard
    refuses while telling the user to switch to a ref that is not there.

    One case stays invisible on purpose: an ``origin/HEAD`` that still points at a
    real ref the remote has since demoted. Nothing local distinguishes that from a
    current answer, so it reports ``thin=False``. Only a fetch of the remote's
    HEAD (``git remote set-head origin --auto``) can settle it.
    """
    ref = _git_out(root, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"])
    if not ref:
        return None
    # `refs/remotes/origin/HEAD` resolves to `origin/<branch>`; we want the branch.
    prefix = "origin/"
    name = ref[len(prefix) :] if ref.startswith(prefix) else ref
    if not name:
        return None
    # Trust the name only if the remote-tracking ref behind it is really there.
    # `git checkout <name>` then works even with no local branch yet, because git
    # creates a tracking branch from `origin/<name>` — so a present remote ref is
    # enough to make the refusal's advice actionable.
    if (
        _git_out(root, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}"])
        is None
    ):
        return None
    return name


def detect(root: Path) -> Mainline:
    """Resolve ``root``'s mainline branches and where HEAD currently sits.

    Resolution order, accumulating a *set* rather than picking one base:

    1. a local ``dev`` branch, when it exists;
    2. ``refs/remotes/origin/HEAD`` — the remote's default branch as recorded at
       clone time;
    3. failing (2), a local ``main`` then ``master``;
    4. nothing resolved -> :data:`UNRESOLVED`, and the guard stays inert.

    **What this cannot know.** It reads the refs that exist now, so it cannot tell
    you which branch a repo's existing plans were actually committed on. Deriving
    that empirically — asking which branch contains the current ``plan [add]:``
    commits — was considered and rejected: it is circular for this guard, which
    exists precisely *because* those commits can land on the wrong branch, so a
    repo that already failed would learn the wrong answer from its own history.

    A repo with no commits yet (unborn HEAD) resolves to ``unborn=True`` with no
    branches: there is no mainline to be off of, so the first ``add`` in a fresh
    repo is never blocked.
    """
    if not _is_repo(root):
        return UNRESOLVED

    # An unborn HEAD (`git init`, nothing committed) names a branch that does not
    # exist yet. Nothing can be reachable-or-not from a mainline that has no
    # commits, so this is inert by construction, not a refusal.
    unborn = _git_out(root, ["rev-parse", "--verify", "-q", "HEAD"]) is None

    # `--show-current` prints empty on a detached HEAD, which is a distinct state
    # from "not a repo" and gets its own message: a commit made there is not on
    # any branch at all.
    shown = _git_out(root, ["branch", "--show-current"])
    current = shown or None
    detached = not unborn and not shown

    if unborn:
        return Mainline(
            branches=(),
            current=current,
            detached=False,
            unborn=True,
            thin=True,
        )

    branches: list[str] = []
    if _has_branch(root, _DEV):
        branches.append(_DEV)

    default = _default_branch(root)
    thin = default is None
    if default is not None:
        if default not in branches:
            branches.append(default)
    else:
        # No origin/HEAD to trust: fall back to the conventional names, taking
        # only those that actually exist so we never name a branch the user
        # cannot switch to. `_has_branch` is the whole filter — the candidates
        # are `main`/`master` and the list holds at most `dev`, so they cannot
        # collide.
        for name in _FALLBACK_DEFAULTS:
            if _has_branch(root, name):
                branches.append(name)
                break

    if not branches:
        return UNRESOLVED

    return Mainline(
        branches=tuple(branches),
        current=current,
        detached=detached,
        unborn=False,
        thin=thin,
    )


def guard_message(mainline: Mainline, action: str) -> str | None:
    """The refusal text for committing ``action`` here, or ``None`` to allow it.

    ``None`` — allow — covers every case where the guard has no standing: an
    unresolvable repo, a fresh repo with no commits, or HEAD already on a
    mainline branch. Only a resolved mainline that HEAD is demonstrably off of
    produces a message, so the guard's default is to get out of the way.
    """
    if not mainline.resolved or mainline.unborn:
        return None
    if mainline.on_mainline:
        return None

    named = ", ".join(mainline.branches)
    if mainline.detached:
        where = "HEAD is detached"
        why = (
            f"a `{action}` commit made here is on no branch at all and is lost on "
            "the next checkout."
        )
    else:
        where = f"HEAD is on '{mainline.current}', which is not a mainline branch"
        why = (
            f"a `{action}` commit belongs on the mainline so the plan is recorded "
            "there even if this branch is never merged."
        )

    lines = [
        f"{where} ({named}).",
        f"  {why}",
        f"  Switch to {mainline.branches[0]} and re-run, or pass --allow-branch to "
        "commit here anyway.",
    ]
    if mainline.thin:
        lines.append(f"  note: {THIN_NOTE}")
    return "\n".join(lines)
