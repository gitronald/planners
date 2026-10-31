"""The routine start of a plan: the base, the branch, the worktree, the draft PR.

The ``implement`` skill used to walk a session through these steps in prose, and a
session interrupted partway (a lost VM, a refused command, a context reset) had to
work out by hand which of them had run. ``planners start`` runs them in order. Each
reads its own result first, so a re-run resumes where the last one ended, and each
reports one :class:`Step`, so the output is the resume record.

**The pushes are not here**, for the reason :mod:`planners.finish` keeps the merge
out: a permission rule can only see the command a session runs, not what that
command runs in turn. Under a profile that allows ``planners`` and not ``git push``,
a push made from inside ``start`` would skip the gate that the ``confirm``
automation level exists to open. So a step that needs a push raises
:class:`~planners.finish.Stop` with the command to run, and the re-run sees it done.
The draft PR is opened here because it publishes nothing the push did not.

This module holds the pieces ``start`` is built from.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from planners import ahead as ahead_mod
from planners import base as base_mod
from planners import entries, proc
from planners.finish import Stop, must
from planners.remote import RemoteKind

__all__ = [
    "DONE",
    "RAN",
    "SKIPPED",
    "Step",
    "check_base",
    "check_base_pushed",
    "check_branch_pushed",
    "create_draft_pr",
    "ensure_branch",
    "ensure_ignored",
    "ensure_worktree",
    "open_pr",
    "push_command",
    "set_up_worktree",
]

DONE = "done"
RAN = "ran"
SKIPPED = "skipped"

# Where the setup step records that it finished, under the worktree's own git
# directory: out of the tree, per worktree, and gone with the worktree. A setup
# hook's result cannot be read back, and a `.venv` can be a sync that stopped
# partway, so neither says whether the step finished.
_SETUP_MARKER = "planners-setup"

# The directory the default worktree lives under, which the step below ignores.
_WORKTREES_DIR = ".worktrees"


@dataclass(frozen=True)
class Step:
    """What one step found or did. ``notes`` are things it left for a person."""

    outcome: str
    detail: str
    notes: tuple[str, ...] = ()


def push_command(branch: str, *, upstream: bool = False) -> str:
    """The push for ``branch``, which names it so it works from any checkout."""
    flags = ["-u"] if upstream else []
    return shlex.join(["git", "push", *flags, "origin", branch])


def _uncommitted(root: Path, ignore: tuple[Path, ...]) -> list[str]:
    """The changed paths in ``root``, leaving out ``ignore``."""
    skipped = {path.relative_to(root).as_posix() for path in ignore}
    status = must(root, ["git", "status", "--porcelain"])
    paths = (line[3:] for line in status.splitlines())
    return [path for path in paths if path not in skipped]


def _upstream(root: Path) -> str | None:
    """HEAD's upstream as ``origin/<branch>``, or ``None`` when it has none."""
    out = proc.git_out(
        root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    return (out or "").strip() or None


def check_base(
    root: Path, mainline: base_mod.Mainline, *, ignore: tuple[Path, ...] = ()
) -> Step:
    """HEAD is on the mainline, the tree is clean, and the base is not behind.

    ``ignore`` names the files an earlier run wrote and failed to commit, which
    ``activate`` is about to commit itself. A base *ahead* of its upstream is left
    for :func:`check_base_pushed`: the activation adds to it, and the commits to
    report are the ones there after that.
    """
    if not mainline.resolved:
        raise Stop(
            "cannot tell which branch is the mainline; `planners base` names what "
            "was looked for"
        )
    if not mainline.on_mainline:
        where = mainline.current or "a detached HEAD"
        raise Stop(
            f"HEAD is on {where}, not a mainline branch; switch to "
            f"{mainline.branches[0]} and run start again"
        )
    changed = _uncommitted(root, ignore)
    if changed:
        listed = "\n".join(f"  {path}" for path in changed)
        raise Stop(
            f"the tree has {len(changed)} uncommitted change(s); commit or set "
            f"them aside, then run start again:\n{listed}"
        )
    base = mainline.current
    upstream = _upstream(root)
    if upstream is None:
        return Step(DONE, f"on {base}, clean, no upstream to compare with")
    must(root, ["git", "fetch"])
    behind = int(must(root, ["git", "rev-list", "--count", "HEAD..@{upstream}"]))
    if behind:
        raise Stop(
            f"{base} is {behind} behind {upstream}; pull it, then run start again:\n"
            "  git pull --ff-only"
        )
    return Step(DONE, f"on {base}, clean, not behind {upstream}")


def ensure_ignored(root: Path, recorded: str) -> Step:
    """The worktree path is ignored, so it never shows as untracked in the parent.

    ``.worktrees/`` is added and committed on the base when it is missing. A path
    elsewhere is the repo's own arrangement, so it is reported and left alone.
    """
    if recorded == entries.NO_WORKTREE:
        return Step(SKIPPED, "the work is in the main checkout")
    # The trailing slash: a directory pattern matches a path that does not exist
    # yet only when the path is spelled as a directory.
    ignored = proc.run(
        root,
        ["git", "check-ignore", "-q", f"{recorded.rstrip('/')}/"],
        capture_output=True,
    )
    if ignored.returncode == 0:
        return Step(DONE, f"{recorded} is ignored")
    if not recorded.startswith(f"{_WORKTREES_DIR}/"):
        return Step(
            SKIPPED,
            f"{recorded} is not ignored",
            (f"{recorded} is outside {_WORKTREES_DIR}/; add it to .gitignore",),
        )
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(f"{text}{_WORKTREES_DIR}/\n", encoding="utf-8")
    must(root, ["git", "add", ".gitignore"])
    must(root, ["git", "commit", "-m", "ignore .worktrees", "--", ".gitignore"])
    return Step(RAN, f"committed {_WORKTREES_DIR}/ to .gitignore")


def check_base_pushed(
    root: Path, base: str, plan_dir: str, prefix: str, origin: RemoteKind
) -> Step:
    """Nothing on ``base`` waits for a push, or a stop that says what to push.

    The commits are sorted the way ``activate`` reports them, so the ones that are
    not the plan's own are in front of whoever decides on the push. A single-branch
    remote is never stopped for: its upstream is the live document, so pushing is a
    publish and not a precondition.
    """
    if origin is RemoteKind.none:
        return Step(SKIPPED, "no remote to push to")
    ahead = ahead_mod.count(root, base, plan_dir)
    if origin is RemoteKind.single_branch:
        waiting = f"{ahead.total} commit(s) unpushed; " if ahead else ""
        return Step(
            SKIPPED,
            f"origin is single-branch: {waiting}a push publishes into the live "
            "document, so it is left to you",
        )
    if ahead is None:
        command = push_command(base, upstream=True)
        raise Stop(
            f"{base} has no upstream; push it, then run start again:\n  {command}"
        )
    if ahead.total == 0:
        return Step(DONE, f"{base} is level with {ahead.upstream}")
    lines = [*ahead_mod.report(ahead, prefix)]
    if ahead.other:
        lines.append("Confirm the commits above before pushing the plan's with them.")
    lines.append(f"Push {base}, then run start again:\n  {push_command(base)}")
    raise Stop("\n".join(lines))


def ensure_branch(root: Path, branch: str, base: str) -> Step:
    """``branch`` exists: as it is, from its remote copy, or from ``base``.

    A new branch starts at the base's tip, which holds the activation commit. A
    branch only on the remote is a start resumed in another clone, so the local one
    follows it instead of diverging from it.
    """
    local = f"refs/heads/{branch}"
    if proc.git_out(root, ["rev-parse", "--verify", "-q", local]) is not None:
        return Step(DONE, f"{branch} exists")
    tracking = f"refs/remotes/origin/{branch}"
    if proc.git_out(root, ["rev-parse", "--verify", "-q", tracking]) is not None:
        must(root, ["git", "branch", "--track", branch, f"origin/{branch}"])
        return Step(RAN, f"created {branch} from origin/{branch}")
    must(root, ["git", "branch", branch, base])
    return Step(RAN, f"created {branch} from {base}")


def ensure_worktree(
    root: Path, main: Path, branch: str, recorded: str
) -> tuple[Step, Path]:
    """``branch`` is checked out somewhere, and where that is.

    A worktree already on the branch is the answer even when it is not at the
    recorded path: the plan's Log is a record of the first activation, and moving a
    worktree does not make its work somewhere else.
    """
    held = next((path for path, name in proc.worktrees(root) if name == branch), None)
    if held is not None:
        if not held.is_dir():
            raise Stop(
                f"git lists {held} as the worktree of {branch}, and it is gone; "
                "run `git worktree prune`, then run start again"
            )
        return Step(DONE, f"{branch} is checked out at {_shown(held, main)}"), held
    if recorded == entries.NO_WORKTREE:
        must(root, ["git", "switch", branch])
        return Step(RAN, f"switched the checkout to {branch}"), root
    target = main / recorded
    if target.exists():
        raise Stop(
            f"{recorded} exists and is not on {branch}; move it aside, then run "
            "start again"
        )
    must(main, ["git", "worktree", "add", str(target), branch])
    return Step(RAN, f"created {recorded} on {branch}"), target


def _shown(path: Path, main: Path) -> str:
    """``path`` from the main checkout when it is under it, as a plan would write it."""
    try:
        return path.resolve().relative_to(main.resolve()).as_posix() or "."
    except ValueError:
        return str(path)


def _relative_path_sources(worktree: Path) -> list[str]:
    """The ``tool.uv.sources`` dependencies a relative path names."""
    try:
        text = (worktree / "pyproject.toml").read_text(encoding="utf-8")
        data = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    return [
        name
        for name, source in sources.items()
        if isinstance(source, dict)
        and isinstance(source.get("path"), str)
        and not Path(source["path"]).is_absolute()
    ]


def _missing_links(worktree: Path, main: Path) -> list[str]:
    """The main checkout's top-level symlinks the worktree does not have."""
    return sorted(
        path.name
        for path in main.iterdir()
        if path.is_symlink() and not os.path.lexists(worktree / path.name)
    )


def set_up_worktree(worktree: Path, main: Path) -> Step:
    """Give a fresh worktree what its tracked files do not: the repo's own hook, or
    an environment sync and the untracked ``.claude/``.

    What else the repo needs is per-repo knowledge, so it is reported rather than
    guessed: a dependency on a relative path (it resolves from the main checkout),
    a top-level symlink the worktree lacks, an environment no ``uv.lock`` describes.
    """
    if worktree.resolve() == main.resolve():
        return Step(SKIPPED, "the main checkout is set up already")
    marker = Path(
        must(
            worktree,
            ["git", "rev-parse", "--path-format=absolute", "--git-path", _SETUP_MARKER],
        ).strip()
    )
    if marker.exists():
        return Step(DONE, f"{_shown(worktree, main)} was set up by an earlier run")

    hook = main / ".planners" / "hooks" / "post-worktree"
    if hook.is_file() and os.access(hook, os.X_OK):
        must(worktree, [str(hook)])
        marker.touch()
        return Step(RAN, "ran the post-worktree hook")

    ran: list[str] = []
    notes = [
        f"{name} is a relative path dependency, which resolves from the main "
        "checkout and not from a worktree"
        for name in _relative_path_sources(worktree)
    ]
    notes += [
        f"{name} is a symlink in the main checkout and not in the worktree"
        for name in _missing_links(worktree, main)
    ]
    claude = main / ".claude"
    if claude.is_dir() and not (worktree / ".claude").exists():
        try:
            shutil.copytree(claude, worktree / ".claude", symlinks=True)
        except OSError as exc:
            raise Stop(f"cannot copy .claude/ into the worktree: {exc}") from None
        ran.append("copied .claude/")
    if (worktree / "uv.lock").exists():
        must(worktree, ["uv", "sync"])
        ran.append("ran uv sync")
    else:
        notes.append(
            "no uv.lock and no .planners/hooks/post-worktree: set the environment "
            "up as the repo's instructions describe"
        )
    marker.touch()
    if not ran:
        return Step(SKIPPED, "nothing this step knows how to set up", tuple(notes))
    return Step(RAN, ", ".join(ran), tuple(notes))


def check_branch_pushed(work_dir: Path, branch: str, origin: RemoteKind) -> Step:
    """``branch`` is on ``origin`` with tracking set, or a stop with the push to run."""
    if origin is RemoteKind.none:
        return Step(SKIPPED, "no remote to push to")
    if origin is RemoteKind.single_branch:
        return Step(SKIPPED, "origin is single-branch and takes no feature branch")
    upstream = _upstream(work_dir)
    if upstream is None:
        command = push_command(branch, upstream=True)
        raise Stop(f"push {branch}, then run start again:\n  {command}")
    unpushed = int(must(work_dir, ["git", "rev-list", "--count", "@{upstream}..HEAD"]))
    if unpushed:
        raise Stop(
            f"{branch} has {unpushed} commit(s) not on {upstream}; push them, then "
            f"run start again:\n  {push_command(branch)}"
        )
    return Step(DONE, f"{branch} is level with {upstream}")


def open_pr(work_dir: Path, branch: str) -> str | None:
    """The URL of the open PR whose head is ``branch``, or ``None``."""
    out = must(
        work_dir,
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "--limit",
            "1",
        ],
    )
    try:
        found = json.loads(out)
    except json.JSONDecodeError:
        raise Stop(f"`gh pr list` printed something that is not JSON: {out}") from None
    return found[0]["url"] if found else None


def create_draft_pr(
    work_dir: Path, *, base: str, branch: str, title: str, plan_path: str
) -> str:
    """Open a draft PR for ``branch`` and return its URL.

    The body links the plan on the base branch, where the activation commit already
    landed it, so the link is live when the PR opens and survives the branch.
    """
    repo = must(
        work_dir,
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
    ).strip()
    href = f"https://github.com/{repo}/blob/{base}/{plan_path}"
    out = must(
        work_dir,
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            f"Implements [{plan_path}]({href})",
        ],
    )
    return out.strip().splitlines()[-1]
