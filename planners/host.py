"""The ``pkgskills`` host declaration: what planners ships and how it is invoked.

``pkgskills`` owns the prompt-packaging machinery — printing bundled bodies on
demand (``skill``, ``rule``), materializing the version-stamped ``/planners``
dispatcher stub and convention rule (``install``), drift checking
(``install --check``), and the automation-level ``permissions`` profiles. This
module is only the *declaration* the library acts on, plus the per-clone repo
wiring it cannot know about: the two pre-commit hooks and the index's merge
attribute.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import typer
from pkgskills import (
    ExtraCheck,
    Hook,
    Host,
    InstallReport,
    Level,
    Line,
    Mode,
    Rule,
    Skill,
    precommit,
)

from planners.index import INDEX_PATH

# The seven plan-lifecycle subcommands, in lifecycle order. `pipeline` follows
# `close` because it chains implement -> work -> close as one driven run.
SKILL_NAMES = (
    "add",
    "implement",
    "update",
    "close",
    "pipeline",
    "index",
    "backfill",
)

# The single dispatcher's description must absorb the union of all seven
# subcommands' triggers so /planners still auto-fires across the whole plan flow.
HOLDER_DESCRIPTION = (
    "Manage this repo's plan-file lifecycle end to end. Use whenever the user "
    "wants to plan, spec out, propose, draft, or outline new work (add); start, "
    "implement, or begin work on a plan (implement); activate, log, update, "
    "finish, close, complete, ship, or abandon/retire a plan (update, close); "
    "drive a plan from implementation through close in one run (pipeline); "
    "regenerate or refresh the plan index / README table (index); or "
    "backfill missing plan frontmatter from git history and PRs (backfill). "
    'Triggers on "let\'s plan", "spec this out", "write up a plan", '
    '"start/close this plan", "take this plan to done", "update the plan status", '
    'or "refresh the index".'
)

HOOKS = (
    Hook(
        id="planners-validate",
        name="validate plan frontmatter",
        args=("validate",),
        files=r"^\.planners/plans/[^/]+/plan\.md$",
    ),
    # The post-merge companion to the `merge=union` line below. Union resolves the
    # index instead of conflicting, but can leave a row duplicated when both sides
    # rewrote it; regenerating from the plan files is the only correct repair, and
    # only *after* the merge are both sides' plan files on disk. Git does not run
    # `post-merge` when a merge stops on conflicts, and the regenerated index lands
    # as an uncommitted change (git writes the merge tree before the hook runs).
    Hook(
        id="planners-index",
        name="regenerate plan index after merge",
        args=("index", "."),
        stage="post-merge",
        always_run=True,
        pass_filenames=False,
    ),
)

# The generated index is tracked, so it has merge semantics whether or not anyone
# chooses them. `union` is a built-in driver — one committed line, nothing to
# configure per clone — and its failure mode is a duplicated row that a
# regeneration repairs, never a silently dropped one (see plan 004's Log). It
# applies to local merges only; GitHub's server-side merge ignores it.
INDEX_ATTR = Line(".gitattributes", INDEX_PATH.as_posix(), "merge=union")


def _after_install(report: InstallReport) -> None:
    """Wire both hooks into the repo's pre-commit config and register their stages."""
    done = precommit.wire(report, HOOKS)
    if done.unreadable:
        typer.echo(
            f"note: {done.config.name} cannot be read, so the hooks were not "
            "wired; fix the file, then re-run install.",
            err=True,
        )
    for hook_id in (*done.added, *done.resynced):
        typer.echo(f"wrote {hook_id} to {done.config.name}")
    for stage, activation in done.activation.items():
        typer.echo(f"{stage} hook: {activation.replace('_', ' ')}")


def _extra_checks(host: Host, root: Path, mode: Mode | None) -> Sequence[ExtraCheck]:
    """Report (never gate on) whether each hook is registered in this clone."""
    return precommit.checks(host, root, mode, HOOKS)


HOST = Host(
    dist="planners",
    cli="planners",
    prompts="planners.prompts",
    artifacts=(
        Skill(
            name="planners",
            sources=tuple(f"skills/{name}/SKILL.md" for name in SKILL_NAMES),
            description=HOLDER_DESCRIPTION,
        ),
        # Installs tool-namespaced as planners.md, superseding the hand-maintained
        # plan-files.md of earlier releases (removed only if it carries a stamp).
        Rule(
            name="planners", source="rules/planners.md", previous_names=("plan-files",)
        ),
    ),
    lines=(INDEX_ATTR,),
    render_cli=True,
    after_install=_after_install,
    extra_checks=_extra_checks,
    # Each level's Bash allow-rules *add* over the one below: `assist` grants the
    # local, reversible spine plus the self-authored PR writes, `confirm` adds the
    # one code-publishing command, and `full` the single irreversible one. The
    # bare-`planners` grant a global install needs is derived by pkgskills.
    permissions={
        Level.assist: (
            "Bash(git worktree:*)",
            "Bash(git add:*)",
            "Bash(git commit:*)",
            "Bash(uv run:*)",
            "Bash(uv sync:*)",
            "Bash(gh pr comment:*)",
            "Bash(gh pr ready:*)",
        ),
        Level.confirm: ("Bash(git push:*)",),
        Level.full: ("Bash(gh pr merge:*)",),
    },
)
