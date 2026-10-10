"""planners CLI — the documented entry point for the plan-file lifecycle.

Commands: ``add``, ``finalize``, ``activate``, ``set-pr``, ``implemented``,
``finish``, ``retire``, ``subplans``, ``review``, ``base``, ``remote``,
``index``, ``schema``, and ``validate``, plus
``skill``, ``rule``, ``install``, and ``permissions``, which
:func:`pkgskills.register` mounts from :data:`planners.host.HOST`. Filesystem and
subprocess (git) work is confined to this module and the ``add`` helpers; the
schema/index transforms stay pure. Every shell-out goes through
:mod:`planners.proc`, which pins it to an explicit repo root.
"""

import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

import typer
from pkgskills import register

from planners import ahead as ahead_mod
from planners import base as base_mod
from planners import entries, proc
from planners import finish as finish_mod
from planners import remote as remote_mod
from planners import review as review_mod
from planners import subplans as subplans_mod
from planners.body import append_to_section, section_span, set_frontmatter_key
from planners.host import HOST
from planners.index import INDEX_PATH, render_index, render_plans_table
from planners.metadata import (
    CLOSED_STATUSES,
    DIRNAME_RE,
    PLAN_FILENAME,
    PlanError,
    PlanMetadata,
    Status,
    is_plan_dirname,
    next_number,
    next_sub,
)
from planners.subplans import SUBPLANS_DIRNAME, SubplanError, SubplanMetadata
from planners.utils import (
    is_safe_slug,
    parse_frontmatter,
    parse_instant,
    split_frontmatter,
)

app = typer.Typer(
    help="Own a repo's plan-file lifecycle: schema, CLI, and skillstub.",
    no_args_is_help=True,
)

PLANS_DIR = Path(".planners/plans")
# Deferred-numbering staging area for collision-safe batch creation: `add --defer`
# writes unnumbered plans here (no shared state), and `finalize` is the single
# serialized writer that numbers, materializes, and commits them.
STAGING_DIR = Path(".planners/staging")
INDEX_TITLE = "Plans"
# Every column set `index` can write, and therefore every rendering a tracked
# index may legitimately be in. Spelled once so the `--cols` validation and the
# staleness comparison can never drift apart — a set the check did not know
# about would make `validate` fail a correctly generated index.
INDEX_COLS = ("curated", "all")


def _version() -> str:
    try:
        return metadata.version("planners")
    except metadata.PackageNotFoundError:
        return "0+unknown"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"planners {_version()}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed planners version and exit.",
    ),
) -> None:
    """Own a repo's plan-file lifecycle: schema, CLI, and skillstub."""


# skill, rule, install, and permissions: the shared pkgskills command grammar.
register(app, HOST)


def _err(message: str) -> None:
    typer.echo(message, err=True)


def _warn(message: str) -> None:
    """A non-fatal note to stderr — unlike :func:`_err`, no exit follows it."""
    typer.echo(message, err=True)


def _shown(path: Path, root: Path) -> Path:
    """``path`` relative to ``root`` when possible; a global artifact is under $HOME."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _plan_files(plans_dir: Path) -> list[Path]:
    """The ``plan.md`` of each plan dir (``NNN-slug/plan.md``), sorted by dir name.

    Each plan is a directory; iterating the plan-shaped subdirectories that
    contain a ``plan.md`` keeps stray files (the generated ``README.md`` index,
    notes) and non-plan directories out of indexing and validation.
    """
    if not plans_dir.is_dir():
        return []
    plans: list[Path] = []
    for child in sorted(plans_dir.iterdir()):
        if child.is_dir() and is_plan_dirname(child.name):
            plan = child / PLAN_FILENAME
            if plan.is_file():
                plans.append(plan)
    return plans


def _resolve_dir_plans(directory: Path) -> list[Path]:
    """The plan files a *directory* argument contributes, by resolution priority.

    1. a plan directory named directly (it holds a ``plan.md``) -> that one file;
    2. a repo root (it holds a ``.planners/plans`` tree) -> every plan under it;
    3. otherwise a container of plan dirs -> its plan-shaped subdirs, swept.

    The repo-root case (2) is what makes ``validate .`` from a checkout discover
    the plans instead of sweeping the root for top-level ``NNN-slug`` dirs (of
    which there are none) and silently matching zero files — the vacuous-pass bug.
    """
    own = directory / PLAN_FILENAME
    if own.is_file():
        return [own]
    nested = directory / PLANS_DIR
    if nested.is_dir():
        return _plan_files(nested)
    return _plan_files(directory)


class _Ref(NamedTuple):
    """What a plan reference resolved to.

    ``plan`` is the ``plan.md`` the reference names, or the umbrella's when it
    names a nested subplan, which is then ``nested``. ``label`` is the reference
    in its canonical ``NNN[x]`` form.
    """

    plan: Path
    nested: Path | None
    label: str


def _parse_ref(ref: str) -> tuple[int, str]:
    """Split a plan reference into its number and optional letter, or exit."""
    match = re.fullmatch(r"(\d+)([a-z]?)", ref.strip())
    if match is None:
        _err(f"not a plan reference: {ref!r}; use a number like 005 (or 005a).")
        raise typer.Exit(1)
    return int(match.group(1)), match.group(2)


def _find_plan(plans_dir: Path, want_id: int, want_sub: str) -> Path | None:
    """The ``plan.md`` of the plan directory numbered ``want_id`` + ``want_sub``."""
    for plan in _plan_files(plans_dir):
        parts = DIRNAME_RE.match(plan.parent.name)
        if parts is None:  # unreachable: _plan_files filters on the same pattern
            continue
        if int(parts.group(1)) == want_id and parts.group(2) == want_sub:
            return plan
    return None


def _subplan_files(plan_dir: Path) -> list[Path]:
    """The ``<letter>-<step>.md`` files under ``plan_dir``'s ``subplans/``, sorted.

    Anything else in that directory is left out, so a plan can keep notes or
    free-form files beside its subplans.
    """
    directory = plan_dir / SUBPLANS_DIRNAME
    if not directory.is_dir():
        return []
    return [
        child
        for child in sorted(directory.iterdir())
        if child.is_file() and subplans_mod.is_subplan_filename(child.name)
    ]


def _subplan_by_letter(plan_dir: Path, letter: str) -> Path | None:
    """The nested subplan ``letter`` under ``plan_dir``, or ``None``."""
    for path in _subplan_files(plan_dir):
        if path.name.startswith(f"{letter}-"):
            return path
    return None


def _resolve_ref(plans_dir: Path, ref: str) -> _Ref:
    """Resolve a reference (``5``, ``005``, ``005a``) to a plan or a nested subplan.

    The reference names a number and an optional letter; the slug is not part of
    it, so a retitled or re-slugged plan stays addressable by the number that
    identifies it. Matching is on the parsed ``(number, letter)`` pair rather than
    a string prefix, so ``5`` and ``005`` are the same plan while ``5`` never
    matches ``050-...``.

    A lettered sibling plan wins over a nested subplan with the same letter, since
    it is the one with an identity of its own.

    Exits with a CLI error when the reference is malformed or matches nothing.
    """
    want_id, want_sub = _parse_ref(ref)
    label = f"{want_id:03d}{want_sub}"
    plan = _find_plan(plans_dir, want_id, want_sub)
    if plan is not None:
        return _Ref(plan, None, label)
    if want_sub:
        umbrella = _find_plan(plans_dir, want_id, "")
        if umbrella is not None:
            nested = _subplan_by_letter(umbrella.parent, want_sub)
            if nested is not None:
                return _Ref(umbrella, nested, label)
    _err(f"no plan {label} found under {plans_dir}.")
    raise typer.Exit(1)


def _resolve_plan(plans_dir: Path, ref: str) -> Path:
    """Resolve a reference to a plan's ``plan.md``, refusing a nested subplan.

    For the commands that act on a plan as a whole. A nested subplan has no
    directory, no index row, and no activation of its own, so they have nothing
    to act on.
    """
    found = _resolve_ref(plans_dir, ref)
    if found.nested is not None:
        number, letter = found.label[:-1], found.label[-1]
        _err(
            f"{found.label} is a nested subplan of plan {number}, not a plan of "
            f"its own; set its status with `planners subplans {number} --set "
            f"{letter}=<status>`."
        )
        raise typer.Exit(1)
    return found.plan


def _load_subplans(
    plan: Path, planned: dict[Path, str] | None = None
) -> tuple[list[SubplanMetadata], list[str]]:
    """Parse an umbrella's nested subplans: the readable ones, and the errors.

    An unreadable file is reported and left out rather than raised, so one bad
    subplan does not hide the state of the rest.

    ``planned`` holds texts that are about to be written, keyed by path. Each is
    read in place of what is on disk, a file that does not exist yet included, so
    a command can see the state it is about to create before it creates any of it.
    """
    planned = planned or {}
    paths = {*_subplan_files(plan.parent), *planned}
    metas: list[SubplanMetadata] = []
    errors: list[str] = []
    for path in sorted(paths, key=lambda found: found.name):
        try:
            text = planned.get(path)
            if text is None:
                text = path.read_text(encoding="utf-8")
            metas.append(SubplanMetadata.from_text(text, path.name))
        except (SubplanError, OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return metas, errors


def _sync_subplans(
    root: Path, plan: Path, planned: dict[Path, str], *, warn: bool = True
) -> None:
    """Write ``planned`` subplan texts and the umbrella's table, as one step.

    Everything that can refuse is settled before anything is written: each
    planned text must read as a subplan, and the table must be one this command
    may write. A refusal therefore leaves every file as it was, where writing
    first would leave a subplan changed, the table stale, and no commit.
    """
    for path, text in planned.items():
        try:
            SubplanMetadata.from_text(text, path.name)
        except SubplanError as exc:
            _err(f"{_shown(path, root)}: {exc}")
            raise typer.Exit(1) from None

    metas, errors = _load_subplans(plan, planned)
    if warn:
        for error in errors:
            _warn(f"warning: {error}")

    current = plan.read_text(encoding="utf-8")
    try:
        updated = subplans_mod.write_table(current, metas)
    except ValueError as exc:
        _err(f"{_shown(plan, root)}: {exc}")
        raise typer.Exit(1) from None

    for path, text in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if updated != current:
        plan.write_text(updated, encoding="utf-8")
        typer.echo(f"updated the subplan table in {_shown(plan, root)}")


def _read_plan(root: Path, path: Path) -> PlanMetadata:
    """Read plan metadata, reporting a parse failure in the CLI's usual form."""
    try:
        return PlanMetadata.from_file(path)
    except PlanError as exc:
        _err(f"cannot read {_shown(path, root)}: {exc}")
        raise typer.Exit(1) from None


def _taken_numbers(plans_dir: Path) -> list[int]:
    """Every plan number in use, read from the directory names.

    Read from names rather than frontmatter, so a plan whose frontmatter does not
    parse (skipped with a warning by :func:`_collect_metas`) still holds its
    number and the next ``add`` does not reuse it.
    """
    if not plans_dir.is_dir():
        return []
    return [
        int(match.group(1))
        for child in plans_dir.iterdir()
        if child.is_dir() and (match := DIRNAME_RE.match(child.name))
    ]


def _collect_metas(plans_dir: Path, *, strict: bool) -> list[PlanMetadata]:
    """Parse every ``NNN-slug/plan.md``. In non-strict mode, skip unparseable files."""
    metas: list[PlanMetadata] = []
    for path in _plan_files(plans_dir):
        try:
            metas.append(PlanMetadata.from_file(path))
        except PlanError as exc:
            if strict:
                raise
            _err(f"warning: skipping {path}: {exc}")
    return metas


