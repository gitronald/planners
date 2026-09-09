"""Install the ``/planners`` skillstub holder and wire the pre-commit hook.

The package is the source of truth; ``install`` materializes only thin,
generated artifacts: one version-stamped dispatcher holder, a
``planners-validate`` pre-commit hook, and one ``.gitattributes`` line giving the
generated plan index its merge semantics. ``SkillStub.render`` is a pure
transform; the filesystem writes live in the module-level functions.

Two install **modes** are supported, both first-class:

* **global** (default) — the CLI is on ``PATH`` (``uv tool install``) and
  invoked as bare ``planners``; one holder at ``~/.claude/skills/planners/``
  serves every repo, so a consuming repo needs only its own ``.planners/``.
* **local** (``--local``) — the CLI is a per-repo dev dependency invoked as
  ``uv run planners``; the holder lives at ``<repo>/.claude/skills/planners/``.

A mode is a single resolved value spanning three axes (CLI distribution, the
invocation string baked into generated artifacts, and the holder location). The
invocation prefix derives from one helper so the command string is never
duplicated; the resolved mode is stamped into the holder so ``install --check``
recovers it without re-passing the mode flag. What is always per-repo regardless
of mode: the ``.planners/`` folder, the validate hook in the repo's
``.pre-commit-config.yaml``, and the index's ``.gitattributes`` line — those are
repo content, not tooling.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from planners import proc
from planners.index import INDEX_PATH
from planners.skill import list_skills

# A mode is one resolved value, not a loose set of flags, even though it spans
# three axes (CLI distribution, invocation string, holder location). Keeping it
# atomic gives a simple UX and one thing to stamp and check; a finer per-axis
# flag can be layered on later without disturbing this type.
Mode = Literal["local", "global"]

# The outcome of trying to make the validate hook live. Distinct from
# ``wire_precommit``'s "did the config change" bool: this is about the *git hook*
# registration, which is what actually makes validation fire on commit.
#   activated         — ``pre-commit install`` registered the git hook just now.
#   already_active    — the git hook was already registered (idempotent re-run).
#   config_only       — config written but the git hook is NOT registered: either
#                       activation was skipped (``--no-activate``), the repo is
#                       not a git worktree, or ``pre-commit`` was unavailable.
#   hookspath_blocked — git's ``core.hooksPath`` is set, so ``pre-commit install``
#                       cannot register the hook until the override is unset; the
#                       config is written but the git hook is not (a hook placed
#                       at the configured path by other means still reads as
#                       ``already_active``). Split out from ``config_only`` so the
#                       CLI names the real cause, not a phantom "unavailable" message.
HookStatus = Literal["activated", "already_active", "config_only", "hookspath_blocked"]

# What ``--check`` can say about the validate hook without touching anything.
# ``activate_precommit`` reports what an *attempt* did; this reports what *is*, so
# the two are kept as separate vocabularies rather than one overloaded status.
#   active         — the git hook is registered and will fire.
#   config_missing — no planners-validate entry in .pre-commit-config.yaml.
#   no_git_repo    — nowhere to register a hook.
#   hookspath_blocked — core.hooksPath is set, so `pre-commit install` refuses.
#   not_registered — config is present and nothing is blocking; just never run.
HookReport = Literal[
    "active", "config_missing", "no_git_repo", "hookspath_blocked", "not_registered"
]

# What ``--check`` can say about the index's merge attribute.
#   ok         — the file grants exactly INDEX_ATTR_LINE.
#   drifted    — a line names the index but grants something else.
#   missing    — no .gitattributes, or none of its lines name the index.
#   unreadable — the file is there but cannot be read, so neither the check nor
#                the write path can say what it grants. Distinct from `missing`
#                because `install` can fix a missing line and cannot fix this.
GitattrStatus = Literal["ok", "drifted", "missing", "unreadable"]

HOLDER_REL = Path(".claude/skills/planners/SKILL.md")
# The convention rule installs tool-namespaced as planners.md (not plan-files.md)
# so drift detection targets it unambiguously and it never clobbers a user's own
# hand-maintained plan-files.md on the same topic.
RULE_REL = Path(".claude/rules/planners.md")
# The pre-package, hand-maintained convention file. The rule used to be a
# hand-copied plan-files.md; install now generates planners.md instead, so a
# lingering plan-files.md is superseded — surfaced (never deleted) on install.
LEGACY_RULE_REL = Path(".claude/rules/plan-files.md")
PRECOMMIT_REL = Path(".pre-commit-config.yaml")
HOOK_ID = "planners-validate"
# The post-merge companion to the ``merge=union`` attribute below. Union resolves the
# index instead of conflicting, but can leave a row duplicated when both sides rewrote
# it; regenerating from the plan files is the only correct repair, and only *after* the
# merge are both sides' plan files on disk. Hence a hook, not a merge driver.
#
# It is a genuine hook rather than advice because the manual step is the kind that gets
# skipped: a duplicated row is invisible until ``validate`` fails on some later commit,
# by which point the merge that caused it is well behind you. Caveat worth keeping in
# mind — git does not run ``post-merge`` when a merge stops on conflicts, so a merge you
# finish by hand with ``git commit`` still needs ``planners index .`` run manually.
INDEX_HOOK_ID = "planners-index"

GITATTRIBUTES_REL = Path(".gitattributes")
# The generated index is a tracked file, so it has merge semantics whether or not
# anyone chooses them: without an attribute, any *local* merge whose two sides both
# added or closed plans conflicts on it. ``union`` is deliberate, and the choice is
# narrower than it looks (see plan 004's Log):
#
# * It is a **built-in** low-level driver, so a bare attribute line is
#   self-sufficient — nothing to define, nothing to configure per clone, and it
#   works in a fresh clone that has never run ``install``. A ``merge=ours``-style
#   driver would need ``git config merge.ours.driver true`` in every clone, which
#   is invisible when absent.
# * Its failure mode is stale-and-loud, not silent: when both sides rewrite the
#   *same* row (one branch closes a plan while the other adds one) union keeps
#   both versions, so a row appears twice. Nothing is lost, the table still
#   renders, and a regeneration repairs it — whereas ``ours`` would silently drop
#   the incoming branch's rows.
#
# The accompanying hook is ``post-merge`` (:data:`INDEX_HOOK_ID`), and the stage is
# forced: measured at ``pre-merge-commit`` and ``prepare-commit-msg``, a hook that
# regenerates and stages the index cannot get it into the merge commit — git writes
# the merge tree from the index it already holds. ``post-merge`` runs after that tree
# is written, so the regeneration necessarily lands as an **uncommitted change** to
# commit alongside. That is the ceiling for any hook here, not a shortcoming of this
# one: what the hook buys is that the repair happens at all, unprompted, rather than
# waiting to surface as a ``validate`` failure some commits later.
#
# Reach: **local merges only**. GitHub's server-side merge does not apply the
# attribute, so a PR whose two sides both touched the index still reports a
# conflict there. What changes is the resolution: merging the base in locally
# resolves the index by itself instead of by hand-editing a generated file.
#
# That is measured, not assumed — two PR pairs with identical index edits,
# differing only in the attribute, both reported CONFLICTING on GitHub while the
# attribute pair merged cleanly locally (plan 004's Log has the setup). Do not
# re-run that probe. The one thing it did not rule out: GitHub may read
# .gitattributes from the repository's *default* branch, which did not carry the
# attribute when this was measured. Once a release lands it on the default
# branch, a PR that conflicts only on the index is the free re-test.
INDEX_MERGE_ATTR = "merge=union"
INDEX_ATTR_PATTERN = INDEX_PATH.as_posix()
INDEX_ATTR_LINE = f"{INDEX_ATTR_PATTERN} {INDEX_MERGE_ATTR}"

# The resolved mode is recorded in the holder's generated comment so ``check``
# can recover it from the file alone.
_MODE_STAMP_RE = re.compile(r"\(mode=(local|global)\)")

# Sentinel that every generated holder carries (in its "generated by planners
# <ver>" stamp). Used as a safety check to confirm a file is our own holder
# before deleting it — never unlink a file that lacks this marker.
_GENERATED_MARKER = "generated by planners"

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


def invocation(mode: Mode) -> str:
    """The command prefix generated artifacts use to call the CLI.

    The single source for this string: both the holder's dispatch commands and
    the pre-commit hook entry route through it, so the prefix is never written in
    two places (the storage-layout retrospective flagged "the same string in
    four places" as a drift hazard — derive, don't duplicate).
    """
    return "planners" if mode == "global" else "uv run planners"


def _stamp(version: str, mode: Mode) -> str:
    """The generated-by-planners comment every installed artifact carries.

    A single source for the stamp so the holder and the rule never diverge. It is
    an HTML comment — invisible in rendered markdown, parseable by
    :func:`_recover_mode`, and valid as the first line of a frontmatter-less rule
    file — carrying both the version (drift signal) and the resolved mode
    (recovered by ``check`` without re-passing the mode flag).
    """
    return (
        f"<!-- generated by planners {version} (mode={mode}); "
        f"do not edit — run: {invocation(mode)} install --force -->"
    )


@dataclass(frozen=True)
class GeneratedArtifact:
    """A file ``install`` materializes from the package: its location and renderer.

    The two things that differ between the dispatcher holder and the convention
    rule, captured so one path/stamp/drift/cleanup layer serves both:

    * ``rel`` — the artifact's path relative to its mode base (``$HOME`` for
      global, the repo root for local), e.g. ``.claude/skills/planners/SKILL.md``
      or ``.claude/rules/planners.md``.
    * ``render`` — ``(version, mode) -> stamped body``; the pure transform whose
      bytes are what gets written and what drift is checked against.
    """

    rel: Path
    render: Callable[[str, Mode], str]


def _validate_hook_entry(mode: Mode) -> str:
    """The ``planners-validate`` hook entry, with a mode-correct ``entry:`` line."""
    return f"""\
      - id: {HOOK_ID}
        name: validate plan frontmatter
        entry: {invocation(mode)} validate
        language: system
        files: ^\\.planners/plans/[^/]+/plan\\.md$
