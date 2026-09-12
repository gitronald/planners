"""planners CLI — the documented entry point for the plan-file lifecycle.

Commands: ``add``, ``finalize``, ``activate``, ``base``, ``index``, ``schema``,
``validate``, plus ``skill``, ``rule``, ``install``, and ``permissions``, which
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

import typer
from pkgskills import register

from planners import base as base_mod
from planners import proc
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


def _resolve_plan(plans_dir: Path, ref: str) -> Path:
    """Resolve a plan reference (``5``, ``005``, ``005a``) to its ``plan.md``.

    The reference names a number and an optional subplan letter; the slug is not
    part of it, so a retitled or re-slugged plan stays addressable by the number
    that identifies it. Matching is on the parsed ``(number, letter)`` pair rather
    than a string prefix, so ``5`` and ``005`` are the same plan while ``5`` never
    matches ``050-...``.

    Exits with a CLI error when the reference is malformed or matches no plan.
    """
    match = re.fullmatch(r"(\d+)([a-z]?)", ref.strip())
    if match is None:
        _err(f"not a plan reference: {ref!r}; use a number like 005 (or 005a).")
        raise typer.Exit(1)
    want_id, want_sub = int(match.group(1)), match.group(2)

    for plan in _plan_files(plans_dir):
        parts = DIRNAME_RE.match(plan.parent.name)
        if parts is None:  # unreachable: _plan_files filters on the same pattern
            continue
        if int(parts.group(1)) == want_id and parts.group(2) == want_sub:
            return plan

    _err(f"no plan {want_id:03d}{want_sub} found under {plans_dir}.")
    raise typer.Exit(1)


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
        help="Umbrella plan number; scaffold a lettered subplan (e.g. 010a) under it.",
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
        typer.echo(f"activated {_shown(path, root)} on {meta.branch}")

    if no_commit:
        return

    readme = _refresh_index(root, cols="curated")
    _git(root, ["add", str(path.relative_to(root)), str(readme.relative_to(root))])
    # The subject names the slug, not the title: a slug is fixed by the directory
    # name, while a title can be reworded until the subject no longer names the plan
    # it belongs to. Matches what `add` writes, and a format string owns it, so it
    # cannot drift the way the hand-written subjects did.
    _git(root, ["commit", "-m", f"plan [activate]: {meta.prefix} - {meta.slug}"])


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


@app.command()
def validate(
    paths: list[Path] = typer.Argument(
        ..., help="Plan files, a plans directory, or a repo root."
    ),
    allow_empty: bool = typer.Option(
        False,
        "--allow-empty",
        help="Treat a zero-file match as a pass (warn only) instead of the "
        "default nonzero exit — for scripts that tolerate an empty plan set.",
    ),
) -> None:
    """Validate plan frontmatter; exit non-zero on any violation or no match.

    A directory argument is resolved by :func:`_resolve_dir_plans` — a named plan
    dir, a repo root with a ``.planners/plans`` tree, or a plain container — so
    ``validate .`` from a checkout discovers its plans. Matching **zero** files is
    a failure by default (the vacuous-pass bug: a script asserting on the exit
    code would otherwise green-light a repo whose plans were never examined);
    ``--allow-empty`` opts back into the old warn-and-pass.
    """
    files: list[Path] = []
    for p in paths:
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
    roots = {root for root in map(_repo_root_of, files) if root is not None}
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