def _git(root: Path, args: list[str]) -> None:
    """Run a git command in ``root``, with arguments as a list (never shell=True).

    ``root`` is explicit rather than inherited from the process directory, and
    :func:`planners.proc.run` strips the git location variables — an ambient
    ``GIT_DIR`` would otherwise redirect the commit into a *different* repository
    while the plan files stayed uncommitted here. The guard in
    :func:`_guard_base_branch` already describes ``root`` and nothing else, so
    pinning the commit the same way keeps the two talking about one repo.

    Converts the usual failure modes — git missing, an unusable ``root``, or a
    non-zero exit (e.g. not a git worktree, or no commit identity configured) —
    into a clear CLI error instead of a traceback.

    Pinning to ``root`` is what makes that last case possible: ``cwd=root`` fails
    in its own right if the directory has gone away or become unreadable, and a
    missing directory raises the *same* ``FileNotFoundError`` as a missing git
    binary. ``root.is_dir()`` separates the two, so the message names the real
    cause instead of sending the user to install a git they already have.
    """
    try:
        result = proc.run(root, ["git", *args])
    except FileNotFoundError:
        if root.is_dir():
            _err("git not found on PATH; install git or re-run with --no-commit.")
        else:
            _err(f"cannot run git: {root} is no longer a directory.")
        raise typer.Exit(1) from None
    except OSError as exc:
        _err(f"cannot run git in {root}: {exc}")
        raise typer.Exit(1) from None
    if result.returncode != 0:
        joined = " ".join(args)
        _err(
            f"`git {joined}` failed (exit {result.returncode}); "
            "the plan file was written — commit it manually or use --no-commit."
        )
        raise typer.Exit(1)


def _commit(root: Path, message: str, paths: list[str]) -> None:
    """Stage ``paths`` and commit them, and only them.

    The pathspec keeps anything else the user had already staged out of the
    plan's commit; it stays staged, as it was.
    """
    _git(root, ["add", *paths])
    _git(root, ["commit", "-m", message, "--", *paths])


def _guard_base_branch(root: Path, action: str, *, allow_branch: bool) -> None:
    """Refuse to commit ``action`` when HEAD is off the repo's mainline.

    The plan-file convention is that ``add``/``activate`` commits land on the
    mainline *before* a feature branch exists, so the plan is recorded there even
    if the branch never merges. That ordering used to live only in the implement
    skill's prose, which a session can ignore — and did, leaving both commits
    reachable only from the branch. This is the enforcement.

    Deliberately quiet in every ambiguous case: :func:`base.guard_message`
    returns ``None`` for an unresolvable repo, a repo with no commits, or a HEAD
    already on the mainline, so the guard only speaks when the failure is
    demonstrable. ``--allow-branch`` is the escape hatch for a repo whose mainline
    genuinely is not detectable by name.
    """
    if allow_branch:
        return
    message = base_mod.guard_message(base_mod.detect(root), action)
    if message is None:
        return
    _err(f"error: {message}")
    raise typer.Exit(1)


def _index_document(metas: list[PlanMetadata], cols: str = "curated") -> str:
    """Assemble the index document from already-parsed plan metadata.

    The one place that assembly happens. Split from :func:`_rendered_index` so a
    caller that needs *both* column sets (:func:`_index_is_stale`) pays for
    parsing the plans once rather than once per rendering.
    """
    return render_index(INDEX_TITLE, render_plans_table(metas, cols=cols))


def _rendered_index(repo_root: Path, cols: str = "curated") -> str:
    """The index document ``repo_root``'s plan frontmatter currently renders to.

    The one place that answer is computed. Three callers need it and would
    otherwise each re-assemble the same three calls: :func:`_refresh_index`
    writes it, :func:`_finalize_self_check` asserts the batch landed it, and
    ``validate`` compares the tracked file against it.
    """
    return _index_document(_collect_metas(repo_root / PLANS_DIR, strict=False), cols)


def _index_is_stale(repo_root: Path) -> bool:
    """True when the tracked index disagrees with a fresh render (or is absent).

    What "stale" catches, in order of how often it happens: a plan edited without
    reindexing, and a local merge — the index carries ``merge=union`` (see
    ``install.INDEX_MERGE_ATTR``), which resolves rather than conflicting and
    never loses a row, but can leave a row duplicated when both sides rewrote the
    same one. Union's repair is a regeneration, and this is what notices one is
    due.

    Compared against **every** column set ``index`` can write, not just the
    default: ``--cols all`` is a first-class option, so a wide index is a
    legitimate tracked state. Checking only the curated rendering would report
    such a repo stale on every commit, with no edit able to fix it — a gate that
    fires on correct input is worse than no gate.
    """
    index = repo_root / INDEX_PATH
    if not index.is_file():
        return True
    try:
        current = index.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    metas = _collect_metas(repo_root / PLANS_DIR, strict=False)
    return all(current != _index_document(metas, cols) for cols in INDEX_COLS)


def _repo_root_of(plan: Path) -> Path | None:
    """The repo root owning ``plan``, from its ``.planners/plans/<dir>/plan.md`` shape.

    Lets ``validate`` check the index even when it is handed individual plan
    files — which is exactly how the pre-commit hook calls it (``files:`` matches
    plan paths, and pre-commit passes the matched filenames, never a root).
    Returns ``None`` for anything not in that layout, so a legacy
    ``docs/plans/`` repo is left alone rather than reported stale.
    """
    parents = plan.parents
    if len(parents) < 4:
        return None
    if parents[1].name == PLANS_DIR.name and parents[2].name == PLANS_DIR.parent.name:
        return parents[3]
    return None


def _refresh_index(repo_root: Path, cols: str) -> Path:
    """Regenerate ``.planners/README.md`` (title + plans table) from frontmatter."""
    index = repo_root / INDEX_PATH
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(_rendered_index(repo_root, cols), encoding="utf-8")
    return index


def _now() -> str:
    """Current local time as an ISO-8601 string (keeps the clock out of import)."""
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _render_staged_plan(slug: str, title: str, branch: str) -> str:
    """A deferred plan's text: conformant frontmatter with the ``id`` left blank.

    Identical to a normal plan except ``id:`` is empty — the number is assigned by
    :func:`finalize`, the single serialized writer, so concurrent ``add --defer``
    creators share no state and cannot race on numbering. The body (the title
    heading, and any ``## Plan`` the creator appends before finalize) is preserved
    verbatim when the plan is materialized.
    """
    branch_line = f"branch: {branch}" if branch else "branch:"
    return (
        "---\n"
        "id:\n"
        f"slug: {slug}\n"
        "status: draft\n"
        f"{branch_line}\n"
        f"created: {_now()}\n"
        "concluded:\n"
        "pr:\n"
        "---\n"
        "\n"
        f"# {title}\n"
    )


def _created_key(value: str | None) -> tuple[int, float]:
    """Sort key for a staged plan's ``created``: present-and-parseable first.

    Returns ``(0, instant)`` for a parseable timestamp (older instant sorts first,
    so it takes the lower number) and ``(1, 0.0)`` for a missing or malformed one,
    which sorts last. Comparing the parsed instant — not the raw string — keeps
    ordering correct across plans written under different UTC offsets.
    """
    instant = parse_instant(value)
    return (0, instant) if instant is not None else (1, 0.0)


def _collect_staged(staging: Path) -> list[tuple[Path, dict[str, str | None], str]]:
    """Read staged (deferred) plans, ordered by ``created`` then directory name.

    Each staged plan directory contributes ``(dir, frontmatter, body)``. Ordering
    by ``created`` (tie-broken by directory name for determinism) reproduces the
    numbering a sequence of foreground ``add`` calls would have produced,
    independent of the filesystem's iteration order.
    """
    if not staging.is_dir():
        return []
    staged: list[tuple[Path, dict[str, str | None], str]] = []
    for child in sorted(staging.iterdir()):
        if not child.is_dir():
            continue
        plan = child / PLAN_FILENAME
        if not plan.is_file():
            continue
        fm, body = split_frontmatter(plan.read_text(encoding="utf-8"))
        data = parse_frontmatter(fm) if fm is not None else {}
        staged.append((child, data, body))
    staged.sort(key=lambda item: (_created_key(item[1].get("created")), item[0].name))
    return staged


def _git_status_porcelain(root: Path, *paths: Path) -> str | None:
    """``git status --porcelain`` for ``root`` (empty = clean), or ``None`` on error.

    Goes through :func:`planners.proc.run` so the location variables are stripped:
    the self-check must report on the repo ``finalize`` just committed to, not on
    whatever an ambient ``GIT_DIR`` points at.

    ``paths`` narrows the report to those pathspecs, which is what lets a caller ask
    whether *one* file is committed without caring about the rest of the tree.
    """
    args = ["git", "status", "--porcelain"]
    if paths:
        args += ["--", *(str(p) for p in paths)]
    try:
        result = proc.run(root, args, capture_output=True)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_unmodified(root: Path, path: Path) -> bool:
    """True when ``path`` has no staged or unstaged changes against ``HEAD``.

    Distinguishes "already done and committed" from "written by an earlier run that
    then failed to commit" — the two states that frontmatter alone cannot tell apart.
    An unreadable git state (no repo, no git binary) reports unmodified: the caller's
    next step surfaces that failure with a better message than this check could.
    """
    try:
        spec = path.relative_to(root)
    except ValueError:
        spec = path
    return not _git_status_porcelain(root, spec)


def _finalize_self_check(
    root: Path,
    finalized: list[tuple[int, str, Path]],
    start_id: int,
    *,
    committed: bool,
) -> None:
    """Verify a finalize run landed cleanly; report and exit non-zero if not.

    The sole serialized writer self-checks the invariants the batch flow promises,
    so a batch never silently leaves a half-finished or mis-numbered state: every
    new plan validates, the numbers are sequential from ``start_id`` with no gaps
    or reuse, the staging area is drained, the index matches a fresh render, and —
    in commit mode — the git tree is clean.
    """
    problems: list[str] = []

    expected = list(range(start_id, start_id + len(finalized)))
    actual = [plan_id for plan_id, _, _ in finalized]
    if actual != expected:
        problems.append(f"numbers not sequential: expected {expected}, got {actual}")

    for _, _, plan_dir in finalized:
        plan = plan_dir / PLAN_FILENAME
        if not plan.is_file():
            problems.append(f"missing materialized plan: {plan_dir}")
            continue
        try:
            errs = PlanMetadata.from_file(plan).validate()
        except PlanError as exc:
            problems.append(f"{plan}: {exc}")
            continue
        problems.extend(f"{plan}: {err}" for err in errs)

    staging = root / STAGING_DIR
    leftover: list[str] = (
        [p.name for p in staging.iterdir()] if staging.is_dir() else []
    )
    if leftover:
        problems.append(f"staging not drained: {sorted(leftover)}")

    if _index_is_stale(root):
        problems.append("index is stale (does not match a fresh render)")

    if committed:
        dirty = _git_status_porcelain(root)
        if dirty is None:
            problems.append("could not check git status")
        elif dirty:
            # Scope "clean" to the plan files finalize manages: a stray untracked
            # file elsewhere in the repo is not this command's concern, only an
            # uncommitted staging leftover or plan/index change would be.
            plan_dirty = [line for line in dirty.splitlines() if ".planners" in line]
            if plan_dirty:
                joined = "\n".join(plan_dirty)
                problems.append(f"uncommitted plan changes after commit:\n{joined}")

    if problems:
        _err("self-check FAILED:")
        for problem in problems:
            _err(f"  - {problem}")
        raise typer.Exit(1)
    typer.echo("self-check OK")