"""


def _index_hook_entry(mode: Mode) -> str:
    """The ``planners-index`` hook entry, run at ``post-merge`` to repair the index.

    ``always_run`` with ``pass_filenames: false`` because ``post-merge`` hands the
    hook no filenames to match on: the trigger is "a merge happened", not "these
    files changed".
    """
    return f"""\
      - id: {INDEX_HOOK_ID}
        name: regenerate plan index after merge
        entry: {invocation(mode)} index .
        language: system
        stages: [post-merge]
        always_run: true
        pass_filenames: false
"""


def _precommit_hook_block(mode: Mode) -> str:
    """The ``repo: local`` block wiring both hooks, with mode-correct entries."""
    return (
        "  - repo: local\n    hooks:\n"
        + _validate_hook_entry(mode)
        + "\n"
        + _index_hook_entry(mode)
    )


def _index_hook_block(mode: Mode) -> str:
    """A standalone ``repo: local`` block for the index hook alone.

    Appended when a config predates the index hook: those repos already carry a
    ``planners-validate`` block, and appending a second ``repo: local`` block is
    valid for pre-commit — which keeps the back-fill a text append, with no YAML
    parsing and no risk to the entry already committed there.
    """
    return "  - repo: local\n    hooks:\n" + _index_hook_entry(mode)


@dataclass(frozen=True)
class SkillStub:
    """Renders the generated ``/planners`` dispatcher holder for a given mode."""

    version: str
    mode: Mode = "local"
    name: str = "planners"
    description: str = HOLDER_DESCRIPTION
    subcommands: tuple[str, ...] = field(default_factory=lambda: tuple(list_skills()))

    def render(self) -> str:
        inv = invocation(self.mode)
        subs = "\n".join(f"- `{sub}`" for sub in self.subcommands)
        stamp = _stamp(self.version, self.mode)
        return f"""\
