"""Automation-level permission profiles for planners' lifecycle commands.

planners' skills invoke ~15 shell commands across implement/close; whether each
runs unprompted depends on the ambient Claude Code permission config, which the
skills never declare. This module maps a chosen *automation level* to the Bash
allow-rules that pre-authorize the commands that level unlocks, so a user can
trade portability for fewer prompts.

The rule sets are computed here (pure); the CLI (``planners permissions``) reads
and writes ``settings.json``. Grants are applied *additively* and never downgrade
an existing ``deny``/``ask`` rule — a deliberate stricter policy always wins.

Levels form an escalating, superset ladder named by supervision posture:

* ``none``    — grant nothing; every command falls to the session mode and the
                classifier (fully portable, most prompts).
* ``assist``  — everything **local and reversible** (the commit spine, worktree,
                the ``uv run`` check gate) plus the low-blast-radius, self-authored
                PR writes (``gh pr comment``, ``gh pr ready``). Pushing code and
                merging still prompt.
* ``confirm`` — ``assist`` plus ``git push``: the pipeline runs unattended through
                push and pauses only to confirm the irreversible merge.
* ``full``    — ``confirm`` plus ``gh pr merge``: nothing is confirmed.

Rules are **mode-aware**: a *global* install invokes the CLI as bare ``planners``
and needs a ``Bash(planners:*)`` grant, while a *local* install invokes it as
``uv run planners``, already covered by the ``Bash(uv run:*)`` grant in ``assist``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from planners.install import Mode


class Level(StrEnum):
    """An automation level: how far the lifecycle runs without a prompt."""

    none = "none"
    assist = "assist"
    confirm = "confirm"
    full = "full"


# Lowest to highest. Each level is a superset of the ones before it.
LEVELS: tuple[Level, ...] = (Level.none, Level.assist, Level.confirm, Level.full)

# The Bash allow-rules each level *adds* over the one below it; the effective set
# for a level is the union of its own increment and every lower increment (see
# `rules_for`). Ordered so `assist` grants the local, reversible spine plus the
# self-authored PR writes, `confirm` adds the one code-publishing command, and
# `full` adds the single irreversible one.
_INCREMENT: dict[Level, tuple[str, ...]] = {
    Level.none: (),
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
}

# Mode-only supplement: a global install invokes the CLI as bare `planners`, so it
# needs its own grant; a local install runs `uv run planners`, already covered by
# `Bash(uv run:*)` in `assist`. Keyed by the level at which the CLI first runs
# unattended (`assist` — implement/close call `planners index` from there up).
_GLOBAL_ONLY: dict[Level, tuple[str, ...]] = {
    Level.assist: ("Bash(planners:*)",),
}

# The personal, git-ignored per-repo settings file (local mode) vs. the user-wide
# one (global mode). Local is the default so a broad grant is scoped to one
# checkout and is never committed for collaborators.
SETTINGS_GLOBAL_REL = Path(".claude/settings.json")
SETTINGS_LOCAL_REL = Path(".claude/settings.local.json")


def levels() -> list[str]:
    """The automation-level names, lowest to highest."""
    return [level.value for level in LEVELS]


def parse_level(name: str) -> Level:
    """Resolve a level name — or its ``0``-``3`` numeric alias — to a :class:`Level`.

    ``"0"``-``"3"`` map to ``none``/``assist``/``confirm``/``full`` by ladder
    position; every other value raises ``ValueError`` so the CLI can report the
    valid choices.
    """
    if name.isdigit():
        index = int(name)
        if 0 <= index < len(LEVELS):
            return LEVELS[index]
        raise ValueError(name)
    return Level(name)


def rules_for(level: Level, mode: Mode = "global") -> list[str]:
    """The allow-rules pre-authorizing everything up to and including ``level``.

    Cumulative: the union of every increment from ``none`` through ``level`` plus
    the mode-only supplement (a bare-``planners`` grant only a global install
    needs). Deduplicated, in ascending-level order, for reproducible output.
    """
    out: list[str] = []
    seen: set[str] = set()
    for lvl in LEVELS:
        chunk = list(_INCREMENT[lvl])
        if mode == "global":
            chunk.extend(_GLOBAL_ONLY.get(lvl, ()))
        for rule in chunk:
            if rule not in seen:
                seen.add(rule)
                out.append(rule)
        if lvl is level:
            break
    return out


def settings_path(root: Path, mode: Mode) -> Path:
    """Where a profile is written for ``mode``.

    Global targets ``~/.claude/settings.json`` (applies to every repo); local
    targets the repo's ``.claude/settings.local.json`` — the personal, git-ignored
    file — so a broad grant stays scoped to one checkout.
    """
    if mode == "global":
        return Path.home() / SETTINGS_GLOBAL_REL
    return root / SETTINGS_LOCAL_REL


@dataclass(frozen=True)
class MergeResult:
    """The outcome of merging rules into a permissions block.

    ``permissions`` is a fresh block (the input is never mutated); ``added`` were
    appended to ``allow``, ``already`` were present on ``allow`` (no-ops), and
    ``skipped`` are ``(rule, reason)`` pairs left untouched because an existing
    ``deny``/``ask`` rule already governs them.
    """

    permissions: dict[str, Any]
    added: list[str]
    already: list[str]
    skipped: list[tuple[str, str]]


def _string_list(value: Any) -> list[str]:
    """The string members of ``value`` when it is a list, else an empty list."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def merge_allow(permissions: dict[str, Any], rules: list[str]) -> MergeResult:
    """Additively merge ``rules`` into ``permissions['allow']``, deferring to policy.

    Never removes or weakens an existing rule: a rule whose exact string is already
    on ``deny`` or ``ask`` is left there and reported as skipped (a deliberate
    stricter policy wins), a rule already on ``allow`` is a no-op, and everything
    else is appended to ``allow``. Matching is by exact rule string — subsuming a
    broader pattern is the Claude Code matcher's job, not this merge's. Returns a
    new permissions block plus a report; the input dict is not mutated.
    """
    allow = _string_list(permissions.get("allow"))
    deny = set(_string_list(permissions.get("deny")))
    ask = set(_string_list(permissions.get("ask")))
    present = set(allow)

    new_allow = list(allow)
    added: list[str] = []
    already: list[str] = []
    skipped: list[tuple[str, str]] = []
    for rule in rules:
        if rule in deny:
            skipped.append((rule, "already on deny"))
        elif rule in ask:
            skipped.append((rule, "already on ask"))
        elif rule in present:
            already.append(rule)
        else:
            new_allow.append(rule)
            present.add(rule)
            added.append(rule)

    new_permissions = dict(permissions)
    new_permissions["allow"] = new_allow
    return MergeResult(
        permissions=new_permissions, added=added, already=already, skipped=skipped
    )


def render_block(rules: list[str]) -> str:
    """A paste-ready ``settings.json`` fragment granting ``rules`` on ``allow``."""
    return json.dumps({"permissions": {"allow": rules}}, indent=2) + "\n"