def _add_nested(
    root: Path,
    slug: str,
    parent: int,
    *,
    title: str,
    branch: str,
    letter: str | None,
    allow_branch: bool,
    no_commit: bool,
) -> None:
    """Scaffold ``subplans/<letter>-<slug>.md`` under umbrella ``parent``.

    The subplan gets its minimal frontmatter and a back-link, and the umbrella's
    table gets its row, in the same step. The index is not touched: a nested
    subplan has no row there.

    The commit follows the umbrella. One that is not yet ``active`` lives on the
    mainline, so the guard applies as it does to ``add``. An ``active`` one has a
    branch where its work is, and a subplan added during that work belongs there.
    """
    plans_dir = root / PLANS_DIR
    umbrella = _find_plan(plans_dir, parent, "")
    if umbrella is None:
        _err(
            f"no umbrella plan {parent:03d} found under {PLANS_DIR}; "
            "create it first with `planners add`."
        )
        raise typer.Exit(1)
    meta = _read_plan(root, umbrella)
    if meta.status in CLOSED_STATUSES:
        _err(f"plan {meta.prefix} is {meta.status}; it is closed.")
        raise typer.Exit(1)

    taken = {path.name[0]: path.name for path in _subplan_files(umbrella.parent)}
    if letter is None:
        try:
            letter = subplans_mod.next_letter(list(taken))
        except ValueError as exc:
            _err(str(exc))
            raise typer.Exit(1) from None
    elif not re.fullmatch(r"[a-z]", letter):
        _err(f"--letter must be a single letter a-z, got {letter!r}.")
        raise typer.Exit(1)
    elif letter in taken:
        # Letters are fixed once assigned, so a taken one is never handed out
        # again, and nothing is renamed to make room.
        _err(f"letter {letter!r} is already taken by {taken[letter]}.")
        raise typer.Exit(1)

    if not no_commit and meta.status != Status.active:
        _guard_base_branch(root, "plan [add]", allow_branch=allow_branch)

    path = umbrella.parent / SUBPLANS_DIRNAME / f"{letter}-{slug}.md"
    text = subplans_mod.render_subplan(title, meta.title, branch)
    _sync_subplans(root, umbrella, {path: text})
    typer.echo(f"wrote {path.relative_to(root)}")

    if no_commit:
        return

    _commit(
        root,
        f"plan [add]: {meta.prefix}{letter} - {slug}",
        [str(path.relative_to(root)), str(umbrella.relative_to(root))],
    )


@app.command()
def add(
    slug: str = typer.Argument(..., help="kebab-case plan slug."),
    title: str | None = typer.Option(None, "--title", help="Fill the # Title heading."),
    branch: str | None = typer.Option(
        None, "--branch", help="Fill the branch: field at creation."
    ),
    parent: int | None = typer.Option(
        None,
        "--parent",
        help="Umbrella plan number. With --nested, scaffold a nested subplan file "
        "under it; without, a lettered sibling plan (e.g. 010a).",
    ),
    nested: bool = typer.Option(
        False,
        "--nested",
        help="With --parent: write subplans/<letter>-<slug>.md inside the umbrella's "
        "directory and add its row to the umbrella's table.",
    ),
    letter: str | None = typer.Option(
        None,
        "--letter",
        help="With --nested: the letter to take (default: the next free one from b; "
        "a is the investigation).",
    ),
    defer: bool = typer.Option(
        False,
        "--defer",
        help="Stage an unnumbered plan under .planners/staging for collision-safe "
        "batch creation; number it later with `planners finalize`.",
    ),
    allow_branch: bool = typer.Option(
        False,
        "--allow-branch",
        help="Commit the plan even though HEAD is off the repo's mainline "
        "(dev/default branch), which normally refuses.",
    ),
    no_commit: bool = typer.Option(
        False, "--no-commit", help="Write only — no index refresh, no commit."
    ),
) -> None:
    """Scaffold a conformant plan file; by default refresh the index and commit."""
    if not is_safe_slug(slug):
        _err(f"unsafe slug: {slug!r}; use kebab-case with no '/', '..', or null bytes.")
        raise typer.Exit(1)

    root = Path.cwd()

    if nested and parent is None:
        _err("--nested needs --parent <NNN>: a nested subplan lives in its umbrella.")
        raise typer.Exit(1)
    if letter is not None and not nested:
        _err("--letter applies to --nested subplans only.")
        raise typer.Exit(1)
    if nested and defer:
        _err(
            "--defer cannot be combined with --nested: a nested subplan takes a "
            "letter from its umbrella, not a number from `finalize`."
        )
        raise typer.Exit(1)
    if nested and parent is not None:
        _add_nested(
            root,
            slug,
            parent,
            title=title or "",
            branch=branch or "",
            letter=letter,
            allow_branch=allow_branch,
            no_commit=no_commit,
        )
        return

    # Guard before writing anything, so a refusal leaves no half-scaffolded plan
    # directory behind — the same ordering the unsafe-slug check above relies on.
    # Only the committing paths are guarded: --no-commit and --defer write no
    # commit, so there is nothing for a branch to strand.
    if not no_commit and not defer:
        _guard_base_branch(root, "plan [add]", allow_branch=allow_branch)

    if defer:
        # Deferred creation: write an unnumbered plan into a per-creator staging
        # directory with no commit and no shared state, so any number of concurrent
        # `add --defer` creators can run in parallel. `finalize` is the single
        # serialized writer that orders, numbers, and commits the batch.
        if parent is not None:
            _err(
                "--defer cannot be combined with --parent: a subplan is numbered "
                "against its umbrella, which `finalize` does not assign."
            )
            raise typer.Exit(1)
        staging = root / STAGING_DIR
        staging.mkdir(parents=True, exist_ok=True)
        # A random token keys the staging dir so two creators picking the same slug
        # never collide on the directory name (the number, and any slug clash, are
        # resolved at finalize, the sole writer).
        staged_dir = staging / f"{secrets.token_hex(4)}-{slug}"
        if staged_dir.exists():
            _err(f"staging collision at {staged_dir.relative_to(root)}; retry.")
            raise typer.Exit(1)
        staged_dir.mkdir(parents=True)
        staged_path = staged_dir / PLAN_FILENAME
        staged_path.write_text(
            _render_staged_plan(slug, title or "", branch or ""), encoding="utf-8"
        )
        typer.echo(
            f"staged {staged_path.relative_to(root)} "
            "(assign its number with `planners finalize`)"
        )
        return

    plans_dir = root / PLANS_DIR
    plans_dir.mkdir(parents=True, exist_ok=True)

    existing = _collect_metas(plans_dir, strict=False)
    if parent is None:
        # Top-level plan: next free number, no subplan letter.
        plan_id, sub = next_number(_taken_numbers(plans_dir)), ""
    else:
        # Subplan: share the umbrella's number and take the next free letter. The
        # umbrella must already exist — a subplan with no umbrella is invalid.
        if not any(m.id == parent and not m.sub for m in existing):
            _err(
                f"no umbrella plan {parent:03d} found under {PLANS_DIR}; "
                "create it first with `planners add`."
            )
            raise typer.Exit(1)
        plan_id = parent
        try:
            sub = next_sub([m.sub for m in existing if m.id == parent])
        except ValueError as exc:
            _err(str(exc))
            raise typer.Exit(1) from None

    prefix = f"{plan_id:03d}{sub}"
    plan_dir = plans_dir / f"{prefix}-{slug}"
    if plan_dir.exists():
        _err(f"refusing to overwrite existing plan: {plan_dir.relative_to(root)}")
        raise typer.Exit(1)
    plan_dir.mkdir(parents=True)
    path = plan_dir / PLAN_FILENAME

    meta = PlanMetadata(
        id=plan_id,
        slug=slug,
        sub=sub,
        status=Status.draft,
        branch=branch or "",
        created=_now(),
        concluded="",
        pr="",
        title=title or "",
    )
    path.write_text(meta.render(), encoding="utf-8")
    typer.echo(f"wrote {path.relative_to(root)}")

    if no_commit:
        return

    readme = _refresh_index(root, cols="curated")
    _commit(
        root,
        f"plan [add]: {prefix} - {slug}",
        [str(path.relative_to(root)), str(readme.relative_to(root))],
    )


@app.command()
def finalize(
    allow_branch: bool = typer.Option(
        False,
        "--allow-branch",
        help="Commit the batch even though HEAD is off the repo's mainline "
        "(dev/default branch), which normally refuses.",
    ),
    no_commit: bool = typer.Option(
        False,
        "--no-commit",
        help="Materialize and refresh the index, but don't commit.",
    ),
) -> None:
    """Number, materialize, and commit staged (deferred) plans in ``created`` order.

    The single serialized writer behind ``add --defer``: it orders the staged
    plans by ``created``, assigns the next sequential numbers, moves each into
    ``.planners/plans/<NNN>-<slug>/`` (sidecar files included), refreshes the
    index, commits each one (mirroring a foreground ``add``), and then runs a
    self-check. Being the sole writer, it cannot race on numbering or the commit.
    """
    root = Path.cwd()

    # Guard before materializing: a refusal must leave the batch staged and
    # recoverable, not half-moved out of staging with no commit to show for it.
    if not no_commit:
        _guard_base_branch(root, "plan [add]", allow_branch=allow_branch)

    staging = root / STAGING_DIR
    staged = _collect_staged(staging)
    if not staged:
        _err(f"no staged plans under {STAGING_DIR}; nothing to finalize.")
        raise typer.Exit(1)

    plans_dir = root / PLANS_DIR
    plans_dir.mkdir(parents=True, exist_ok=True)
    start_id = next_number(_taken_numbers(plans_dir))

    # Pass 1 — validate and resolve every staged plan WITHOUT touching the
    # filesystem. A bad entry aborts the batch before any plan is moved out of
    # staging, so a later failure can't strand earlier plans materialized-but-
    # uncommitted (the partial-batch hazard the single commit avoids, one step
    # earlier). Constructing the meta is pure, so it belongs in this pass too.
    resolved: list[tuple[PlanMetadata, str, Path, Path]] = []
    seen_slugs: set[str] = set()
    for offset, (src_dir, data, body) in enumerate(staged):
        slug = data.get("slug") or ""
        if not is_safe_slug(slug):
            _err(
                f"staged plan {src_dir.name!r} has an unsafe or missing slug "
                f"{slug!r}; fix it under {STAGING_DIR} and re-run."
            )
            raise typer.Exit(1)
        created = data.get("created") or ""
        if not created:
            _err(
                f"staged plan {src_dir.name!r} has no created timestamp; it cannot "
                "be ordered. Fix it and re-run."
            )
            raise typer.Exit(1)
        raw_status = data.get("status") or "draft"
        try:
            status = Status(raw_status)
        except ValueError:
            _err(f"staged plan {src_dir.name!r} has invalid status {raw_status!r}.")
            raise typer.Exit(1) from None

        plan_id = start_id + offset
        plan_dir = plans_dir / f"{plan_id:03d}-{slug}"
        if plan_dir.exists():
            _err(f"refusing to overwrite existing plan: {plan_dir.relative_to(root)}")
            raise typer.Exit(1)
        if slug in seen_slugs:
            # Numbering keeps them distinct, but two same-slug dirs is worth a heads-up.
            _warn(
                f"note: duplicate slug {slug!r} in this batch (kept distinct by number)"
            )
        seen_slugs.add(slug)

        meta = PlanMetadata(
            id=plan_id,
            slug=slug,
            status=status,
            branch=data.get("branch", "") or "",
            created=created,
            concluded=data.get("concluded", "") or "",
            pr=data.get("pr", "") or "",
        )
        # Validate the exact text pass 2 will write, so a value the self-check
        # would reject (an unparseable `created`, say) stops the batch here,
        # while every plan is still in staging and a re-run can find it.
        try:
            problems = PlanMetadata.from_text(
                meta.render_frontmatter() + body, dirname=plan_dir.name
            ).validate()
        except PlanError as exc:
            problems = [str(exc)]
        if problems:
            _err(
                f"staged plan {src_dir.name!r} is not valid: {'; '.join(problems)}. "
                "Fix it and re-run."
            )
            raise typer.Exit(1)
        resolved.append((meta, body, src_dir, plan_dir))

    # Pass 2 — materialize: every entry is validated, so this only moves files.
    finalized: list[tuple[int, str, Path]] = []
    for meta, body, src_dir, plan_dir in resolved:
        plan_dir.mkdir(parents=True)
        # Preserve the creator's body (title + any drafted ## Plan) verbatim; only
        # the frontmatter is re-rendered, now that the id is known.
        (plan_dir / PLAN_FILENAME).write_text(
            meta.render_frontmatter() + body, encoding="utf-8"
        )
        for child in sorted(src_dir.iterdir()):
            if child.name != PLAN_FILENAME:
                shutil.move(str(child), str(plan_dir / child.name))
        (src_dir / PLAN_FILENAME).unlink()
        src_dir.rmdir()
        finalized.append((meta.id, meta.slug, plan_dir))
        typer.echo(f"numbered {src_dir.name} -> {plan_dir.relative_to(root)}")

    # Drop the staging root once drained (leave it if anything unexpected remains).
    if staging.is_dir() and not any(staging.iterdir()):
        staging.rmdir()

    readme = _refresh_index(root, cols="curated")

    if no_commit:
        typer.echo(f"finalized {len(finalized)} plan(s) (no commit)")
        _finalize_self_check(root, finalized, start_id, committed=False)
        return

    # One commit for the whole batch: atomic at the commit boundary. A mid-batch
    # per-plan commit loop could land some plans and strand the rest materialized
    # but uncommitted with no diagnostic; a single commit instead either lands the
    # whole batch or leaves every plan in the same recoverable "written, not yet
    # committed" state (the documented `add` trade-off, applied uniformly).
    rels = [str(plan_dir.relative_to(root)) for _, _, plan_dir in finalized]
    rels.append(str(readme.relative_to(root)))
    _git(root, ["add", *rels])
    first, last = finalized[0][0], finalized[-1][0]
    message = (
        f"plan [add]: {first:03d} - {finalized[0][1]}"
        if len(finalized) == 1
        else f"plan [add]: {first:03d}-{last:03d} ({len(finalized)} plans)"
    )
    _git(root, ["commit", "-m", message, "--", *rels])
    typer.echo(f"finalized and committed {len(finalized)} plan(s)")
    _finalize_self_check(root, finalized, start_id, committed=True)


