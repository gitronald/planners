"""Subprocess calls pinned to a repo root, immune to git's location variables.

Every shell-out in this package is *about* one repository: the one whose plans are
being written. Passing ``cwd=root`` is not enough to say so. Git's location
variables — ``GIT_DIR`` and friends — outrank ``cwd``, so an inherited one silently
redirects the command to a different repository: detection describes a repo it
never looked at, and a commit lands in someone else's history while the files the
user was looking at stay uncommitted.

That is a reachable state, not a hypothetical. Git exports ``GIT_DIR`` to every
hook it runs, so anything invoking ``planners`` from a hook, a wrapper script, or a
shell where an earlier command left the variable set inherits it. Nothing warns.

**An ambient ``GIT_DIR`` is never honored here, deliberately.** Someone could in
principle set it to aim a commit at another repo, but that was never coherent:
plan files are written relative to the working directory, so honoring ``GIT_DIR``
puts the files in one repo and the commit in another — precisely the bug this
module exists to prevent. The target repository is named by ``root``, and only by
``root``.

:func:`run` also fronts the ``uv``/``pre-commit`` shell-outs, which invoke git
internally and so inherit the same hazard one level down.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    "LOCATION_ENV",
    "pinned_env",
    "run",
]

# The variables that relocate git's idea of "the repository". Stripped for the
# duration of every call so ``root`` is the only thing that selects a repo.
# ``GIT_CONFIG_*`` and ``GIT_CEILING_DIRECTORIES`` are deliberately *not* here:
# they change what git reads, not which repository it acts on, and the test suite
# relies on setting them.
LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
)


def pinned_env() -> dict[str, str]:
    """The current environment minus :data:`LOCATION_ENV`."""
    return {k: v for k, v in os.environ.items() if k not in LOCATION_ENV}


def run(
    root: Path,
    argv: Sequence[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` in ``root`` with the git location variables stripped.

    Never ``shell=True`` and never ``check=True``: callers decide what a non-zero
    exit means (for the ``rev-parse --verify -q`` forms it just means "no such
    ref"), and they translate the raising failures — a missing binary — into their
    own idiom. Output goes to the caller's terminal unless ``capture_output``.
    """
    return subprocess.run(
        list(argv),
        cwd=root,
        capture_output=capture_output,
        text=True,
        env=pinned_env(),
    )