---
name: {self.name}
description: {self.description}
---

{stamp}

# planners

This repo's entire plan-file lifecycle is owned by the `planners` package. This
file is a generated dispatcher stub, not the source of truth — the instructions
live in the package and are printed on demand.

**Before dispatching, confirm this stub is current:**

```bash
{inv} install --check
```

If it prints `drifted` or `missing`, the guidance below may be stale: run
`{inv} install --force`, then start a fresh context before continuing.

**To run a plan-lifecycle action**, pick a subcommand, load its instructions,
and follow them exactly:

```bash
{inv} skill <sub>
```

Subcommands ({len(self.subcommands)}):

{subs}

These map to `/planners add`, `/planners implement`, `/planners update`,
`/planners close`, `/planners pipeline`, `/planners index`, and
`/planners backfill`. Plan state lives only in frontmatter — there is no separate
checklist file — and the index is regenerated from it with `{inv} index .`.
"""


def render_holder(version: str, mode: Mode = "local") -> str:
    return SkillStub(version=version, mode=mode).render()


def render_rule(version: str, mode: Mode = "local") -> str:
    """Render the installed convention rule: the generated stamp + the rule body.

    Mirrors :func:`render_holder` for the rule artifact. The body is the bundled
    ``planners`` rule prompt with ``{cli}`` substituted for ``mode`` (so its
    commands run as-is); the stamp is prepended so ``planners.md`` is drift-checked
    and mode-recoverable exactly like the holder. The import is local to avoid a
    module-load cycle (``install`` imports ``rule`` which imports ``skill``).
    """
    from planners.rule import get_rule

    return f"{_stamp(version, mode)}\n\n{get_rule('planners', mode)}"


# The two artifacts `install` materializes, both routed through one file layer:
# the dispatcher holder skillstub and the convention rule.
HOLDER = GeneratedArtifact(HOLDER_REL, render_holder)
RULE = GeneratedArtifact(RULE_REL, render_rule)


def artifact_path(root: Path, mode: Mode, art: GeneratedArtifact) -> Path:
    """Where ``art`` lives for ``mode``: under ``$HOME`` (global) or the repo (local).

    The relative path is identical in both modes; only the base differs, so a
    global install and a local install never collide on the same file. This is
    the old ``holder_path`` generalized over the artifact's ``rel``.
    """
    base = Path.home() if mode == "global" else root
    return base / art.rel


def write_artifact(
    root: Path, version: str, mode: Mode, art: GeneratedArtifact
) -> Path:
    """Write ``art``'s generated body for ``mode``, creating parent dirs as needed."""
    path = artifact_path(root, mode, art)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(art.render(version, mode), encoding="utf-8")
    return path


def resolve_installed(root: Path, art: GeneratedArtifact) -> tuple[Path, Mode] | None:
    """Find an installed ``art``, preferring global over local.

    Returns ``(path, mode)`` where ``mode`` is the location-implied mode, or
    ``None`` if neither location has the artifact. Global wins when both exist so
    a repo that has switched to global is read as global even if a stale local
    copy lingers; any stamp inside is still the authoritative mode.
    """
    for mode in ("global", "local"):
        path = artifact_path(root, cast("Mode", mode), art)
        if path.exists():
            return path, cast("Mode", mode)
    return None


def check_artifact(
    root: Path, version: str, mode: Mode, art: GeneratedArtifact
) -> Literal["ok", "drifted", "missing"]:
    """Drift for ``art`` of a *specific* mode, at that mode's location.

    Used by ``install`` to guard an artifact it is about to write (don't clobber a
    hand-edited file without ``--force``) and by ``--check`` to report each
    artifact against the holder-resolved mode.
    """
    path = artifact_path(root, mode, art)
    if not path.exists():
        return "missing"
    # Anything other than a readable plain file at the path is not our artifact:
    # a directory, a symlink, or an undecodable file is "drifted" (something
    # foreign is squatting there), never a crash. Mirrors is_generated_artifact's
    # hardening so --check and the pre-write guard can't traceback on a stray dir.
    if path.is_symlink() or not path.is_file():
        return "drifted"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "drifted"
    return "ok" if text == art.render(version, mode) else "drifted"