@app.command()
def activate(
    ref: str = typer.Argument(
        ..., help="Plan number, e.g. 005 (or 005a for a subplan)."
    ),
    branch: str | None = typer.Option(
        None,
        "--branch",
        help="Branch name to record; defaults to feature/<slug>. An already-filled "
        "branch: field is left alone.",
    ),
    worktree: str | None = typer.Option(
        None,
        "--worktree",
        help="Repo-relative worktree path to record in the Log entry; defaults to "
        ".worktrees/<branch-suffix>.",
    ),
    no_worktree: bool = typer.Option(
        False,
        "--no-worktree",
        help="Record that the work happens in the main checkout, not a worktree.",
    ),
    allow_branch: bool = typer.Option(
        False,
        "--allow-branch",
        help="Commit the activation even though HEAD is off the repo's mainline "
        "(dev/default branch), which normally refuses.",
    ),
    no_commit: bool = typer.Option(
        False, "--no-commit", help="Write only — no index refresh, no commit."
    ),
) -> None:
    """Flip a plan to active, fill its branch, log where the work is, and commit.

    The activation commit belongs on the mainline, *before* the feature branch
    exists, so the plan is recorded there even if the branch never lands. That
    ordering was previously prose in two skills instructing a hand-edit of the
    frontmatter — which is why the ``plan [activate]`` subjects in this repo's own
    history disagree with each other, and why no guard could cover the step. Both
    problems are the same problem: there was no code to put them in.

    The activation appends a standard entry to the plan's Log naming the branch,
    the base and the commit it starts from, the worktree, and the PR, so the plan
    file says where its work lives without anyone rebuilding it from git.

    A plan in ``implemented`` that review sends back is reactivated the same way,
    on its feature branch: that return is not guarded, and it logs a short
    ``Reactivated`` entry instead.
    """
    root = Path.cwd()
    if worktree is not None and no_worktree:
        _err("--worktree and --no-worktree cannot be combined.")
        raise typer.Exit(1)
    if worktree is not None:
        problem = entries.worktree_error(worktree)
        if problem is not None:
            _err(f"error: {problem}.")
            raise typer.Exit(1)

    # Resolve and validate before the branch guard, the ordering `add` uses for its
    # slug check. A closed plan is closed on every branch, so leading with the branch
    # would send the user to switch branches and only then learn the real blocker.
    path = _resolve_plan(root / PLANS_DIR, ref)
    meta = _read_plan(root, path)

    if meta.status in CLOSED_STATUSES:
        _err(
            f"plan {meta.prefix} is {meta.status}; it is closed. Reopen it by setting "
            "status: draft (or inactive) if the work is genuinely resuming."
        )
        raise typer.Exit(1)

    # An empty branch: is pending, so fill it; a populated one is the user's answer
    # and is never overwritten (--branch on an already-filled plan is a no-op).
    new_branch = meta.branch or branch or f"feature/{meta.slug}"
    unchanged = meta.status == Status.active and new_branch == meta.branch

    # The worktree is recorded only in the first activation's entry, so the flags
    # mean nothing to a plan that is already active or is coming back from review.
    if (worktree is not None or no_worktree) and meta.status in (
        Status.active,
        Status.implemented,
    ):
        _warn(
            f"warning: plan {meta.prefix} is {meta.status}, so no activation entry "
            "is written; --worktree and --no-worktree are not recorded."
        )

    # Idempotent rather than an error: re-running activate destroys nothing (unlike
    # `add`, which refuses in order to protect a body), and a no-op keeps the command
    # safe inside a pipeline that may retry it. But *already active* is not the same
    # as *already committed* — an earlier run can have written and staged the plan and
    # then failed at the commit (a rejecting hook, no commit identity). Deciding from
    # the frontmatter alone would report that failure as success and strand the
    # activation staged forever, so the file must also be unmodified against HEAD.
    # This runs before the guard: a genuine no-op commits nothing, so there is nothing
    # for a feature branch to strand and nothing for the guard to protect.
    if unchanged and (no_commit or _is_unmodified(root, path)):
        typer.echo(
            f"plan {meta.prefix} is already active on {meta.branch}; nothing to do."
        )
        return

    # Guard before writing, so a refusal leaves the plan exactly as it was — the
    # ordering `add` uses. Only the committing path is guarded: --no-commit writes
    # no commit, so there is nothing for a branch to strand. A plan coming back
    # from `implemented` is on its feature branch by design, where review sent it.
    returning = meta.status == Status.implemented
    if not no_commit and not returning:
        _guard_base_branch(root, "plan [activate]", allow_branch=allow_branch)

    if unchanged:
        # Reached only via the staged-but-uncommitted path above: the frontmatter is
        # already right, so there is nothing to rewrite — just the commit to finish.
        typer.echo(
            f"plan {meta.prefix} is already active on {meta.branch}; "
            "committing the pending activation."
        )
    else:
        _, body = split_frontmatter(path.read_text(encoding="utf-8"))
        # An already-active plan that only gains its branch was activated before,
        # so it gets no second entry; that keeps a re-run idempotent.
        entry = None
        if returning:
            entry = entries.reactivation_entry(_now())
        elif meta.status != Status.active:
            entry = _activation_entry(
                root, meta, new_branch, worktree=worktree, no_worktree=no_worktree
            )
        meta.status = Status.active
        meta.branch = new_branch
        if entry is not None:
            body = append_to_section(
                body, "Log", entry, before=("Handoff", "Retrospective")
            )
        # Re-render only the frontmatter and keep the body verbatim — the same
        # mutate-preserving-body shape `finalize` uses. The plan text is the record.
        path.write_text(meta.render_frontmatter() + body, encoding="utf-8")
        # The branch named here is the one written to the frontmatter, where the
        # work will go. It is not where the activation is committed, which the
        # line after the commit says, so the two are never read as one.
        typer.echo(f"activated {_shown(path, root)}; recorded branch {meta.branch}")

    if no_commit:
        return

    readme = _refresh_index(root, cols="curated")
    _git(root, ["add", str(path.relative_to(root)), str(readme.relative_to(root))])
    # The subject names the slug, not the title: a slug is fixed by the directory
    # name, while a title can be reworded until the subject no longer names the plan
    # it belongs to. Matches what `add` writes, and a format string owns it, so it
    # cannot drift the way the hand-written subjects did.
    _git(
        root,
        [
            "commit",
            "-m",
            f"plan [activate]: {meta.prefix} - {meta.slug}",
            "--",
            str(path.relative_to(root)),
            str(readme.relative_to(root)),
        ],
    )
    current = _current_branch(root)
    typer.echo(f"committed the activation on {current}")
    # The skill pushes next, and that push carries every unpushed commit on the
    # base. Count and sort them here so the skill reads a fact instead of sorting
    # by eye; quiet when there is no upstream to compare against.
    ahead = ahead_mod.count(root, current, path.parent.relative_to(root).as_posix())
    if ahead is not None:
        for line in ahead_mod.report(ahead, meta.prefix):
            typer.echo(line)


def _activation_entry(
    root: Path,
    meta: PlanMetadata,
    branch: str,
    *,
    worktree: str | None,
    no_worktree: bool,
) -> str:
    """The activation Log entry for ``meta``, read from HEAD as it stands now.

    Called before the activation commit is made, so the commit it records is the
    one the activation sits on, which is where the feature branch will start.
    """
    mainline = base_mod.detect(root)
    sha = proc.git_out(root, ["rev-parse", "--short", "HEAD"])
    if no_worktree:
        recorded = entries.NO_WORKTREE
    else:
        recorded = worktree or entries.default_worktree(branch)
    return entries.activation_entry(
        _now(),
        branch=branch,
        base=mainline.current,
        sha=sha.strip() if sha else None,
        worktree=recorded,
        pr=meta.pr or None,
    )


def _current_branch(root: Path) -> str:
    """The branch HEAD is on, in words fit for a message."""
    return base_mod.detect(root).current or "a detached HEAD"


def _head_authored(root: Path) -> str | None:
    """The authored date of ``HEAD`` as ISO-8601, or ``None`` when there is none."""
    return (proc.git_out(root, ["log", "-1", "--format=%aI"]) or "").strip() or None


@app.command(name="set-pr")
def set_pr(
    ref: str = typer.Argument(
        ..., help="Plan number, e.g. 005 (or 005d for a nested subplan)."
    ),
    url: str = typer.Argument(..., help="The full PR URL."),
    no_commit: bool = typer.Option(
        False, "--no-commit", help="Write only — no index refresh, no commit."
    ),
) -> None:
    """Record a plan's PR URL, log it, refresh the index, and commit.

    The index shows the PR, so the three hand steps (edit ``pr:``, regenerate,
    commit) are one command here and the middle one cannot be forgotten. There is
    no mainline guard: the PR exists once the branch does, so this commit belongs
    on the branch with the work.

    For a nested subplan the URL goes in the subplan's own ``pr:``, which is how a
    step that lands through another repo's PR is recorded.
    """
    root = Path.cwd()
    if not re.fullmatch(r"https?://\S+", url):
        _err(f"not a PR URL: {url!r}; pass the full URL, not the number.")
        raise typer.Exit(1)

    plan, nested, label = _resolve_ref(root / PLANS_DIR, ref)
    target = nested or plan

    if nested is not None:
        text = nested.read_text(encoding="utf-8")
        updated = set_frontmatter_key(text, "pr", url)
        slug = nested.stem[2:]
        staged = [nested]
    else:
        meta = _read_plan(root, plan)
        text = plan.read_text(encoding="utf-8")
        _, body = split_frontmatter(text)
        meta.pr = url
        updated = meta.render_frontmatter() + body
        slug = meta.slug
        staged = [plan]

    if updated == text and (no_commit or _is_unmodified(root, target)):
        typer.echo(f"plan {label} already records {url}; nothing to do.")
        return
    if updated != text:
        # The entry goes in only with a change of URL, so a re-run that finishes
        # an interrupted commit does not log the same PR twice.
        updated = append_to_section(
            updated,
            "Log",
            entries.pr_entry(_now(), url),
            before=("Handoff", "Retrospective"),
        )
        target.write_text(updated, encoding="utf-8")
        typer.echo(f"recorded {url} in {_shown(target, root)}")

    if no_commit:
        return

    if nested is None:
        staged.append(_refresh_index(root, cols="curated"))
    _commit(
        root,
        f"plan [pr]: {label} - {slug}",
        [str(path.relative_to(root)) for path in staged],
    )


