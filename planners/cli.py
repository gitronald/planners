"""planners CLI — the documented entry point for the plan-file lifecycle.

Commands: ``add``, ``finalize``, ``activate``, ``set-pr``, ``retire``,
``subplans``, ``base``, ``index``, ``schema``, and ``validate``, plus ``skill``,
``rule``, ``install``, and ``permissions``, which
:func:`pkgskills.register` mounts from :data:`planners.host.HOST`. Filesystem and
subprocess (git) work is confined to this module and the ``add`` helpers; the
schema/index transforms stay pure. Every shell-out goes through
:mod:`planners.proc`, which pins it to an explicit repo root.
"""

import re
import secrets
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

import typer
from pkgskills import register

from planners import base as base_mod
from planners import proc
from planners import subplans as subplans_mod
from planners.body import append_to_section, set_frontmatter_key
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
from planners.utils import is_safe_slug, parse_frontmatter, split_frontmatter

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
    if not value:
        return (1, 0.0)
    from datetime import datetime

    try:
        return (0, datetime.fromisoformat(value).timestamp())
    except ValueError:
        return (1, 0.0)


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
    try:
        meta = PlanMetadata.from_file(umbrella)
    except PlanError as exc:
        _err(f"cannot read {_shown(umbrella, root)}: {exc}")
        raise typer.Exit(1) from None
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

    _git(root, ["add", str(path.relative_to(root)), str(umbrella.relative_to(root))])
    _git(root, ["commit", "-m", f"plan [add]: {meta.prefix}{letter} - {slug}"])


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
        plan_id, sub = next_number([m.id for m in existing]), ""
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
    _git(root, ["add", str(path.relative_to(root)), str(readme.relative_to(root))])
    _git(root, ["commit", "-m", f"plan [add]: {prefix} - {slug}"])


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
    existing = _collect_metas(plans_dir, strict=False)
    start_id = next_number([m.id for m in existing])

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
    _git(root, ["commit", "-m", message])
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
    """Flip a plan to active, fill its branch, refresh the index, and commit.

    The activation commit belongs on the mainline, *before* the feature branch
    exists, so the plan is recorded there even if the branch never lands. That
    ordering was previously prose in two skills instructing a hand-edit of the
    frontmatter — which is why the ``plan [activate]`` subjects in this repo's own
    history disagree with each other, and why no guard could cover the step. Both
    problems are the same problem: there was no code to put them in.
    """
    root = Path.cwd()

    # Resolve and validate before the branch guard, the ordering `add` uses for its
    # slug check. A closed plan is closed on every branch, so leading with the branch
    # would send the user to switch branches and only then learn the real blocker.
    path = _resolve_plan(root / PLANS_DIR, ref)
    try:
        meta = PlanMetadata.from_file(path)
    except PlanError as exc:
        _err(f"cannot read {_shown(path, root)}: {exc}")
        raise typer.Exit(1) from None

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
    # no commit, so there is nothing for a branch to strand.
    if not no_commit:
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
        meta.status = Status.active
        meta.branch = new_branch
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
    _git(root, ["commit", "-m", f"plan [activate]: {meta.prefix} - {meta.slug}"])
    typer.echo(f"committed the activation on {_current_branch(root)}")


def _current_branch(root: Path) -> str:
    """The branch HEAD is on, in words fit for a message."""
    return base_mod.detect(root).current or "a detached HEAD"


def _head_authored(root: Path) -> str | None:
    """The authored date of ``HEAD`` as ISO-8601, or ``None`` when there is none."""
    try:
        result = proc.run(
            root, ["git", "log", "-1", "--format=%aI"], capture_output=True
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


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
    """Record a plan's PR URL, refresh the index, and commit.

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
        try:
            meta = PlanMetadata.from_file(plan)
        except PlanError as exc:
            _err(f"cannot read {_shown(plan, root)}: {exc}")
            raise typer.Exit(1) from None
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
        target.write_text(updated, encoding="utf-8")
        typer.echo(f"recorded {url} in {_shown(target, root)}")

    if no_commit:
        return

    if nested is None:
        staged.append(_refresh_index(root, cols="curated"))
    _git(root, ["add", *(str(path.relative_to(root)) for path in staged)])
    _git(root, ["commit", "-m", f"plan [pr]: {label} - {slug}"])


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
        try:
            meta = PlanMetadata.from_file(plan)
        except PlanError as exc:
            _err(f"cannot read {_shown(plan, root)}: {exc}")
            raise typer.Exit(1) from None
        if meta.status in CLOSED_STATUSES:
            _err(f"plan {meta.prefix} is {meta.status}; it is closed.")
            raise typer.Exit(1)
        # An umbrella does not close over unfinished subplans, by either door:
        # `close` checks it with `subplans --require-closed`, and this is the
        # same check for the plan that is retired instead.
        unfinished = [
            f"{sub.letter} ({sub.status.value})"
            for sub in _load_subplans(plan)[0]
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
    _git(root, ["add", *(str(path.relative_to(root)) for path in staged)])
    _git(root, ["commit", "-m", f"plan [retire]: {label} - {slug}"])


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
        help="Exit non-zero when a subplan is draft, active, or blocked: the check "
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
        help="Check frontmatter only; skip the stale-index comparison. For a "
        "caller that reads plans from repos it does not maintain, where "
        "another repo's unregenerated index is not its violation to fix.",
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
        if allow_empty:
            typer.echo("ok: 0 file(s) — no plans to validate (--allow-empty)")
            return
        _err(
            "no plan files matched; nothing was validated. Point at a repo root, a "
            "plans directory, or plan files — or pass --allow-empty to permit an "
            "empty match."
        )
        raise typer.Exit(1)

    failures = 0
    for path in files:
        try:
            meta = PlanMetadata.from_file(path)
        except PlanError as exc:
            _err(f"{path}: {exc}")
            failures += 1
            continue
        errors = meta.validate()
        for error in errors:
            _err(f"{path}: {error}")
        failures += len(errors)

    if subplans_:
        for path in files:
            for error in _subplan_violations(path):
                _err(error)
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
    # an aggregator validating another repo's plans has no business failing on
    # that repo's index hygiene, and no way to regenerate it.
    roots = (
        set()
        if no_index
        else {root for root in map(_repo_root_of, files) if root is not None}
    )
    stale = sorted(
        root
        for root in roots
        if (root / INDEX_PATH).is_file() and _index_is_stale(root)
    )
    for root in stale:
        _err(
            f"{root / INDEX_PATH}: stale — it does not match a fresh render of "
            "the plan frontmatter; run `planners index .` to regenerate it."
        )

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