def is_generated_artifact(path: Path) -> bool:
    """True only for a real, plain file *we* generated.

    The gate for deletion, and the ``--force`` ours-vs-foreign signal: it must be
    a regular file (not a directory), not a symlink (so an unlink can never
    traverse a link out to an unrelated target), and its contents must carry the
    generated-by-planners marker (so a foreign file that merely happens to sit at
    the artifact path is never destroyed).
    """
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return _GENERATED_MARKER in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def remove_stale(root: Path, mode: Mode, art: GeneratedArtifact) -> Path | None:
    """Clean up ``art``'s per-repo copy when switching a repo to global mode.

    A global install in a repo that already had a local artifact would otherwise
    leave two copies (the per-repo one shadowing the global one), so the local
    copy is removed. The reverse is deliberately *not* done: a local install
    never deletes the global artifact, which serves every other repo. Returns the
    removed path, or ``None`` when there was nothing to clean up.

    The unlink is fenced by several guards so this can never delete the wrong
    thing: it only runs in global mode, never when the local and global paths
    coincide (repo root is ``$HOME`` — that file is the global artifact we just
    wrote), and only on a plain file we generated (see
    :func:`is_generated_artifact` — not a symlink, directory, or unrelated file).
    """
    if mode != "global":
        return None
    local = artifact_path(root, "local", art)
    # When the repo root *is* ``$HOME`` the local and global paths coincide, so
    # the "stale local" copy is the global artifact we just wrote — never remove
    # it (that would leave the global install with no artifact at all).
    if local == artifact_path(root, "global", art):
        return None
    if not is_generated_artifact(local):
        return None
    local.unlink()
    return local


def holder_path(root: Path, mode: Mode) -> Path:
    """Where the holder lives for ``mode`` — :func:`artifact_path` for the holder."""
    return artifact_path(root, mode, HOLDER)


def _recover_mode(text: str) -> Mode | None:
    """Recover the mode stamped into a holder, or ``None`` if unstamped (old)."""
    match = _MODE_STAMP_RE.search(text)
    return cast("Mode", match.group(1)) if match else None


def resolve_installed_holder(root: Path) -> tuple[Path, Mode] | None:
    """Find the installed holder, preferring global over local.

    :func:`resolve_installed` for the holder; the stamp inside is still the
    authoritative mode (see :func:`resolve_mode`). Global wins when both exist so
    a repo that has switched to global is read as global even if a stale local
    holder lingers.
    """
    return resolve_installed(root, HOLDER)


def resolve_mode(root: Path) -> Mode:
    """The installed holder's authoritative mode, or ``global`` when none exists.

    The stamp inside the holder is authoritative (it survives a holder lingering
    at the other location), falling back to the location-implied mode for an
    unstamped (old) holder — the same derivation :func:`check` uses. Callers that
    only need the mode (e.g. rendering a skill body's ``{cli}`` prefix) use this
    so they agree with ``check`` instead of trusting location alone.
    """
    found = resolve_installed_holder(root)
    if found is None:
        return "global"
    path, location_mode = found
    return _recover_mode(path.read_text(encoding="utf-8")) or location_mode


def both_holders_present(root: Path) -> bool:
    """True when a repo has *both* a global and a distinct per-repo holder.

    This is the shadow case: under Claude Code's precedence the global holder
    wins, so the per-repo stub is inert. :func:`check` reports the global one;
    the CLI uses this to warn that a local stub is being shadowed. The equality
    guard avoids a false positive when the repo root is ``$HOME`` (the two paths
    coincide, so there is really only one holder).
    """
    glob = holder_path(root, "global")
    local = holder_path(root, "local")
    return glob != local and glob.exists() and local.exists()


def check(root: Path, version: str) -> Literal["ok", "drifted", "missing"]:
    """Report drift for the *installed* holder, whatever mode it is in.

    Resolves which holder exists (global first), recovers its stamped mode, and
    compares against a re-render in that mode — so ``install --check`` is a
    single no-arg command that "just knows" the mode.
    """
    found = resolve_installed_holder(root)
    if found is None:
        return "missing"
    path, location_mode = found
    text = path.read_text(encoding="utf-8")
    mode = _recover_mode(text) or location_mode
    return "ok" if text == render_holder(version, mode) else "drifted"


@dataclass(frozen=True)
class RuleCheck:
    """The convention rule's drift across *both* auto-loaded locations.

    Claude Code auto-loads rules from ``~/.claude/rules/`` **and**
    ``<repo>/.claude/rules/`` at once — unlike the holder, where the global one
    shadows the local one (see :func:`check`). So a rule that drifts at *either*
    path is live in context, and :func:`check_rule` folds both into one result:

    * ``status`` — the worst of the present locations (``missing`` only when
      neither location has a rule), suitable for the ``rule:`` line and the gate.
    * ``locations`` — the per-location verdict (``ok``/``drifted``) for each
      location that actually has a file, so the CLI can name *which* path is
      drifted or stale rather than reporting a bare status.
    """

    status: Literal["ok", "drifted", "missing"]
    locations: dict[Mode, Literal["ok", "drifted"]]