def _unpublished_work(
    root: Path,
    mainline: base_mod.Mainline,
    *,
    ignore: tuple[Path, ...] = (),
    require_upstream: bool = True,
    check_upstream: bool = True,
) -> list[str]:
    """What the branch at ``root`` holds that a reviewer of its PR cannot see.

    Uncommitted changes, commits not pushed to the upstream, and a branch with no
    upstream at all in a repo that has a remote. A repo with no remote has nothing
    to publish to, so only its uncommitted changes count. Outside a repo there is
    nothing to check, and the commit that follows reports that on its own.

    ``require_upstream=False`` drops the no-upstream problem, for a remote whose
    review does not happen on a pushed branch (see :mod:`planners.remote`). A
    branch that does have an upstream is still checked for unpushed commits,
    unless ``check_upstream=False``: on a single-branch remote the upstream is
    the live document, and pushing to it is a publish, not a precondition.

    ``ignore`` names files whose changes are not counted: the ones an earlier run
    wrote and then failed to commit, which this run is about to commit itself.
    """
    status = _git_status_porcelain(root)
    if status is None:
        return []
    problems: list[str] = []
    skipped = {str(path.relative_to(root)) for path in ignore}
    # Split rather than slice: the helper strips its output, which takes the
    # leading space off the first line's status column.
    changed = sum(
        1 for line in status.splitlines() if line.split(maxsplit=1)[-1] not in skipped
    )
    if changed:
        problems.append(f"{changed} uncommitted change(s); commit them first")
    if not check_upstream:
        return problems
    upstream = proc.git_out(
        root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    if upstream is None:
        if (
            require_upstream
            and mainline.current is not None
            and (proc.git_out(root, ["remote"]) or "").strip()
        ):
            branch = mainline.current
            problems.append(
                f"{branch} has no upstream; push it with `git push -u origin {branch}`"
            )
        return problems
    unpushed = int(
        proc.git_out(root, ["rev-list", "--count", "@{upstream}..HEAD"]) or 0
    )
    if unpushed > 0:
        problems.append(
            f"{unpushed} commit(s) not pushed to {upstream.strip()}; push first"
        )
    return problems


def _ahead_of(root: Path, base: str) -> int | None:
    """How many commits HEAD has that ``base`` lacks, or ``None`` when unknown.

    ``origin/<base>`` is tried first, since that is what the PR is compared with
    and a local base can lag it; a repo with no remote copy falls back to the
    local branch.
    """
    for ref in (f"origin/{base}", base):
        out = proc.git_out(root, ["rev-list", "--count", f"{ref}..HEAD"])
        if out is not None:
            return int(out)
    return None


def _mark_pr_ready(root: Path, url: str) -> None:
    """Take the PR at ``url`` out of draft, warning rather than failing.

    The status change is already committed by the time this runs, so a gh that is
    missing, unauthenticated, or offline is reported for the user to finish by
    hand instead of undoing a commit that is correct.
    """
    try:
        result = proc.run(root, ["gh", "pr", "ready", url], capture_output=True)
    except OSError:
        _warn(f"warning: gh is not available; run `gh pr ready {url}` by hand.")
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _warn(
            f"warning: `gh pr ready {url}` failed"
            + (f": {detail}" if detail else "")
            + "; run it by hand."
        )
        return
    typer.echo(f"marked {url} ready for review")


def _implemented_entry(
    root: Path,
    text: str,
    plan: Path,
    nested: Path | None,
    mainline: base_mod.Mainline,
) -> str:
    """The Log entry ``implemented`` writes, counting the work past its base.

    The base is the one the activation entry recorded: in the subplan for a step
    on a sub-branch of its own, else in the umbrella, else the detected mainline.
    """
    base = entries.recorded_base(text)
    if base is None and nested is not None:
        base = entries.recorded_base(plan.read_text(encoding="utf-8"))
    if base is None and mainline.resolved:
        base = mainline.branches[0]
    ahead = _ahead_of(root, base) if base is not None else None
    return entries.implemented_entry(_now(), ahead, base)


@app.command()
def implemented(
    ref: str = typer.Argument(
        ..., help="Plan number, e.g. 005 (or 005d for a nested subplan)."
    ),
    no_commit: bool = typer.Option(
        False,
        "--no-commit",
        help="Write only: no index refresh, no commit, and the PR stays a draft.",
    ),
) -> None:
    """Mark an active plan implemented: its work is done and its PR awaits review.

    Flips ``active`` to ``implemented``, appends a Log entry counting the commits
    the branch carries past its base, refreshes the index, and commits on the
    feature branch. When the plan has a PR it is then taken out of draft, since
    ``implemented`` means it is open for review.

    Refuses unless the plan is ``active``, and unless the branch is fully
    committed and pushed, so the plan never says implemented about work the
    reviewer cannot see. It closes nothing: merging, the Retrospective, and
    ``concluded`` stay with ``close``. Review that asks for more work returns the
    plan with ``planners activate``.

    For a nested subplan the subplan's own file changes and the umbrella's table
    follows; only a PR recorded in the subplan itself is taken out of draft.
    """
    root = Path.cwd()
    plan, nested, label = _resolve_ref(root / PLANS_DIR, ref)
    target = nested or plan

    meta: PlanMetadata | None = None
    try:
        text = target.read_text(encoding="utf-8")
        if nested is not None:
            sub_meta = SubplanMetadata.from_text(text, nested.name)
            status, pr, slug = sub_meta.status, sub_meta.pr, sub_meta.step
            # An empty subplan branch means the umbrella's.
            recorded = sub_meta.branch or PlanMetadata.from_file(plan).branch
        else:
            meta = PlanMetadata.from_text(text, plan.parent.name)
            status, pr, slug = meta.status, meta.pr, meta.slug
            recorded = meta.branch
    except (PlanError, SubplanError, OSError, UnicodeDecodeError) as exc:
        _err(f"cannot read {_shown(target, root)}: {exc}")
        raise typer.Exit(1) from None

    kind = "subplan" if nested is not None else "plan"
    # An earlier run that wrote the status and then failed to commit (a rejecting
    # hook, say) left the plan reading `implemented` with its change uncommitted.
    # That run is finished here rather than refused, as `activate` and `set-pr` do.
    resuming = (
        status == Status.implemented
        and not no_commit
        and not _is_unmodified(root, target)
    )
    if status != Status.active and not resuming:
        _err(
            f"{kind} {label} is {status.value}; only an active {kind} can be marked "
            "implemented."
        )
        raise typer.Exit(1)

    # The status change belongs on the feature branch, beside the work it
    # describes; on the mainline it would say implemented about unmerged work.
    mainline = base_mod.detect(root)
    if not no_commit and (mainline.detached or mainline.on_mainline):
        where = (
            "HEAD is detached"
            if mainline.detached
            else f"HEAD is on the mainline branch '{mainline.current}'"
        )
        _err(
            f"error: {kind} {label} is not marked implemented: {where}. "
            "Run it on the plan's feature branch."
        )
        raise typer.Exit(1)
    # The checks below inspect the current branch, so on any branch but the
    # recorded one they would vouch for work that is not this plan's.
    if not no_commit and recorded and mainline.current != recorded:
        _err(
            f"error: {kind} {label} is not marked implemented: it records branch "
            f"'{recorded}', but HEAD is on '{mainline.current}'."
        )
        raise typer.Exit(1)

    ignore = (target, plan, root / INDEX_PATH) if resuming else ()
    # Only a GitHub origin reviews the pushed branch; elsewhere the feature branch
    # may be unpushable (a single-branch bridge) or simply unreviewed there.
    origin = remote_mod.classify(root)
    require_upstream = origin.kind is remote_mod.RemoteKind.github
    check_upstream = origin.kind is not remote_mod.RemoteKind.single_branch
    if not check_upstream:
        typer.echo(
            f"origin is {origin.kind.value}: only uncommitted changes are checked"
        )
    elif not require_upstream and origin.kind is not remote_mod.RemoteKind.none:
        typer.echo(f"origin is {origin.kind.value}: a missing upstream is not refused")
    problems = _unpublished_work(
        root,
        mainline,
        ignore=ignore,
        require_upstream=require_upstream,
        check_upstream=check_upstream,
    )
    if problems:
        _err(f"{kind} {label} is not marked implemented: the branch has")
        for problem in problems:
            _err(f"  - {problem}")
        raise typer.Exit(1)

    if resuming:
        staged = [target, plan] if nested is not None else [plan]
        typer.echo(f"committing the earlier change to {_shown(target, root)}")
    else:
        entry = _implemented_entry(root, text, plan, nested, mainline)
        if meta is None:
            updated = set_frontmatter_key(text, "status", Status.implemented.value)
            updated = append_to_section(
                updated, "Log", entry, before=("Handoff", "Retrospective")
            )
            _sync_subplans(root, plan, {target: updated})
            staged = [target, plan]
        else:
            _, body = split_frontmatter(text)
            meta.status = Status.implemented
            body = append_to_section(
                body, "Log", entry, before=("Handoff", "Retrospective")
            )
            plan.write_text(meta.render_frontmatter() + body, encoding="utf-8")
            staged = [plan]
        typer.echo(f"marked {_shown(target, root)} implemented")

    if no_commit:
        return

    if nested is None:
        staged.append(_refresh_index(root, cols="curated"))
    _commit(
        root,
        f"plan [implemented]: {label} - {slug}",
        [str(path.relative_to(root)) for path in staged],
    )
    if pr:
        _mark_pr_ready(root, pr)
    typer.echo(f"push {_current_branch(root)} so the PR shows the status change")


def _closed_plan(root: Path, plan: Path, branch: str, base: str) -> PlanMetadata:
    """The plan as its branch has it, where the closing commit was made.

    The branch's copy is read first, then its remote copy, then the remote
    base's, and the checkout's own copy last: before the pull the local base
    still has the activated plan, without the PR and the ``done`` status the
    branch recorded, and once the branch is deleted (``gh pr merge
    --delete-branch``) the merged base is the only place that has both.
    """
    rel = plan.relative_to(root).as_posix()
    text: str | None = None
    refs = [f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"]
    if base:
        refs.append(f"refs/remotes/origin/{base}")
    for ref in refs:
        text = proc.git_out(root, ["show", f"{ref}:{rel}"])
        if text is not None:
            break
    if text is None:
        text = plan.read_text(encoding="utf-8")
    try:
        return PlanMetadata.from_text(text, plan.parent.name)
    except PlanError as exc:
        raise finish_mod.Stop(f"cannot read {rel} on {branch}: {exc}") from None


def _sync_base(root: Path, base: str, say: finish_mod.Say) -> None:
    """Check ``base`` out in ``root`` and fast-forward it to the merged base.

    That is its upstream, or ``origin/<base>`` for a base with no upstream set:
    the branch deletions that follow test against the local base, and a base
    left behind the merge would read the merged branch as holding unmerged work.
    The caller has fetched already, once, at the start of ``finish``.
    """
    if _current_branch(root) != base:
        finish_mod.must(root, ["git", "checkout", base])
        say(f"checked out {base}")
    if proc.git_out(root, ["rev-parse", "--verify", "-q", "@{upstream}"]) is not None:
        finish_mod.must(root, ["git", "pull", "--ff-only"])
        say(f"pulled {base}")
        return
    tracking = f"refs/remotes/origin/{base}"
    if proc.git_out(root, ["rev-parse", "--verify", "-q", tracking]) is None:
        return
    finish_mod.must(root, ["git", "merge", "--ff-only", tracking])
    say(f"fast-forwarded {base} to origin/{base}")


def _remote_or_local(root: Path, branch: str) -> str:
    """``origin/<branch>`` when it exists, as last fetched, else ``branch`` itself."""
    tracking = f"refs/remotes/origin/{branch}"
    if proc.git_out(root, ["rev-parse", "--verify", "-q", tracking]) is not None:
        return tracking
    return f"refs/heads/{branch}"


def _unmerged_work(worktree: Path, merged: str, base: str) -> list[str]:
    """What the worktree holds that the merged base ``merged`` does not.

    The branch is merged by now, so its upstream is no test: GitHub may have
    deleted it and a prune taken the tracking ref. What matters is that nothing
    is uncommitted and every commit at the worktree's HEAD is in the base.
    """
    problems: list[str] = []
    status = _git_status_porcelain(worktree)
    if status:
        changed = len(status.splitlines())
        problems.append(f"{changed} uncommitted change(s); commit them first")
    ahead = proc.git_out(worktree, ["rev-list", "--count", f"{merged}..HEAD"])
    if ahead and int(ahead):
        problems.append(
            f"{int(ahead)} commit(s) {base} does not have; merge or drop them"
        )
    return problems


def _check_merged(
    root: Path, branch: str, base: str, *, pr_url: str | None
) -> finish_mod.PullRequest | None:
    """The merged PR, or ``None`` on the no-PR path; a stop when not merged yet.

    The merge is the session's own command, never ``finish``'s (see
    :mod:`planners.finish`), so a branch that is not merged is a stop that
    prints the command to run before the re-run.
    """
    if pr_url is not None:
        pr = finish_mod.view_pr(root, pr_url)
        if pr.state == "MERGED":
            return pr
        if pr.state == "CLOSED":
            raise finish_mod.Stop(f"PR #{pr.number} is closed without being merged")
        subject = finish_mod.merge_subject(pr.label, pr.number)
        raise finish_mod.Stop(
            f"PR #{pr.number} is not merged yet. Merge it, then run finish again:\n"
            f'  gh pr merge {pr.number} --merge --subject "{subject}"'
        )
    source = next(
        (
            ref
            for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}")
            if proc.git_out(root, ["rev-parse", "--verify", "-q", ref]) is not None
        ),
        None,
    )
    if source is not None and not finish_mod.is_ancestor(
        root, source, _remote_or_local(root, base)
    ):
        subject = finish_mod.merge_subject(branch)
        raise finish_mod.Stop(
            f"{branch} is not merged into {base} yet. From {base}, merge and push "
            "it, then run finish again:\n"
            f'  git merge --no-ff {branch} -m "{subject}" && git push'
        )
    return None


def _finish(root: Path, ref: str, *, no_pr: bool, say: finish_mod.Say) -> None:
    """The steps of ``finish``, each raising :class:`finish.Stop` on a real issue."""
    plan = _resolve_plan(root / PLANS_DIR, ref)
    parts = DIRNAME_RE.match(plan.parent.name)
    label = f"{parts.group(1)}{parts.group(2)}" if parts else ref
    try:
        on_base = PlanMetadata.from_file(plan)
    except PlanError as exc:
        raise finish_mod.Stop(f"cannot read {_shown(plan, root)}: {exc}") from None
    branch = on_base.branch
    mainline = base_mod.detect(root)
    if not branch:
        raise finish_mod.Stop(f"plan {label} records no branch; nothing to finish")
    if branch in mainline.branches:
        raise finish_mod.Stop(
            f"plan {label} records the mainline branch {branch}; finish never "
            "deletes a mainline branch"
        )

    if not _is_unmodified(root, root / INDEX_PATH):
        # finish commits the index it regenerates; a change it did not make
        # would ride along in that commit, under a subject that misnames it.
        raise finish_mod.Stop(
            f"{INDEX_PATH.as_posix()} has uncommitted changes; commit or discard "
            "them before finishing"
        )

    base = entries.recorded_base(plan.read_text(encoding="utf-8"))
    if base is None and mainline.resolved:
        base = mainline.branches[0]
    finish_mod.must(root, ["git", "fetch", "--prune"])
    meta = _closed_plan(root, plan, branch, base or "")
    if meta.status != Status.done:
        raise finish_mod.Stop(
            f"plan {label} is {meta.status.value} on {branch}; close it "
            "(status done), commit, and push before finishing"
        )
    no_pr = no_pr or meta.pr is None
    if not no_pr and not meta.pr:
        raise finish_mod.Stop(
            f"plan {label} records no PR; record it with `planners set-pr {label} "
            "<url>`, or pass --no-pr for a branch merged locally"
        )
    if no_pr and not base:
        raise finish_mod.Stop("cannot tell which branch is the base")

    pr = _check_merged(root, branch, base or "", pr_url=None if no_pr else meta.pr)
    if pr is not None:
        base = pr.base
    if not base:
        raise finish_mod.Stop("cannot tell which branch is the base")
    merged = f"PR #{pr.number}" if pr is not None else "a local merge"
    say(f"plan {label}: {branch} is merged into {base} by {merged}")

    worktree = finish_mod.find_worktree(root, branch)
    if worktree is None:
        say(f"no worktree has {branch} checked out")
    else:
        if Path.cwd().resolve().is_relative_to(worktree.resolve()):
            raise finish_mod.Stop(
                f"this is the worktree being removed; run finish from the main "
                f"checkout ({root})"
            )
        problems = _unmerged_work(worktree, _remote_or_local(root, base), base)
        if problems:
            raise finish_mod.Stop(
                f"the worktree {_shown(worktree, root)} has\n"
                + "\n".join(f"  - {problem}" for problem in problems)
            )
        hook = worktree / ".planners" / "hooks" / "pre-worktree-remove"
        if hook.is_file() and os.access(hook, os.X_OK):
            finish_mod.must(worktree, [str(hook)])
            say("ran the pre-worktree-remove hook")
        finish_mod.must(root, ["git", "worktree", "remove", str(worktree)])
        say(f"removed the worktree {_shown(worktree, root)}")

    _sync_base(root, base, say)
    finish_mod.delete_remote_branch(
        root, branch, base, say, against=_remote_or_local(root, base)
    )
    finish_mod.delete_local_branch(root, branch, base, say)

    if _index_is_stale(root):
        _refresh_index(root, cols="curated")
    if not _is_unmodified(root, root / INDEX_PATH):
        finish_mod.must(root, ["git", "add", INDEX_PATH.as_posix()])
        finish_mod.must(
            root,
            [
                "git",
                "commit",
                "-m",
                "update plan index after merge",
                "--",
                INDEX_PATH.as_posix(),
            ],
        )
        say(f"committed the regenerated plan index; push {base} to publish it")

    finish_mod.repoint_hooks(root, say)
    say(f"finished plan {label}")


@app.command()
def finish(
    ref: str = typer.Argument(..., help="Plan number, e.g. 005."),
    no_pr: bool = typer.Option(
        False,
        "--no-pr",
        help="The branch was merged locally, not through a PR. Implied when the "
        "plan records `pr: null`.",
    ),
) -> None:
    """Clean up after a closed plan's merge, from the main checkout.

    Run once the closing commit is pushed and the branch is merged: through its
    PR (`gh pr merge`), or locally with `git merge --no-ff` and a push. The
    merge stays the session's own command so the permission profile still
    governs it. In order, `finish` fetches, checks the branch is merged, checks
    the worktree holds nothing the base lacks, removes it, pulls the base, deletes the
    branch on the remote and locally, commits the plan index if the merge left
    it stale, and re-installs any hook whose interpreter was in the worktree.

    Stops with exit 1 on a real issue: a branch not merged yet (it prints the
    merge command), a worktree with uncommitted changes or commits the base
    lacks, a branch holding such commits, uncommitted changes to the plan index,
    or a refused git or gh call. A step already done is skipped, so
    a re-run after a stop picks up where the last one ended.
    """
    toplevel = proc.git_out(Path.cwd(), ["rev-parse", "--show-toplevel"])
    root = Path(toplevel.strip()) if toplevel else Path.cwd()
    try:
        _finish(root, ref, no_pr=no_pr, say=typer.echo)
    except finish_mod.Stop as exc:
        _err(f"stopped: {exc}")
        raise typer.Exit(1) from None


@app.command()
def retire(
    ref: str = typer.Argument(
        ..., help="Plan number, e.g. 005 (or 005d for a nested subplan)."
    ),
    into: str | None = typer.Option(
        None, "--into", help="The plan the work moved to, e.g. 015."
    ),
    note: str | None = typer.Option(
        None, "--note", help="A sentence for the Log entry, on why it was retired."
    ),
    no_commit: bool = typer.Option(
        False, "--no-commit", help="Write only — no index refresh, no commit."
    ),
) -> None:
    """Close a plan as retired: frontmatter, Log entry, index, and commit.

    What ``activate`` does for ``active``, for the other end of a plan that was
    superseded or is no longer needed. ``concluded`` is the authored date of
    ``HEAD``, the commit the decision was made against. A ``branch`` or ``pr``
    that was never filled becomes ``null``, since the plan is closed and they are
    confirmed absent.

    A nested subplan closes the same way in its own file, with ``moved_to``
    recording ``--into``, and the umbrella's table follows.
    """
    root = Path.cwd()
    plans_dir = root / PLANS_DIR
    plan, nested, label = _resolve_ref(plans_dir, ref)

    moved = _resolve_ref(plans_dir, into).label if into is not None else ""
    if moved and moved == label:
        _err(f"plan {label} cannot be retired into itself.")
        raise typer.Exit(1)

    sentence = "Retired."
    if moved:
        sentence += f" The work moved to plan {moved}."
    if note:
        sentence += f" {note.strip()}"
    entry = f"- **{_now()}** — {sentence}"

    if nested is not None:
        try:
            text = nested.read_text(encoding="utf-8")
            current = SubplanMetadata.from_text(text, nested.name)
        except (SubplanError, OSError, UnicodeDecodeError) as exc:
            _err(f"cannot read {_shown(nested, root)}: {exc}")
            raise typer.Exit(1) from None
        if current.status in CLOSED_STATUSES:
            _err(f"subplan {label} is {current.status}; it is closed.")
            raise typer.Exit(1)
        text = set_frontmatter_key(text, "status", Status.retired.value)
        if moved:
            text = set_frontmatter_key(text, "moved_to", moved)
        _sync_subplans(root, plan, {nested: append_to_section(text, "Log", entry)})
        typer.echo(f"retired {_shown(nested, root)}")
        staged, slug = [nested, plan], nested.stem[2:]
    else:
        meta = _read_plan(root, plan)
        if meta.status in CLOSED_STATUSES:
            _err(f"plan {meta.prefix} is {meta.status}; it is closed.")
            raise typer.Exit(1)
        # An umbrella does not close over unfinished subplans, by either door:
        # `close` checks it with `subplans --require-closed`, and this is the
        # same check for the plan that is retired instead.
        subs, unreadable = _load_subplans(plan)
        # A subplan that does not parse could be unfinished; it cannot be
        # cleared, so it blocks the umbrella like an unfinished one.
        if unreadable:
            for error in unreadable:
                _err(error)
            _err(
                f"plan {meta.prefix} has subplans that cannot be read; fix them "
                "before retiring it."
            )
            raise typer.Exit(1)
        unfinished = [
            f"{sub.letter} ({sub.status.value})"
            for sub in subs
            if sub.status in subplans_mod.UNFINISHED_STATUSES
        ]
        if unfinished:
            _err(
                f"plan {meta.prefix} has unfinished subplans: "
                f"{', '.join(unfinished)}. Finish each, or retire it first with "
                f"`planners retire {meta.prefix}<letter>`."
            )
            raise typer.Exit(1)
        _, body = split_frontmatter(plan.read_text(encoding="utf-8"))
        meta.status = Status.retired
        meta.concluded = _head_authored(root) or _now()
        meta.branch = meta.branch or None
        meta.pr = meta.pr or None
        body = append_to_section(
            body, "Log", entry, before=("Handoff", "Retrospective")
        )
        plan.write_text(meta.render_frontmatter() + body, encoding="utf-8")
        typer.echo(f"retired {_shown(plan, root)}")
        staged, slug = [plan], meta.slug

    if no_commit:
        return

    if nested is None:
        staged.append(_refresh_index(root, cols="curated"))
    _commit(
        root,
        f"plan [retire]: {label} - {slug}",
        [str(path.relative_to(root)) for path in staged],
    )


def _plan_status(
    root: Path, plan: Path, assignment: str, planned: dict[Path, str]
) -> str:
    """Add one ``<letter>=<status>`` to ``planned``, or exit; writes nothing.

    Returns the line that reports the change, for once it has been written.

    Every assignment is checked here, before any is applied, so a bad one among
    several refuses the whole command rather than the part of it that came after.
    """
    letter, sep, value = assignment.partition("=")
    letter, value = letter.strip(), value.strip()
    if not sep or not re.fullmatch(r"[a-z]", letter):
        _err(f"--set takes <letter>=<status>, got {assignment!r}.")
        raise typer.Exit(1)
    try:
        status = Status(value)
    except ValueError:
        allowed = ", ".join(s.value for s in Status)
        _err(f"invalid status {value!r}; use one of: {allowed}.")
        raise typer.Exit(1) from None
    path = _subplan_by_letter(plan.parent, letter)
    if path is None:
        _err(f"no subplan {letter!r} under {plan.parent / SUBPLANS_DIRNAME}.")
        raise typer.Exit(1)
    text = planned.get(path)
    if text is None:
        text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is None:
        # A status can be repaired in a frontmatter that exists. One is never
        # invented: a file without it is somebody's notes, not a subplan.
        _err(f"{_shown(path, root)} has no frontmatter; it is not a subplan.")
        raise typer.Exit(1)
    planned[path] = set_frontmatter_key(text, "status", status.value)
    return f"set {path.name} to {status.value}"


@app.command()
def subplans(
    ref: str = typer.Argument(..., help="The umbrella's plan number, e.g. 005."),
    write: bool = typer.Option(
        False,
        "--write",
        help="Regenerate the Status column of the umbrella's table from the "
        "subplan frontmatter.",
    ),
    set_: list[str] | None = typer.Option(
        None,
        "--set",
        help="<letter>=<status>: change one subplan's status and regenerate the "
        "table in the same step. Repeatable.",
    ),
    require_closed: bool = typer.Option(
        False,
        "--require-closed",
        help="Exit non-zero when a subplan is draft, active, implemented, or blocked: "
        "the check "
        "an umbrella passes before it closes.",
    ),
) -> None:
    """List a plan's nested subplans, and check them against the umbrella's table.

    The subplan's frontmatter is the status of record; the table is generated from
    it. Exits non-zero when the two disagree, when a subplan cannot be read or
    breaks a rule, or, with ``--require-closed``, when one is unfinished. Writes no
    commit: a status change belongs in the commit of the work it describes.
    """
    root = Path.cwd()
    plan = _resolve_plan(root / PLANS_DIR, ref)
    prefix = plan.parent.name.split("-", 1)[0]

    planned: dict[Path, str] = {}
    changes = [
        _plan_status(root, plan, assignment, planned) for assignment in set_ or []
    ]
    if write or planned:
        # The listing below reports what cannot be read, so it is not warned twice.
        _sync_subplans(root, plan, planned, warn=False)
    for change in changes:
        typer.echo(change)

    metas, problems = _load_subplans(plan)

    if not metas and not problems:
        typer.echo(f"plan {prefix} has no nested subplans")
    width = max((len(meta.filename) for meta in metas), default=0)
    for meta in metas:
        typer.echo(
            f"{prefix}{meta.letter}  {meta.status.value:<8}  "
            f"{meta.filename:<{width}}  branch: {meta.branch or '-'}  "
            f"needs: {', '.join(meta.needs) or '-'}"
        )
        problems.extend(f"{meta.filename}: {error}" for error in meta.validate())

    set_errors = subplans_mod.check_set(metas)
    problems.extend(set_errors)
    # The order is of the work to be run, so a retired subplan is not a node in
    # it. Left in, one with no needs would print as a root of the chain.
    live = [meta for meta in metas if meta.status != Status.retired]
    if any(meta.needs for meta in live) and not set_errors:
        order = subplans_mod.render_order(subplans_mod.phases(live))
        typer.echo(f"order: {order}")

    problems.extend(
        subplans_mod.table_disagreements(plan.read_text(encoding="utf-8"), metas)
    )

    if require_closed:
        problems.extend(
            f"{meta.letter}: still {meta.status.value} ({meta.filename})"
            for meta in metas
            if meta.status in subplans_mod.UNFINISHED_STATUSES
        )

    if problems:
        for problem in problems:
            _err(f"{_shown(plan, root)}: {problem}")
        _err(f"{len(problems)} problem(s) in plan {prefix}'s subplans")
        raise typer.Exit(1)


def _split_log(text: str) -> tuple[tuple[str | None, str, str], str]:
    """``text`` as (everything outside the ``## Log`` section, the Log itself).

    Two versions of a plan whose outside parts agree differ only in their Log,
    the one part of a plan ``review --commit`` may carry. The text on either side
    of the cut is compared with its surrounding blank lines stripped, so adding a
    Log section to a plan that had none, with a blank line before it, still
    reads as a Log-only change.
    """
    fm, body = split_frontmatter(text)
    span = section_span(body, "Log")
    if span is None:
        return (fm, body.strip(), ""), ""
    lines = body.splitlines(keepends=True)
    head = "".join(lines[: span[0]]).strip()
    tail = "".join(lines[span[1] :]).strip()
    return (fm, head, tail), "".join(lines[span[0] : span[1]])


def _review_commit(root: Path, *, allow_branch: bool) -> None:
    """Commit the Log entries a review wrote, and nothing else.

    Stages the top-level plan files whose ``## Log`` changed against ``HEAD``.
    Refuses when one of them changed anywhere else (a review never edits a plan's
    spec or frontmatter) or is an active, implemented, or blocked plan (whose file
    a review never edits, since its owner may be working on it elsewhere).
    """
    diff = proc.git_out(root, ["diff", "--name-only", "HEAD", "--", str(PLANS_DIR)])
    if diff is None:
        _err("cannot read the working tree's changes; is this a git repo with commits?")
        raise typer.Exit(1)
    pattern = re.compile(rf"^{re.escape(PLANS_DIR.as_posix())}/[^/]+/{PLAN_FILENAME}$")
    candidates = [line for line in diff.splitlines() if pattern.match(line)]

    staged: list[str] = []
    problems: list[str] = []
    for rel in candidates:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: deleted; a review never removes a plan")
            continue
        current = path.read_text(encoding="utf-8")
        before = proc.git_out(root, ["show", f"HEAD:{rel}"])
        if before is None:
            continue
        outside_now, log_now = _split_log(current)
        outside_before, log_before = _split_log(before)
        if outside_now != outside_before:
            problems.append(f"{rel}: changed outside its Log")
            continue
        if log_now == log_before:
            continue
        try:
            meta = PlanMetadata.from_text(current, dirname=path.parent.name)
        except PlanError as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if meta.status in review_mod.CAREFUL_STATUSES:
            problems.append(
                f"{rel}: plan {meta.prefix} is {meta.status.value}; a review never "
                "edits it, so its suggested entry goes where the work lives"
            )
            continue
        staged.append(rel)

    if problems:
        for problem in problems:
            _err(f"error: {problem}")
        _err("nothing committed; `review --commit` carries Log entries only.")
        raise typer.Exit(1)
    if not staged:
        _err("no plan has a changed Log; nothing to commit.")
        raise typer.Exit(1)

    _guard_base_branch(root, "plan [review]", allow_branch=allow_branch)
    readme = _refresh_index(root, cols="curated")
    paths = [*staged, str(readme.relative_to(root))]
    noun = "plan" if len(staged) == 1 else "plans"
    _commit(root, f"plan [review]: {len(staged)} {noun}", paths)
    typer.echo(f"committed review notes for {len(staged)} {noun}")


@app.command()
def review(
    ref: str | None = typer.Argument(
        None, help="One plan to review, whatever its status, e.g. 011 (or 012a)."
    ),
    status: list[str] | None = typer.Option(
        None,
        "--status",
        "-s",
        help="Statuses to review (repeatable): all, active, draft, done, retired, "
        "implemented, blocked, or inactive. Default: active, implemented, draft, and "
        "blocked.",
    ),
    json_: bool = typer.Option(
        False, "--json", help="Emit the report as JSON, for the review skill."
    ),
    stale_days: int = typer.Option(
        14,
        "--stale-days",
        min=0,
        help="Idle days after which an active, implemented, or blocked plan's branch "
        "is flagged.",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        help="Commit the Log entries a review wrote (draft, done, retired, and "
        "inactive plans only), with a refreshed index.",
    ),
    allow_branch: bool = typer.Option(
        False,
        "--allow-branch",
        help="With --commit: commit even though HEAD is off the repo's mainline.",
    ),
) -> None:
    """Report what changed in the repo around each plan. Reads only.

    For each selected plan: the commits and tags since it was created (or last
    reviewed), the code paths and ``module.function`` names it mentions and
    whether they still exist, the plans it names, and for an active, implemented,
    or blocked plan the state of its branch, worktree, and PR. The ``review`` skill
    turns this into a verdict and a Log entry per plan; ``--commit`` then commits
    those entries, and is the only form that writes.
    """
    root = Path.cwd()
    if commit:
        if ref is not None or status or json_:
            _err(
                "--commit takes no plan, --status, or --json; it commits what changed."
            )
            raise typer.Exit(1)
        _review_commit(root, allow_branch=allow_branch)
        return
    if allow_branch:
        _err("--allow-branch applies to --commit only.")
        raise typer.Exit(1)

    plans_dir = root / PLANS_DIR
    statuses = review_mod.DEFAULT_STATUSES
    if status:
        values = [value.strip() for value in status]
        if "all" in values:
            if len(values) > 1:
                _err("--status all cannot be combined with other statuses.")
                raise typer.Exit(1)
            statuses = tuple(Status)
        else:
            try:
                statuses = tuple(dict.fromkeys(Status(value) for value in values))
            except ValueError:
                allowed = ", ".join(["all", *(s.value for s in Status)])
                _err(f"invalid --status {status!r}; use one of: {allowed}.")
                raise typer.Exit(1) from None

    only: str | None = None
    if ref is not None:
        if status:
            _err("pass a plan or --status, not both.")
            raise typer.Exit(1)
        found = _resolve_ref(plans_dir, ref)
        if found.nested is not None:
            _warn(
                f"note: {found.label} is a nested subplan; reviewing its umbrella, "
                "whose evidence covers it."
            )
        only = found.plan.parent.name.split("-", 1)[0]

    mainline = base_mod.detect(root)
    try:
        report = review_mod.gather(
            root,
            plans_dir,
            statuses=statuses,
            only=only,
            stale_days=stale_days,
            now=_now(),
            mainline=mainline.branches[0] if mainline.resolved else None,
        )
    except review_mod.ReviewError as exc:
        _err(f"error: {exc}")
        raise typer.Exit(1) from None

    if json_:
        typer.echo(json.dumps(asdict(report), indent=2))
    else:
        typer.echo(review_mod.render_text(report), nl=False)


@app.command()
def base(
    repo_path: Path = typer.Argument(Path("."), help="Repo root (a git worktree)."),
    all_: bool = typer.Option(
        False,
        "--all",
        help="Print every detected mainline branch, one per line, in resolution "
        "order (default: only the first).",
    ),
) -> None:
    """Print the repo's mainline branch(es) — where plan commits belong.

    One detection implementation, shared by the ``add``/``finalize`` guard and by
    the lifecycle skills, so the convention is not re-described in prose that can
    drift from the code. Exits non-zero and prints nothing to stdout when no
    mainline resolves, so a script can branch on it.

    This reports what git's refs say *now*; it is not a record of where a repo's
    existing plans were actually committed. See :func:`planners.base.detect`.
    """
    mainline = base_mod.detect(repo_path)

    if mainline.unborn:
        _err(
            "no commits yet, so no mainline branch exists; the first plan can be "
            "added on whatever branch this repo starts on."
        )
        raise typer.Exit(1)
    if not mainline.resolved:
        _err(
            "could not determine a mainline branch: no 'dev', no "
            "refs/remotes/origin/HEAD, and no local 'main' or 'master'. Run `git "
            "remote set-head origin --auto` to record the remote's default "
            "branch, or pass --allow-branch to planners add."
        )
        raise typer.Exit(1)

    for name in mainline.branches if all_ else mainline.branches[:1]:
        typer.echo(name)

    if mainline.thin:
        _err(f"note: {base_mod.THIN_NOTE}")


@app.command()
def remote(
    repo_path: Path = typer.Argument(Path("."), help="Repo root (a git worktree)."),
    as_json: bool = typer.Option(
        False, "--json", help="Print the classification as a JSON object."
    ),
) -> None:
    """Print what kind of remote ``origin`` is and what the lifecycle does about it.

    The kind is one of github, single-branch, other-forge, bare, or none, read
    from the URL and config only; the remote is never contacted. Set
    ``git config planners.remoteKind <kind>`` to override the built-in host table.
    The lifecycle skills branch on this: a non-github kind skips the draft PR and
    closes through the no-PR path.
    """
    origin = remote_mod.classify(repo_path)
    if origin.note:
        _warn(f"warning: {origin.note}")
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": origin.kind.value,
                    "url": origin.url,
                    "host": origin.host,
                    "source": origin.source,
                    "effects": remote_mod.effects(origin.kind),
                },
                indent=2,
            )
        )
        return
    where = origin.host or origin.url or "no remote"
    typer.echo(f"origin: {origin.kind.value} ({where}; {origin.source})")
    for line in remote_mod.effects(origin.kind):
        typer.echo(f"  {line}")


