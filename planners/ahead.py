"""What ``activate`` reports about the base's unpushed commits.

The ``implement`` skill pushes the base right after ``activate``, and that push
publishes every unpushed commit on the base along with the activation. Most of
them are the plan's own — its ``plan [add]`` commit, the commits of its nested
subplans, edits to its files — and a confirmation on every push would be noise.
The case worth catching is unrelated work riding along, and sorting the two by
eye is the kind of prose step that gets skipped.

So ``activate`` counts and sorts, and the skill reads the result. This module is
the counting: which commits sit ahead of the upstream, which paths each touches,
and whether every path belongs to the plan. It never pushes, never fetches, and
never refuses — the report is information, and it goes quiet when there is
nothing to compare against (no upstream, no remote), the same stance as the
mainline guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from planners import proc
from planners.index import INDEX_PATH

__all__ = [
    "Ahead",
    "Commit",
    "count",
    "parse_log",
    "report",
]

# The generated index: the one file outside a plan's directory that a plan's own
# commits legitimately touch (``add``/``activate``/``set-pr`` all refresh it).
_INDEX = INDEX_PATH.as_posix()

# Record separator for the parsed log. ``%x1e`` is ASCII RS, which no path or
# subject contains, so a record boundary is unambiguous where a blank line is not.
_RS = "\x1e"


@dataclass(frozen=True)
class Commit:
    """One commit ahead of the upstream, with the paths it touches."""

    sha: str
    subject: str
    paths: tuple[str, ...]

    def is_own(self, plan_dir: str) -> bool:
        """Whether every touched path is the plan's: under ``plan_dir`` or the index.

        ``plan_dir`` is repo-relative (``.planners/plans/008-slug``) and covers
        nested subplans and sidecars, which live beneath it. A commit touching
        nothing — a merge, or an empty commit — is *not* its own: a merge of
        unrelated work is exactly the ride-along worth showing, and an empty
        commit costs one line to confirm.
        """
        if not self.paths:
            return False
        prefix = plan_dir.rstrip("/") + "/"
        return all(p == _INDEX or p.startswith(prefix) for p in self.paths)

    @property
    def oneline(self) -> str:
        """The commit as ``git log --oneline`` would print it."""
        return f"{self.sha} {self.subject}"


@dataclass(frozen=True)
class Ahead:
    """The base's position against its upstream, sorted by ownership."""

    branch: str
    upstream: str
    own: tuple[Commit, ...] = field(default_factory=tuple)
    other: tuple[Commit, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.own) + len(self.other)


def parse_log(text: str) -> list[Commit]:
    """Parse ``git log --format=%x1e%h %s --name-only`` output into commits.

    Each record is ``<sha> <subject>`` on its first line, a blank line, then one
    path per line (``--name-only`` lists none for a merge commit). Tolerant of
    the trailing newline git adds and of the leading empty record the separator
    produces.
    """
    commits: list[Commit] = []
    for record in text.split(_RS):
        lines = record.split("\n")
        if not lines or not lines[0].strip():
            continue
        head = lines[0]
        sha, _, subject = head.partition(" ")
        paths = tuple(line.strip() for line in lines[1:] if line.strip())
        commits.append(Commit(sha=sha, subject=subject, paths=paths))
    return commits


def _git_out(root: Path, args: list[str]) -> str | None:
    """Stdout of a git command in ``root``, or ``None`` on any failure."""
    try:
        result = proc.run(root, ["git", *args], capture_output=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def count(root: Path, branch: str, plan_dir: str) -> Ahead | None:
    """Sort the commits on ``branch`` ahead of its upstream into own and other.

    Compares against the local remote-tracking ref as last fetched — this never
    fetches, so a checkout behind its remote gives a true count of a stale
    comparison. Returns ``None`` when there is nothing to compare against: no
    upstream configured, no remote, or git unavailable.
    """
    upstream = _git_out(
        root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    if upstream is None or not upstream.strip():
        return None
    upstream = upstream.strip()
    log = _git_out(
        root, ["log", f"--format={_RS}%h %s", "--name-only", f"{upstream}..HEAD"]
    )
    if log is None:
        return None
    commits = parse_log(log)
    own = tuple(c for c in commits if c.is_own(plan_dir))
    other = tuple(c for c in commits if not c.is_own(plan_dir))
    return Ahead(branch=branch, upstream=upstream, own=own, other=other)


def report(ahead: Ahead, prefix: str) -> list[str]:
    """The lines ``activate`` prints after its commit.

    One summary line always; when some commits are not the plan's own, each one
    follows on its own line as ``git log --oneline`` would print it, so the
    skill can show the list and ask before pushing.
    """
    lines = [
        f"{ahead.branch} is {ahead.total} ahead of {ahead.upstream} (as last "
        f"fetched): {len(ahead.own)} are plan {prefix}'s own, "
        f"{len(ahead.other)} are other"
    ]
    lines.extend(f"  {c.oneline}" for c in ahead.other)
    return lines
