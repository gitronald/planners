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

import re
from collections.abc import Sequence
from pathlib import Path

import typer
from pkgskills import (
    Doc,
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

# The eight plan-lifecycle subcommands, in lifecycle order. `pipeline` follows
# `close` because it chains implement -> work -> close as one driven run, and
# `review` follows it as the pass over plans that have gone stale.
SKILL_NAMES = (
    "add",
    "implement",
    "update",
    "close",
    "pipeline",
    "review",
    "index",
    "backfill",
)

# The single dispatcher's description must absorb the union of all eight
# subcommands' triggers so /planners still auto-fires across the whole plan flow.
# It loads into every session's skill listing, so it names each subcommand once
# and stays near 400 characters.
HOLDER_DESCRIPTION = (
    "Manage this repo's plan-file lifecycle. Use to plan, spec out, or draft new "
    "work (add); start or implement a plan (implement); activate, log, close, or "
    "retire one (update, close); take one from implementation through close "
    "(pipeline); find stale or done plans (review); refresh the plan index "
    '(index); or backfill frontmatter (backfill). Triggers on "let\'s plan", '
    '"write up a plan", "close this plan", or "review the plans".'
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
    # `post-merge` when a merge stops on conflicts. Git writes the merge commit
    # before the hook runs, so the repair comes after it: `--after-merge` amends it
    # into that commit while the commit is still local, and leaves it uncommitted
    # otherwise (see `planners.aftermerge`).
    Hook(
        id="planners-index",
        name="regenerate plan index after merge",
        args=("index", ".", "--after-merge"),
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


def _entry_before_after_merge(host: Host) -> re.Pattern[str]:
    """The `planners-index` entry line a release before `--after-merge` wrote.

    Matched exactly, in either install mode, so an entry someone set by hand to
    anything else is not taken for one of ours.
    """
    invocations = "|".join(
        re.escape(host.invocation(mode)) for mode in ("global", "local")
    )
    return re.compile(
        rf"^([ \t]*entry: (?:{invocations}) index \.)[ \t]*(\r?)$", re.MULTILINE
    )


def _config_text(config: Path) -> str | None:
    """The config's text with its line endings kept, or ``None`` when unreadable."""
    try:
        with config.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _upgrade_index_entry(config: Path, host: Host) -> bool:
    """Give an earlier release's `planners-index` entry the `--after-merge` option.

    `wire` keys a hook on its id and leaves an entry that is present alone, so a
    config written before the option existed would go on running the hook without
    it, and the repair would stay an uncommitted change in that repo.
    """
    text = _config_text(config)
    if text is None:
        return False
    upgraded, count = _entry_before_after_merge(host).subn(r"\1 --after-merge\2", text)
    if not count:
        return False
    with config.open("w", encoding="utf-8", newline="") as handle:
        handle.write(upgraded)
    return True


def _after_install(report: InstallReport) -> None:
    """Wire both hooks into the repo's pre-commit config and register their stages."""
    done = precommit.wire(report, HOOKS)
    if not done.unreadable and _upgrade_index_entry(done.config, report.host):
        typer.echo(
            f"updated planners-index in {done.config.name}: it runs with --after-merge"
        )
    if done.unreadable:
        typer.echo(
            f"note: {done.config.name} cannot be read, so the hooks were not "
            "wired; fix the file, then re-run install.",
            err=True,
        )
    if done.unsupported:
        typer.echo(
            f"note: install cannot safely add hooks to {done.config.name}, so it was "
            "left alone; add the entries `install --check` reports missing by hand.",
            err=True,
        )
    for hook_id in (*done.added, *done.resynced):
        typer.echo(f"wrote {hook_id} to {done.config.name}")
    for stage, activation in done.activation.items():
        typer.echo(f"{stage} hook: {activation.replace('_', ' ')}")


def _extra_checks(host: Host, root: Path, mode: Mode | None) -> Sequence[ExtraCheck]:
    """Report (never gate on) whether each hook is registered in this clone."""
    rows = list(precommit.checks(host, root, mode, HOOKS))
    text = _config_text(root / precommit.CONFIG)
    if text is not None and _entry_before_after_merge(host).search(text):
        rows.append(
            ExtraCheck(
                "hook planners-index",
                "outdated",
                gates=False,
                note=(
                    "planners-index runs without --after-merge, so the index repair "
                    "after a merge is left uncommitted; run "
                    f"`{host.install_command(mode or host.default_mode)}`"
                ),
            )
        )
    return rows


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
        Rule(name="planners", source="rules/planners.md"),
        # The full rule is scoped to plan files by its `paths` frontmatter, so this
        # short one carries what has to hold before a session has opened a plan.
        Rule(name="planners-core", source="rules/planners-core.md"),
    ),
    # Loaded only when a run fans out, so the implement skill stays short for the
    # sessions that do not.
    docs=(Doc(name="orchestrated-run", source="docs/orchestrated-run.md"),),
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