@app.command()
def index(
    repo_path: Path = typer.Argument(
        Path("."), help="Repo root (contains .planners/)."
    ),
    cols: str = typer.Option("curated", "--cols", help="Column set: curated | all."),
) -> None:
    """Regenerate <repo>/.planners/README.md (title + plans table) from frontmatter."""
    if cols not in INDEX_COLS:
        _err(f"--cols must be 'curated' or 'all', got {cols!r}")
        raise typer.Exit(1)
    readme = _refresh_index(repo_path, cols=cols)
    typer.echo(f"updated {readme}")


@app.command()
def schema(
    model: str | None = typer.Argument(
        None, help="Schema model name (default: PlanMetadata)."
    ),
    list_models: bool = typer.Option(
        False, "--list", help="List available schema models."
    ),
) -> None:
    """Print the plan metadata schema with per-field descriptions."""
    if list_models:
        typer.echo("PlanMetadata")
        return
    if model not in (None, "PlanMetadata"):
        _err(f"unknown schema model: {model!r}; only 'PlanMetadata' is defined.")
        raise typer.Exit(1)
    typer.echo("PlanMetadata — plan-file frontmatter schema\n")
    for doc in PlanMetadata.schema():
        typer.echo(f"  {doc.name:<10} {doc.type:<12} {doc.description}")