def check_rule(root: Path, version: str) -> RuleCheck:
    """Drift for the convention rule across both auto-loaded locations.

    The holder's :func:`check` resolves a single authoritative holder (global
    shadows local), but the rule auto-loads from both ``~/.claude/rules/`` and the
    repo simultaneously, so this inspects the rule at *each* location and reports
    the worst. A location is ``drifted`` two ways:

    * **Content drift** — the file at a location differs from that location's
      canonical render (a stale old-version stamp, or a hand-edit). Caught at
      either path.
    * **Stale leftover** — a per-repo rule that *still matches* its render but
      should not be there at all because the repo has switched to global (a global
      holder pins it there). It is an extra rule auto-loaded alongside the global
      one, e.g. left behind by ``install --no-rule`` (which skips the
      rule, so the stale-local cleanup never runs) or hand-restored. Flagged only
      when a holder genuinely resolves the repo to global — with **no** holder the
      global mode is just :func:`resolve_mode`'s fallback, so a local rule is
      judged on content alone and a holder-less local-only rule reads ``ok``
      (*found*), not misreported ``missing``.

    The asymmetry is deliberate: a *global* rule present during a local install is
    shared infrastructure (it serves every other repo), never this repo's stale
    leftover. ``missing`` means neither location has a rule. When the repo root
    *is* ``$HOME`` the two paths coincide, so only one location is inspected.
    """
    glob_path = artifact_path(root, "global", RULE)
    local_path = artifact_path(root, "local", RULE)
    modes: tuple[Mode, ...] = (
        ("global",) if glob_path == local_path else ("global", "local")
    )
    # A per-repo rule is a stale leftover (drift even when its content matches)
    # only once a holder genuinely pins the repo to global. resolve_mode alone
    # says "global" even with no holder (its fallback), so guard on a real holder
    # — that is what keeps a holder-less local-only rule reading "ok" not stale.
    repo_is_global = (
        resolve_installed_holder(root) is not None and resolve_mode(root) == "global"
    )
    locations: dict[Mode, Literal["ok", "drifted"]] = {}
    for mode in modes:
        # check_artifact returns "missing" for an absent file, "ok"/"drifted"
        # (incl. a squatting dir/symlink) for a present one — a location only
        # contributes to the fold when it actually has a file.
        status = check_artifact(root, version, mode, RULE)
        if status == "missing":
            continue
        # A content-ok per-repo rule is still stale once the repo is global.
        if mode == "local" and repo_is_global and status == "ok":
            status = "drifted"
        locations[mode] = status
    if not locations:
        return RuleCheck("missing", {})
    worst: Literal["ok", "drifted"] = (
        "drifted" if "drifted" in locations.values() else "ok"
    )
    return RuleCheck(worst, locations)


def check_holder(
    root: Path, version: str, mode: Mode
) -> Literal["ok", "drifted", "missing"]:
    """Drift for the holder of a *specific* mode — :func:`check_artifact` for it.

    Used by ``install`` to guard the holder it is about to write (don't clobber a
    hand-edited holder without ``--force``), whereas :func:`check` auto-detects
    the installed mode for a no-arg ``--check``.
    """
    return check_artifact(root, version, mode, HOLDER)


def write_holder(root: Path, version: str, mode: Mode = "local") -> Path:
    """Write the generated holder for ``mode`` — :func:`write_artifact` for it."""
    return write_artifact(root, version, mode, HOLDER)


def is_generated_holder(path: Path) -> bool:
    """True only for a real, plain-file holder *we* generated.

    Holder-named alias of :func:`is_generated_artifact`; the CLI uses it to tell
    the user, before a ``--force`` overwrite, whether the file at the holder path
    is ours or hand-edited/foreign.
    """
    return is_generated_artifact(path)


def remove_stale_holder(root: Path, mode: Mode) -> Path | None:
    """Clean up the per-repo holder when switching a repo to global mode.

    :func:`remove_stale` for the holder: a global install removes a per-repo
    holder that would otherwise shadow the global one (leaving two ``/planners``
    skills); a local install never deletes the global holder, which serves every
    other repo. Returns the removed path, or ``None`` when nothing was cleaned up.
    """
    return remove_stale(root, mode, HOLDER)


def superseded_legacy_rule(root: Path, mode: Mode) -> Path | None:
    """The hand-maintained ``plan-files.md`` the generated ``planners.md`` supersedes.

    The convention rule used to be a hand-copied ``.claude/rules/plan-files.md``;
    ``install`` now generates ``planners.md`` instead. A lingering ``plan-files.md``
    on the same topic is a contradiction risk, but it carries no generated marker
    so the safe-remove guard would never touch it — surface it (at ``mode``'s base,
    where the new rule was written) so the user removes it by hand. Returns the
    path if it is present, else ``None``. Never deletes.
    """
    base = Path.home() if mode == "global" else root
    legacy = base / LEGACY_RULE_REL
    return legacy if legacy.is_file() else None


def bare_cli_available() -> bool:
    """True when a bare ``planners`` resolves on ``PATH`` (required by global mode)."""
    return shutil.which("planners") is not None


def _hook_entry_line(mode: Mode) -> str:
    """The hook's ``entry:`` line for ``mode`` (matches the block's, exactly)."""
    return f"        entry: {invocation(mode)} validate\n"