def _subplan_violations(plan: Path) -> list[str]:
    """Every rule the nested subplans under ``plan``'s directory break.

    Stricter than :func:`_subplan_files` about names: here a markdown file that is
    not ``<letter>-<step>.md`` is a violation, because opting in to the check is
    saying the directory holds subplans and nothing else.
    """
    directory = plan.parent / SUBPLANS_DIRNAME
    if not directory.is_dir():
        return []
    found: list[str] = []
    metas: list[SubplanMetadata] = []
    for child in sorted(directory.iterdir()):
        if not child.is_file() or child.suffix != ".md":
            continue
        try:
            meta = SubplanMetadata.from_text(
                child.read_text(encoding="utf-8"), child.name
            )
        except (SubplanError, OSError, UnicodeDecodeError) as exc:
            found.append(f"{child}: {exc}")
            continue
        metas.append(meta)
        found.extend(f"{child}: {error}" for error in meta.validate())
    found.extend(f"{directory}: {error}" for error in subplans_mod.check_set(metas))
    return found


def _echo_validate_json(
    records: list[dict[str, object]],
    subplan_errors: list[str],
    stale_index: list[str],
    *,
    ok: bool,
) -> None:
    """Print ``validate --json``'s document on stdout."""
    document = {
        "ok": ok,
        "plans": records,
        "subplan_errors": subplan_errors,
        "stale_index": stale_index,
    }
    typer.echo(json.dumps(document, indent=2, ensure_ascii=False))