def _append_block(text: str, block: str) -> str:
    """Append a ``repo: local`` block to ``text``, ensuring a separating newline."""
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def wire_precommit(root: Path, mode: Mode = "local", *, resync: bool = True) -> bool:
    """Ensure the ``planners`` pre-commit hooks are present and mode-correct.

    Two hooks: ``planners-validate`` at ``pre-commit``, and ``planners-index`` at
    ``post-merge`` (see :data:`INDEX_HOOK_ID`).

    Returns ``True`` if the config was created or modified, ``False`` if both
    hooks were already there with the right entry. Appending a ``repo: local``
    block is valid for pre-commit, which keeps the first install idempotent
    without parsing YAML.

    A config carrying only ``planners-validate`` predates the index hook and gets
    it appended, so an existing consumer picks the automation up on its next
    install rather than needing to hand-write the block.

    When the hook already exists but in the *other* mode's invocation, its
    ``entry:`` line is rewritten only if ``resync`` is true — a genuine mode
    switch (e.g. local -> global). On a *same-mode* re-install the caller passes
    ``resync=False`` so a deliberate committed entry is left alone: the hook is
    repo content, and refreshing (say) the shared global holder must not clobber
    a repo whose entry is intentionally the other form — e.g. the planners dev
    repo, which keeps ``uv run planners validate`` (planners is a local dep) while
    using the global holder.
    """
    block = _precommit_hook_block(mode)
    config = root / PRECOMMIT_REL
    if not config.exists():
        config.write_text("repos:\n" + block, encoding="utf-8")
        return True
    text = config.read_text(encoding="utf-8")
    if HOOK_ID not in text:
        config.write_text(_append_block(text, block), encoding="utf-8")
        return True

    changed = False
    desired = _hook_entry_line(mode)
    other = _hook_entry_line("local" if mode == "global" else "global")
    if desired not in text and other in text and resync:
        text = text.replace(other, desired)
        changed = True
    # Otherwise the entry is in the other mode's form on a same-mode re-install
    # (resync=False), or was hand-customized to neither invocation. Both are
    # deliberate — leave the committed entry alone.
    #
    # The index hook is keyed on its *id*, not its entry line, for the same
    # reason: a repo that customized the invocation has the hook, and only a
    # config predating it needs the block appended.
    if INDEX_HOOK_ID not in text:
        text = _append_block(text, _index_hook_block(mode))
        changed = True
    if changed:
        config.write_text(text, encoding="utf-8")
    return changed


def _index_attr_line(text: str) -> tuple[int, str] | None:
    """Find the ``.gitattributes`` line governing the plan index.

    Returns ``(line number, whitespace-normalized line)`` for the **last** line
    whose *pattern* field is the index path, or ``None`` when no line names it.
    Last, not first, because that is the one git obeys: attributes are resolved
    by the last matching line, so a file carrying both ``merge=union`` and a
    later ``merge=ours`` is a repo running ``ours``. Reading the first match
    would report such a repo ``ok`` while its merges silently dropped rows —
    exactly the failure the attribute exists to prevent.

    Normalizing the whitespace is what keeps a padded but equivalent line from
    reading as drift. Blank and ``#`` comment lines are skipped for the format's
    sake, not for correctness — a comment's first field always starts with ``#``,
    so it could never equal the pattern anyway.

    Patterns are compared as written, so a quoted or differently-spelled pattern
    for the same file reads as absent — the safe direction: ``install`` then
    appends its own line, and git applies the last matching line, so the appended
    one wins.
    """
    found: tuple[int, str] | None = None
    for number, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if fields[0] == INDEX_ATTR_PATTERN:
            found = (number, " ".join(fields))
    return found


def _read_gitattributes(config: Path) -> str | None:
    """``config``'s text, or ``None`` when it exists but cannot be read.

    Every caller tests ``is_file()`` first, so ``None`` here means *unreadable*
    — bad permissions, or bytes that are not UTF-8 — never *absent*. Keeping
    those two apart is the point: an absent file is safe to create, an
    unreadable one must not be clobbered, and a reader that answered ``None``
    for both would let :func:`wire_gitattributes` overwrite a file whose
    contents it could not see.
    """
    try:
        return config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def installed_index_attr(root: Path) -> str | None:
    """The index's ``.gitattributes`` line as it stands in ``root``, if any.

    Lets the CLI name the line it found when reporting drift, rather than saying
    only that something differs. ``None`` covers every way there is no line to
    name — absent file, unreadable file, or a readable file that says nothing
    about the index — because a caller reporting drift has nothing to print in
    any of them; :func:`check_gitattributes` is what tells those cases apart.
    """
    config = root / GITATTRIBUTES_REL
    if not config.is_file():
        return None
    text = _read_gitattributes(config)
    if text is None:
        return None
    found = _index_attr_line(text)
    return None if found is None else found[1]


def check_gitattributes(root: Path) -> GitattrStatus:
    """Drift for the index's merge attribute: absent, unreadable, different, or exact.

    ``missing`` when no line names the index, ``drifted`` when one does but
    grants different attributes (e.g. a repo still carrying the hand-rolled
    ``merge=ours`` stopgap), ``ok`` when it matches :data:`INDEX_ATTR_LINE` up to
    whitespace. Unlike the holder and the rule this is committed repo content, so
    it travels with a clone — the check exists to catch a repo that has not
    re-run ``install`` since the attribute shipped, not per-clone state.

    ``unreadable`` is reported rather than folded into ``missing`` so it is not
    described as a state ``install`` can fix by writing the line: it cannot, and
    saying ``missing`` would promise a repair that :func:`wire_gitattributes`
    correctly refuses to attempt.
    """
    config = root / GITATTRIBUTES_REL
    if not config.is_file():
        return "missing"
    text = _read_gitattributes(config)
    if text is None:
        return "unreadable"
    found = _index_attr_line(text)
    if found is None:
        return "missing"
    return "ok" if found[1] == INDEX_ATTR_LINE else "drifted"