@app.command()
def validate(
    paths: list[Path] | None = typer.Argument(
        None,
        help="Plan files, a plans directory, or a repo root (default: the current "
        "directory).",
    ),
    subplans_: bool = typer.Option(
        False,
        "--subplans",
        help="Also check the frontmatter of each plan's nested subplans. Off by "
        "default, so a plan with free-form files under subplans/ keeps passing.",
    ),
    allow_empty: bool = typer.Option(
        False,
        "--allow-empty",
        help="Treat a zero-file match as a pass (warn only) instead of the "
        "default nonzero exit — for scripts that tolerate an empty plan set.",
    ),
    no_index: bool = typer.Option(
        False,
        "--no-index",
        help="Skip the stale-index comparison and check frontmatter alone — for "
        "a caller validating plans in a repo whose index it cannot regenerate.",
    ),
    json_: bool = typer.Option(
        False,
        "--json",
        help="Print each plan's parsed frontmatter and violations as JSON on "
        "stdout, for a caller that reads plans without importing planners. The "
        "exit code is unchanged.",
    ),
) -> None:
    """Validate plan frontmatter; exit non-zero on any violation or no match.

    A directory argument is resolved by :func:`_resolve_dir_plans` — a named plan
    dir, a repo root with a ``.planners/plans`` tree, or a plain container — so
    ``validate .`` from a checkout discovers its plans. Matching **zero** files is
    a failure by default (the vacuous-pass bug: a script asserting on the exit
    code would otherwise green-light a repo whose plans were never examined);
    ``--allow-empty`` opts back into the old warn-and-pass.

    With no argument the current directory is validated. A missing argument used
    to be a usage error, which in a chained command reads as the check having run.

    The repo's ``.planners/README.md`` must also match a fresh render of the
    frontmatter; ``--no-index`` skips that comparison and checks frontmatter
    alone, for a caller validating plans in a repo whose index it cannot
    regenerate.

    ``--json`` replaces the human-readable report with one JSON document: each
    plan's ``path``, its parsed ``plan`` record (``null`` when the frontmatter
    does not parse), and its ``errors``, plus ``subplan_errors``, ``stale_index``,
    and an overall ``ok`` that agrees with the exit code. A plan that parses but
    breaks a rule still carries its record, so a reader can index plans it would
    not accept.
    """
    files: list[Path] = []
    for p in paths or [Path(".")]:
        if p.is_dir():
            found = _resolve_dir_plans(p)
            if not found:
                # Name the empty directory so a mistaken target (e.g. `.planners`
                # instead of `.planners/plans`) is visible, not a silent skip.
                _err(f"no plans found under {p}")
            files.extend(found)
        else:
            # An explicitly named file is always validated (and flagged if it
            # isn't a conformant plan).
            files.append(p)

    if not files:
        if json_:
            _echo_validate_json([], [], [], ok=allow_empty)
        if allow_empty:
            if not json_:
                typer.echo("ok: 0 file(s) — no plans to validate (--allow-empty)")
            return
        _err(
            "no plan files matched; nothing was validated. Point at a repo root, a "
            "plans directory, or plan files — or pass --allow-empty to permit an "
            "empty match."
        )
        raise typer.Exit(1)

    # In JSON mode the violations go into the document instead of stderr.
    report = (lambda _message: None) if json_ else _err
    failures = 0
    records: list[dict[str, object]] = []
    for path in files:
        try:
            meta = PlanMetadata.from_file(path)
        except (PlanError, OSError, UnicodeDecodeError) as exc:
            report(f"{path}: {exc}")
            failures += 1
            records.append({"path": str(path), "plan": None, "errors": [str(exc)]})
            continue
        errors = meta.validate()
        for error in errors:
            report(f"{path}: {error}")
        failures += len(errors)
        records.append({"path": str(path), "plan": meta.to_record(), "errors": errors})

    subplan_errors: list[str] = []
    if subplans_:
        for path in files:
            for error in _subplan_violations(path):
                report(error)
                subplan_errors.append(error)
                failures += 1

    # The index is generated from exactly the frontmatter just validated, so a
    # disagreement between them is a violation of the same contract — and this is
    # the only gate that sees it. `finalize` self-checks its own batch, and the
    # lifecycle commands refresh the index in the commit that changes a plan; what
    # is left uncovered is a hand-edited plan and a merge, which is most of the
    # ways an index actually goes stale.
    # An *absent* index is deliberately not a violation here, though it is one for
    # `finalize` (which just wrote it, so absence means the write failed).
    # ``validate`` checks that two artifacts agree; whether a repo has an index at
    # all is `install`'s and `add`'s business, and failing on its absence would
    # break a checkout that simply has not generated one yet.
    # Roots are deduplicated *before* the staleness test, not after: every file in
    # a batch resolves to the same root, and each `_index_is_stale` call re-parses
    # every plan in the repo. Filtering first made a single `validate .` quadratic
    # in the plan count and repeated `_collect_metas`'s skip-warnings once per
    # file, so one malformed plan read as many.
    # ``--no-index`` keeps the frontmatter gate and drops the index comparison:
    # a caller validating plans in a repo it does not maintain cannot be failed on
    # that repo's index hygiene, and has no way to regenerate it.
    stale: list[Path] = []
    if not no_index:
        roots = {root for root in map(_repo_root_of, files) if root is not None}
        stale = sorted(
            root
            for root in roots
            if (root / INDEX_PATH).is_file() and _index_is_stale(root)
        )
    for root in stale:
        report(
            f"{root / INDEX_PATH}: stale — it does not match a fresh render of "
            "the plan frontmatter; run `planners index .` to regenerate it."
        )

    if json_:
        stale_paths = [str(root / INDEX_PATH) for root in stale]
        ok = not (failures or stale)
        _echo_validate_json(records, subplan_errors, stale_paths, ok=ok)
        if not ok:
            raise typer.Exit(1)
        return

    if failures or stale:
        # One summary covering both kinds of failure. A stale-index-only run is a
        # failure like any other and says so; leaving it summary-less made the
        # exit code the only signal.
        summary = []
        if failures:
            summary.append(f"{failures} violation(s) across {len(files)} file(s)")
        if stale:
            summary.append(f"{len(stale)} stale index file(s)")
        _err("; ".join(summary))
        raise typer.Exit(1)
    typer.echo(f"ok: {len(files)} file(s) valid")


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(app())  # pragma: no cover