def wire_gitattributes(root: Path, *, force: bool = False) -> bool:
    """Ensure ``.gitattributes`` gives the plan index its merge attribute.

    Returns ``True`` if the file was created or modified, ``False`` if it already
    said the right thing or was left deliberately alone. Other attribute lines
    are preserved — the line is appended, never the file rewritten, mirroring how
    :func:`wire_precommit` appends its hook block rather than parsing YAML.

    A line that names the index but grants *different* attributes is left alone
    unless ``force`` is passed: like the pre-commit entry, ``.gitattributes`` is
    repo content a user may have set deliberately, so ``install`` reports it as
    drift instead of clobbering it. ``install --force`` rewrites that one line in
    place, which is also the migration path for a repo carrying the earlier
    ``merge=ours`` arrangement.

    A file that exists but cannot be read is left alone too, ``--force`` or not:
    every write below either appends to, or edits one line of, text this
    function has read, so with no text in hand there is no edit to make that
    would not discard the rest of the file. ``--check`` calls the same repo
    ``unreadable``.
    """
    config = root / GITATTRIBUTES_REL
    # ``is_file`` rather than ``exists``, matching :func:`check_gitattributes`:
    # a path that is not a regular file has no attribute line to read, and the
    # two must agree about that or ``--check`` and the write path describe the
    # same repo differently.
    if not config.is_file():
        config.write_text(INDEX_ATTR_LINE + "\n", encoding="utf-8")
        return True
    text = _read_gitattributes(config)
    if text is None:
        return False
    found = _index_attr_line(text)
    if found is None:
        if not text.endswith("\n"):
            text += "\n"
        config.write_text(text + INDEX_ATTR_LINE + "\n", encoding="utf-8")
        return True
    number, normalized = found
    if normalized == INDEX_ATTR_LINE:
        return False
    if not force:
        return False
    lines = text.splitlines(keepends=True)
    ends_with_newline = lines[number].endswith("\n")
    lines[number] = INDEX_ATTR_LINE + ("\n" if ends_with_newline else "")
    config.write_text("".join(lines), encoding="utf-8")
    return True


def is_git_repo(root: Path) -> bool:
    """True when ``root`` is a git working tree.

    Covers both a normal repo (``.git`` is a directory) and a linked worktree
    (``.git`` is a file holding a ``gitdir:`` pointer) — ``exists()`` is true for
    either. This is the gate for activation: ``pre-commit install`` needs a git
    repo, so a non-repo returns ``config_only`` without a pointless shell-out.
    """
    return (root / ".git").exists()


def _git_hooks_dir(root: Path) -> Path | None:
    """Resolve ``root``'s git hooks directory, or ``None`` if it is not a git repo.

    Handles a normal repo (``.git/hooks``) and a linked worktree, where ``.git``
    is a file of the form ``gitdir: <path>`` and the hooks live under that pointed
    git dir rather than under ``<root>/.git``. Best-effort: an unreadable or
    malformed pointer reads as "not a git repo". This is the pure-Python fallback
    for :func:`_effective_hooks_dir`; it does **not** honour ``core.hooksPath`` —
    that override is resolved by asking git in the effective resolver, so this
    path is used only when git cannot be consulted (git missing, or a synthetic
    ``.git`` scaffold in tests).
    """
    git = root / ".git"
    if git.is_dir():
        return git / "hooks"
    if not git.is_file():
        return None
    try:
        pointer = git.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    prefix = "gitdir:"
    if not pointer.startswith(prefix):
        return None
    gitdir = Path(pointer[len(prefix) :].strip())
    if not gitdir.is_absolute():
        gitdir = root / gitdir
    return gitdir / "hooks"


def _effective_hooks_dir(root: Path) -> Path | None:
    """The *effective* git hooks directory for ``root``, honoring ``core.hooksPath``.

    Asks git itself — ``git rev-parse --git-path hooks`` (run with ``cwd=root``) —
    which is authoritative: it honours ``core.hooksPath`` and resolves
    linked-worktree gitdirs, so a hook live at a non-default path is still found.
    git prints the path relative to the command's cwd (here ``root``) or as an
    absolute path; a relative answer is joined onto ``root`` and an absolute one
    used as-is — which is why running with ``cwd=root`` makes the join correct.
    Falls back to the pure-Python
    :func:`_git_hooks_dir` parse when git is unavailable or the command fails —
    e.g. a non-repo or a synthetic ``.git`` scaffold (``rev-parse`` exits non-zero
    there) — so detection still works without a usable git binary.

    Runs through :func:`planners.proc.run`, so an ambient ``GIT_DIR`` cannot point
    the answer at another repo's hooks. The mis-answer here is advisory — a
    misleading activation message, not a misplaced commit — but it would be
    reported about ``root`` all the same.
    """
    try:
        result = proc.run(
            root, ["git", "rev-parse", "--git-path", "hooks"], capture_output=True
        )
    except FileNotFoundError:
        return _git_hooks_dir(root)
    out = result.stdout.strip()
    if result.returncode != 0 or not out:
        return _git_hooks_dir(root)
    hooks = Path(out)
    return hooks if hooks.is_absolute() else root / hooks


def _precommit_hook_registered(root: Path) -> bool:
    """True when the repo's ``pre-commit`` git hook is registered by pre-commit.

    Resolves the effective hooks directory — honouring ``core.hooksPath`` and
    linked worktrees (see :func:`_effective_hooks_dir`) — then checks the hook
    script carries pre-commit's marker, so an unrelated, hand-written
    ``pre-commit`` hook is not mistaken for our active validation hook.
    Best-effort: anything unreadable reads as not-registered.
    """
    hooks_dir = _effective_hooks_dir(root)
    if hooks_dir is None:
        return False
    hook = hooks_dir / "pre-commit"
    if not hook.is_file():
        return False
    try:
        return "pre-commit" in hook.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _run_precommit_install(root: Path, hook_type: str | None = None) -> bool:
    """Run ``uv run pre-commit install`` in ``root``; ``True`` only on exit 0.

    ``hook_type`` adds ``--hook-type <type>``. pre-commit registers only the
    ``pre-commit`` hook by default, so the ``post-merge`` index hook needs its own
    call — a config entry with ``stages: [post-merge]`` and no registered
    ``post-merge`` script is exactly the silent no-op this module exists to avoid.

    Best-effort by contract: a missing ``uv``/``pre-commit`` (``FileNotFoundError``)
    or any non-zero exit returns ``False`` rather than raising, so a fresh
    consumer that has not added ``pre-commit`` never sees ``install`` crash. Output
    is captured so the shell-out stays quiet on the happy path.

    ``pre-commit install`` writes into git's hooks directory, so it inherits the
    location hazard one level down: run through :func:`planners.proc.run` it
    installs the hook in ``root``, not wherever an ambient ``GIT_DIR`` points.
    """
    cmd = ["uv", "run", "pre-commit", "install"]
    if hook_type is not None:
        cmd += ["--hook-type", hook_type]
    try:
        result = proc.run(root, cmd, capture_output=True)
    except FileNotFoundError:
        return False
    return result.returncode == 0


def core_hookspath_set(root: Path) -> bool:
    """True when ``core.hooksPath`` is configured for ``root``'s git repo.

    ``pre-commit install`` refuses ("Cowardly refusing to install hooks with
    ``core.hooksPath`` set") whenever this is configured — even when it points at
    the default ``.git/hooks`` — so this predicate lets activation report the real
    cause instead of attempting a guaranteed refusal. Best-effort: a missing
    ``git`` (or any non-zero exit, which is how ``config --get`` signals "unset")
    reads as not-set.
    """
    try:
        result = proc.run(
            root, ["git", "config", "--get", "core.hooksPath"], capture_output=True
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def activate_precommit(root: Path, *, attempt: bool = True) -> HookStatus:
    """Best-effort register the validate git hook; never raises.

    Returns a :data:`HookStatus` so the caller can report *exactly* what is true
    rather than overpromising. The ``already_active`` check runs first — one
    best-effort ``git rev-parse`` to find the effective hooks dir — so a hook
    already live, even at a configured ``core.hooksPath``, is reported before any
    other guard. A non-git directory or ``attempt=False`` (``--no-activate``) then
    returns ``config_only`` without attempting ``pre-commit install`` (which needs
    a git repo anyway). When ``core.hooksPath`` is set, ``pre-commit install`` is
    guaranteed to refuse, so that case short-cuts to ``hookspath_blocked`` rather
    than shelling out to a doomed install.
    """
    if _precommit_hook_registered(root):
        return "already_active"
    if not attempt:
        return "config_only"
    if not is_git_repo(root):
        return "config_only"
    if core_hookspath_set(root):
        return "hookspath_blocked"
    if not _run_precommit_install(root):
        return "config_only"
    # The validate hook is what "activated" reports, so the post-merge
    # registration rides along best-effort: failing to wire the index repair
    # must not downgrade a validation hook that is genuinely live.
    _run_precommit_install(root, hook_type="post-merge")
    return "activated"


def report_hook(root: Path) -> HookReport:
    """Read-only: is the validate git hook actually live in *this* clone?

    :func:`activate_precommit` answers the same question by trying to fix it;
    this only looks, so ``--check`` can report the truth without side effects.

    The distinction it exists to make visible: the hook's *config* is committed
    and travels with a clone, but its *registration* is per-clone git state that a
    fresh clone silently lacks — and a hook that never fires looks exactly like a
    hook that fires and finds nothing wrong. Reporting it turns that silence into
    a line. ``config_missing`` is called out separately because the remedy differs
    (write the config, rather than register a hook for config that isn't there).

    The config is checked **before** the registration, because
    :func:`_precommit_hook_registered` answers "is pre-commit itself wired into
    this clone", not "will ``planners-validate`` run". A repo that uses
    pre-commit for other hooks satisfies it with no planners entry at all, so
    testing registration first reported ``active`` for a hook that cannot fire —
    the very silence this function was added to break. Reading the config is
    guarded like every other check-path read in this module: an unreadable or
    non-UTF-8 config is a config that does not name the hook, not a traceback out
    of ``--check``.
    """
    config = root / PRECOMMIT_REL
    try:
        entry_present = config.is_file() and HOOK_ID in config.read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError):
        entry_present = False
    if not entry_present:
        return "config_missing"
    if _precommit_hook_registered(root):
        return "active"
    if not is_git_repo(root):
        return "no_git_repo"
    if core_hookspath_set(root):
        return "hookspath_blocked"
    return "not_registered"


def ensure_precommit_dependency(root: Path) -> bool:
    """Add ``pre-commit`` as a dev dependency via ``uv add --dev``; ``True`` on success.

    Opt-in only (``install --full``): it edits the consumer's ``pyproject.toml``,
    which the default install deliberately never does. Best-effort like the other
    shell-outs — a missing ``uv`` or non-zero exit returns ``False`` rather than
    raising, so the rest of ``install`` still completes.
    """
    try:
        result = proc.run(
            root, ["uv", "add", "--dev", "pre-commit"], capture_output=True
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0
