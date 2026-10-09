"""Evidence for ``planners review``: what changed in the repo around each plan.

A plan goes stale without anyone deciding it should. A draft can be done by a
later plan, half done as a side effect, or rest on files that have since been
deleted. Judging that takes reading, which is the ``review`` skill's job. This
module does the part that is mechanical: for each selected plan it gathers the
commits since the plan was created (or last reviewed), the code the plan names
and whether it still exists, the other plans it names and their status, and,
for an open plan someone may be working on, the state of its branch.

Everything here is **read-only**. Nothing is written, committed, fetched, or
checked out. A missing ``gh``, a missing remote, or a shallow clone turns the
matching field into ``None`` (reported as ``unknown``), never into an error.

The one write the review makes, the commit of the skill's Log entries, is in
the CLI (``review --commit``) with the other lifecycle commits.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from planners import proc
from planners.body import fenced_lines, section_span
from planners.index import STATUS_ORDER
from planners.metadata import (
    CLOSED_STATUSES,
    DIRNAME_RE,
    PlanError,
    PlanMetadata,
    Status,
)
from planners.subplans import UNFINISHED_STATUSES, SubplanMetadata
from planners.utils import split_frontmatter

__all__ = [
    "DEFAULT_STATUSES",
    "BranchState",
    "CodeRef",
    "Commit",
    "OpenSubplans",
    "PlanEvidence",
    "PlanRef",
    "PrState",
    "Report",
    "ReviewError",
    "SummaryRow",
    "Tag",
    "extract_code_refs",
    "extract_plan_refs",
    "gather",
    "last_review",
    "render_text",
]

# The open statuses, reviewed when no --status is given. `inactive` is parked,
# and the closed ones are reviewed only for drift, when asked for.
DEFAULT_STATUSES = (Status.active, Status.draft, Status.blocked)

# Plans someone may be working on right now, judged from their branch and only
# ever reported on, never edited.
CAREFUL_STATUSES = frozenset({Status.active, Status.blocked})

# The tool-written subjects, which say a plan file moved, not that the repo did.
_TOOL_SUBJECT_RE = re.compile(r"^(plan|version) \[")
# A commit that touches only plan files is a plan being written, not the repo
# changing under it, so the evidence window lists only commits reaching past
# `.planners/`. The other plans' moves are covered by the plans the body names.
_OUTSIDE_PLANS = (".", ":(exclude).planners")

# A review's Log entry opens with this marker, which the next review reads as
# the start of its evidence window. The skill writes it; nothing here does.
_MARKER_RE = re.compile(r"^\s*- \*\*([^*]+)\*\* — Review: ([a-z][a-z ]*)\.")

_PLAN_REF_RE = re.compile(r"\b[Pp]lans? (\d{3}[a-z]?)\b")
_SPAN_RE = re.compile(r"`([^`]+)`")
_SYMBOL_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
# Characters that mark a span as a command, a placeholder, or a pattern rather
# than a path in the tree.
_NOT_A_PATH = set(" <>{}[]*$=()'\"|,;?!@#%^&+")
# File suffixes that make a span with no slash a path (`cli.py`) rather than a
# dotted symbol.
_SUFFIXES = frozenset(
    {
        ".cfg",
        ".css",
        ".csv",
        ".go",
        ".html",
        ".ini",
        ".ipynb",
        ".js",
        ".json",
        ".lock",
        ".md",
        ".py",
        ".r",
        ".rs",
        ".sh",
        ".sql",
        ".tex",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
)

_US = "\x1f"
_RS = "\x1e"


class ReviewError(ValueError):
    """A repo ``review`` cannot report on at all, such as the legacy layout."""


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    subject: str


@dataclass(frozen=True)
class Tag:
    name: str
    date: str


@dataclass(frozen=True)
class CodeRef:
    """One path or ``module.function`` the plan names, checked against the tree.

    ``state`` is ``present``, ``missing``, or ``unresolved`` (a dotted name whose
    module is not a file in the tree, so it may not be code at all). ``changed``
    lists the commits that touched ``path`` in the evidence window, and is
    ``None`` when history cannot say (a shallow clone).
    """

    ref: str
    kind: str
    state: str
    path: str | None = None
    detail: str = ""
    changed: list[str] | None = None


@dataclass(frozen=True)
class PlanRef:
    ref: str
    status: str | None


@dataclass(frozen=True)
class PrState:
    state: str
    url: str = ""


@dataclass
class BranchState:
    """Where an open plan's branch stands. ``None`` fields are ``unknown``."""

    name: str
    local: bool
    remote: bool | None
    tip: str | None
    ahead: int | None
    last_commit: str | None
    idle_days: int | None
    worktree: str | None
    dirty: bool | None


@dataclass
class PlanEvidence:
    prefix: str
    slug: str
    title: str
    status: str
    path: str
    created: str
    concluded: str | None
    branch: str | None
    pr: str | None
    last_reviewed: str | None
    window_start: str
    evidence_rev: str
    commits: list[Commit] | None
    tags: list[Tag]
    code_refs: list[CodeRef]
    plan_refs: list[PlanRef]
    subplans: list[dict[str, str]]
    branch_state: BranchState | None
    pr_state: PrState | None
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryRow:
    status: str
    plans: int
    commits: int | None
    creation_date: str | None
    closed_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class OpenSubplans:
    plan: str
    open: int
    total: int


@dataclass
class Report:
    now: str
    mainline: str
    stale_days: int
    selected: list[str]
    shallow: bool
    summary: list[SummaryRow]
    open_subplans: list[OpenSubplans]
    plans: list[PlanEvidence]


# --------------------------------------------------------------------------
# Pure helpers: reading a plan's body.


def last_review(body: str) -> str | None:
    """The timestamp of the newest ``Review: <verdict>.`` marker in the Log.

    Newest by instant, not by position, since a Log is appended to but a hand
    edit can land an entry out of order. ``None`` when the plan was never
    reviewed (or has no Log).
    """
    span = section_span(body, "Log")
    if span is None:
        return None
    lines = body.splitlines()[span[0] : span[1]]
    best: tuple[float, str] | None = None
    for line in lines:
        match = _MARKER_RE.match(line)
        if not match:
            continue
        stamp = match.group(1).strip()
        instant = _instant(stamp)
        if instant is None:
            continue
        if best is None or instant > best[0]:
            best = (instant, stamp)
    return best[1] if best else None


def _prose(body: str) -> str:
    """``body`` without its fenced code blocks, which hold commands, not claims."""
    lines = body.splitlines()
    fenced = fenced_lines([line + "\n" for line in lines])
    return "\n".join(line for line, inside in zip(lines, fenced) if not inside)


def _classify(span: str) -> tuple[str, str] | None:
    """``(kind, ref)`` for a code span that names a path or a symbol, else ``None``.

    Deliberately narrow (open question 2): a path has a slash or a known file
    suffix, and a symbol is a dotted ``module.function``. Bare names give too
    many false positives, so the skill finds those by hand.
    """
    text = span.strip()
    if text.endswith("()"):
        text = text[:-2]
    text = _LINE_SUFFIX_RE.sub("", text)
    if text.startswith("./"):
        text = text[2:]
    if not text or text.startswith(("-", "/", "~")) or "://" in text or ".." in text:
        return None
    if any(ch in _NOT_A_PATH for ch in text):
        return None
    suffix = Path(text.rstrip("/")).suffix
    if "/" in text or suffix in _SUFFIXES:
        return "path", text
    if _SYMBOL_RE.match(text):
        return "symbol", text
    return None


def extract_code_refs(body: str) -> list[tuple[str, str]]:
    """Every ``(kind, ref)`` the plan's inline code names, first mention first."""
    prose = _prose(body)
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for match in _SPAN_RE.finditer(prose):
        classified = _classify(match.group(1).replace("\n", " "))
        if classified is None or classified[1] in seen:
            continue
        seen.add(classified[1])
        found.append(classified)
    return found


def extract_plan_refs(body: str, own: str) -> list[str]:
    """The other plans the body names as ``plan NNN``, first mention first."""
    seen: list[str] = []
    for match in _PLAN_REF_RE.finditer(_prose(body)):
        ref = match.group(1)
        if ref != own and ref not in seen:
            seen.append(ref)
    return seen


def _instant(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _date(value: str | None) -> str | None:
    """The calendar date of an ISO-8601 timestamp, as written (no conversion)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Git, read-only.


class _Git:
    """Read-only git queries against one repo, with per-run caches."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._trees: dict[str, list[str]] = {}

    def out(self, args: list[str], cwd: Path | None = None) -> str | None:
        try:
            result = proc.run(cwd or self.root, ["git", *args], capture_output=True)
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def verify(self, ref: str) -> bool:
        return (
            self.out(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"]) is not None
        )

    def shallow(self) -> bool:
        return (self.out(["rev-parse", "--is-shallow-repository"]) or "").strip() == (
            "true"
        )

    def has_origin(self) -> bool:
        return "origin" in (self.out(["remote"]) or "").split()

    def tree(self, rev: str) -> list[str]:
        if rev not in self._trees:
            listing = self.out(
                ["-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", rev]
            )
            self._trees[rev] = (listing or "").splitlines()
        return self._trees[rev]

    def show(self, rev: str, path: str) -> str | None:
        return self.out(["show", f"{rev}:{path}"])

    def log(self, args: list[str]) -> list[Commit]:
        text = self.out(["log", f"--format={_RS}%h{_US}%aI{_US}%s", *args])
        commits: list[Commit] = []
        for record in (text or "").split(_RS):
            record = record.strip("\n")
            if not record:
                continue
            sha, _, rest = record.partition(_US)
            date, _, subject = rest.partition(_US)
            commits.append(
                Commit(
                    sha=sha,
                    date=date,
                    subject=subject.splitlines()[0] if subject else "",
                )
            )
        return commits


def _resolve_path(git: _Git, rev: str, ref: str) -> list[str]:
    """Tracked paths ``ref`` names at ``rev``: exact first, then by suffix."""
    tree = git.tree(rev)
    want = ref.rstrip("/")
    if ref.endswith("/"):
        prefix = want + "/"
        if any(p.startswith(prefix) for p in tree):
            return [want]
        tail = "/" + prefix
        dirs = sorted({p[: p.index(tail) + len(tail) - 1] for p in tree if tail in p})
        return dirs
    if want in tree:
        return [want]
    if any(p.startswith(want + "/") for p in tree):
        return [want]
    return [p for p in tree if p.endswith("/" + want)]


def _defines(text: str, name: str) -> bool:
    pattern = re.compile(
        rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b|^{re.escape(name)}\s*[:=]",
        re.MULTILINE,
    )
    return bool(pattern.search(text))


def _check_ref(
    git: _Git, rev: str, kind: str, ref: str, since: str, shallow: bool
) -> CodeRef:
    def changed(path: str) -> list[str] | None:
        if shallow:
            return None
        return [c.sha for c in git.log([f"--since={since}", rev, "--", path])]

    if kind == "path":
        hits = _resolve_path(git, rev, ref)
        if not hits:
            return CodeRef(ref=ref, kind=kind, state="missing")
        detail = f"also matches {', '.join(hits[1:])}" if len(hits) > 1 else ""
        return CodeRef(
            ref=ref,
            kind=kind,
            state="present",
            path=hits[0],
            detail=detail,
            changed=changed(hits[0]),
        )

    parts = ref.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module = "/".join(parts[:cut])
        for candidate in (f"{module}.py", f"{module}/__init__.py"):
            hits = _resolve_path(git, rev, candidate)
            if not hits:
                continue
            path = hits[0]
            text = git.show(rev, path) or ""
            names = parts[cut:]
            missing = [
                name for name in (names[0], names[-1]) if not _defines(text, name)
            ]
            if missing:
                return CodeRef(
                    ref=ref,
                    kind=kind,
                    state="missing",
                    path=path,
                    detail=f"no `{missing[0]}` defined in {path}",
                    changed=changed(path),
                )
            return CodeRef(
                ref=ref, kind=kind, state="present", path=path, changed=changed(path)
            )
    return CodeRef(
        ref=ref, kind=kind, state="unresolved", detail="no module file in the tree"
    )


def _worktrees(git: _Git) -> dict[str, str]:
    """``branch name -> worktree path`` from ``git worktree list --porcelain``."""
    found: dict[str, str] = {}
    path: str | None = None
    for line in (git.out(["worktree", "list", "--porcelain"]) or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("branch refs/heads/") and path is not None:
            found[line[len("branch refs/heads/") :]] = path
    return found


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _pr_state(root: Path, target: str, *, enabled: bool) -> PrState | None:
    """The PR's state from ``gh``, or ``None`` when it cannot be asked."""
    if not enabled:
        return None
    try:
        result = proc.run(
            root,
            ["gh", "pr", "view", target, "--json", "state,url"],
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return PrState(
        state=str(data.get("state", "")).lower() or "unknown",
        url=str(data.get("url", "")),
    )


# --------------------------------------------------------------------------
# Gathering.


@dataclass
class _Plan:
    meta: PlanMetadata
    path: Path
    body: str
    subplans: list[SubplanMetadata]


def _load(root: Path, plans_dir: Path) -> list[_Plan]:
    plans: list[_Plan] = []
    if not plans_dir.is_dir():
        return plans
    for child in sorted(plans_dir.iterdir()):
        plan = child / "plan.md"
        if not (child.is_dir() and DIRNAME_RE.match(child.name) and plan.is_file()):
            continue
        text = plan.read_text(encoding="utf-8")
        try:
            meta = PlanMetadata.from_text(text, dirname=child.name)
        except PlanError:
            continue
        _, body = split_frontmatter(text)
        subs: list[SubplanMetadata] = []
        sub_dir = child / "subplans"
        if sub_dir.is_dir():
            for sub in sorted(sub_dir.iterdir()):
                try:
                    subs.append(
                        SubplanMetadata.from_text(
                            sub.read_text(encoding="utf-8"), sub.name
                        )
                    )
                except (ValueError, OSError, UnicodeDecodeError):
                    continue
        plans.append(
            _Plan(meta=meta, path=plan.relative_to(root), body=body, subplans=subs)
        )
    return plans


def _check_layout(root: Path, plans_dir: Path) -> None:
    if plans_dir.is_dir():
        return
    if (root / "docs" / "plans").is_dir() or (root / "TODO.md").is_file():
        raise ReviewError(
            "this repo is on the legacy docs/plans/ + TODO.md layout; `review` "
            "reads only .planners/. Migrate the plans to "
            ".planners/plans/<NNN>-<slug>/plan.md first."
        )
    raise ReviewError(f"no plans directory at {plans_dir.relative_to(root)}.")


def _summary(git: _Git, plans: list[_Plan], shallow: bool) -> list[SummaryRow]:
    """One row per status present, in the index's order, then a total.

    ``commits`` counts distinct commits that touched the plans' directories,
    merges left out: a merge changes a directory only by bringing in commits
    that are counted already, and with several directories in one pathspec git
    shows merges it would hide for each alone. The
    total row counts distinct commits across every plan directory, so a commit
    touching plans in two statuses is counted once there, and the total can be
    less than the column's sum.
    """

    def row(status: str, group: list[_Plan]) -> SummaryRow:
        dirs = [p.path.parent.as_posix() for p in group]
        commits: int | None = None
        last: str | None = None
        if not shallow:
            found: list[Commit] = (
                git.log(["--no-merges", "HEAD", "--", *dirs])
                if git.verify("HEAD")
                else []
            )
            commits = len({c.sha for c in found})
            newest = max(found, key=lambda c: _instant(c.date) or 0.0, default=None)
            last = _date(newest.date) if newest else None
        created = [
            p.meta.created for p in group if _instant(p.meta.created) is not None
        ]
        concluded = [
            p.meta.concluded for p in group if _instant(p.meta.concluded) is not None
        ]
        return SummaryRow(
            status=status,
            plans=len(group),
            commits=commits,
            creation_date=_date(min(created, key=lambda v: _instant(v) or 0.0))
            if created
            else None,
            closed_date=_date(max(concluded, key=lambda v: _instant(v) or 0.0))
            if concluded
            else None,
            last_date=last,
        )

    rows = [
        row(status.value, group)
        for status in STATUS_ORDER
        if (group := [p for p in plans if p.meta.status == status])
    ]
    if plans:
        rows.append(row("total", plans))
    return rows


def _status_lookup(plans: list[_Plan]) -> dict[str, str]:
    """``NNN[x] -> status`` for every plan and every nested subplan."""
    found: dict[str, str] = {}
    for plan in plans:
        found[plan.meta.prefix] = plan.meta.status.value
        for sub in plan.subplans:
            found.setdefault(f"{plan.meta.prefix}{sub.letter}", sub.status.value)
    return found


def _branch_state(
    git: _Git, plan: _Plan, mainline: str, now: datetime, worktrees: dict[str, str]
) -> BranchState | None:
    name = plan.meta.branch
    if not name:
        return None
    local = git.verify(f"refs/heads/{name}")
    remote: bool | None = (
        git.verify(f"refs/remotes/origin/{name}") if git.has_origin() else None
    )
    tip = name if local else (f"origin/{name}" if remote else None)

    ahead: int | None = None
    last: str | None = None
    if tip is not None:
        count = git.out(["rev-list", "--count", f"{mainline}..{tip}"])
        ahead = int(count.strip()) if count and count.strip().isdigit() else None
        branch_commits = git.log(["-1", f"{mainline}..{tip}"])
        if branch_commits:
            last = branch_commits[0].date
    if last is None:
        touched = git.log(["-1", "HEAD", "--", plan.path.parent.as_posix()])
        last = touched[0].date if touched else None

    idle: int | None = None
    if last is not None:
        try:
            idle = (now - datetime.fromisoformat(last)).days
        except (ValueError, TypeError):
            idle = None

    worktree = worktrees.get(name)
    dirty: bool | None = None
    if worktree is not None:
        status = git.out(["status", "--porcelain"], cwd=Path(worktree))
        dirty = None if status is None else bool(status.strip())
    return BranchState(
        name=name,
        local=local,
        remote=remote,
        tip=tip,
        ahead=ahead,
        last_commit=last,
        idle_days=idle,
        worktree=worktree,
        dirty=dirty,
    )


def _flags(evidence: PlanEvidence, mainline: str, stale_days: int) -> list[str]:
    """Observations worth a look. Never a reason to act on their own."""
    flags: list[str] = []
    status = Status(evidence.status)
    state = evidence.branch_state
    if status in CAREFUL_STATUSES:
        if not evidence.branch:
            flags.append(f"{status.value} plan with no branch recorded")
        elif state is not None and not state.local and not state.remote:
            where = "locally" if state.remote is None else "locally or on origin"
            flags.append(f"branch {state.name} does not exist {where}")
        if state is not None:
            if state.ahead == 0:
                flags.append(f"branch {state.name} has no commits ahead of {mainline}")
            if state.idle_days is not None and state.idle_days >= stale_days:
                flags.append(
                    f"no commits for {state.idle_days} days (threshold {stale_days})"
                )
            if state.dirty:
                flags.append(
                    f"worktree {state.worktree} has uncommitted changes (in progress)"
                )
        if evidence.pr_state is not None and evidence.pr_state.state == "merged":
            flags.append(f"PR is merged but the plan is still {status.value}")
    if status in CLOSED_STATUSES:
        if evidence.pr_state is not None and evidence.pr_state.state != "merged":
            flags.append(
                f"pr points at a PR that is {evidence.pr_state.state}, not merged"
            )
    for ref in evidence.plan_refs:
        if ref.status is None:
            flags.append(f"names plan {ref.ref}, which does not exist")
    return flags


def gather(
    root: Path,
    plans_dir: Path,
    *,
    statuses: tuple[Status, ...] = DEFAULT_STATUSES,
    only: str | None = None,
    stale_days: int = 14,
    now: str,
    mainline: str | None = None,
    gh: bool | None = None,
) -> Report:
    """Build the review report for ``root``. Reads only.

    ``only`` is a plan prefix (``011``, ``010a``) that selects one plan whatever
    its status. ``mainline`` defaults to ``HEAD``; the CLI passes the detected
    mainline branch. ``gh`` defaults to whether the binary is on PATH (and is
    used only when the repo has an ``origin`` remote).
    """
    _check_layout(root, plans_dir)
    git = _Git(root)
    rev = mainline if mainline and git.verify(mainline) else "HEAD"
    shallow = git.shallow()
    use_gh = (_gh_available() if gh is None else gh) and git.has_origin()
    clock = datetime.fromisoformat(now)

    plans = _load(root, plans_dir)
    lookup = _status_lookup(plans)
    worktrees = _worktrees(git)

    if only is not None:
        selected = [p for p in plans if p.meta.prefix == only]
    else:
        wanted = set(statuses)
        selected = [p for p in plans if p.meta.status in wanted]
    rank = {status: i for i, status in enumerate(STATUS_ORDER)}
    selected.sort(
        key=lambda p: (rank.get(p.meta.status, len(rank)), p.meta.id, p.meta.sub)
    )

    evidence: list[PlanEvidence] = []
    for plan in selected:
        meta = plan.meta
        reviewed = last_review(plan.body)
        start = reviewed or meta.created
        careful = meta.status in CAREFUL_STATUSES
        state = _branch_state(git, plan, rev, clock, worktrees) if careful else None
        evidence_rev = state.tip if state is not None and state.tip else rev

        commits: list[Commit] | None = None
        tags: list[Tag] = []
        if not shallow and _instant(start) is not None:
            commits = [
                c
                for c in git.log([f"--since={start}", rev, "--", *_OUTSIDE_PLANS])
                if not _TOOL_SUBJECT_RE.match(c.subject)
            ]
            listing = git.out(
                [
                    "for-each-ref",
                    "--merged",
                    rev,
                    f"--format=%(refname:short){_US}%(creatordate:iso-strict)",
                    "refs/tags",
                ]
            )
            since = _instant(start) or 0.0
            for line in (listing or "").splitlines():
                name, _, date = line.partition(_US)
                if (_instant(date) or 0.0) >= since:
                    tags.append(Tag(name=name, date=date))

        code_refs = [
            _check_ref(git, evidence_rev, kind, ref, start, shallow)
            for kind, ref in extract_code_refs(plan.body)
        ]
        plan_refs = [
            PlanRef(ref=ref, status=lookup.get(ref))
            for ref in extract_plan_refs(plan.body, meta.prefix)
        ]

        pr_state: PrState | None = None
        if meta.pr:
            pr_state = _pr_state(root, meta.pr, enabled=use_gh)
        elif careful and meta.branch:
            pr_state = _pr_state(root, meta.branch, enabled=use_gh)

        item = PlanEvidence(
            prefix=meta.prefix,
            slug=meta.slug,
            title=meta.title,
            status=meta.status.value,
            path=plan.path.as_posix(),
            created=meta.created,
            concluded=meta.concluded,
            branch=meta.branch,
            pr=meta.pr,
            last_reviewed=reviewed,
            window_start=start,
            evidence_rev=evidence_rev,
            commits=commits,
            tags=tags,
            code_refs=code_refs,
            plan_refs=plan_refs,
            subplans=[
                {"letter": s.letter, "status": s.status.value, "file": s.filename}
                for s in plan.subplans
            ],
            branch_state=state,
            pr_state=pr_state,
        )
        item.flags = _flags(item, rev, stale_days)
        evidence.append(item)

    open_subplans = [
        OpenSubplans(
            plan=p.meta.prefix,
            open=sum(1 for s in p.subplans if s.status in UNFINISHED_STATUSES),
            total=len(p.subplans),
        )
        for p in plans
        if any(s.status in UNFINISHED_STATUSES for s in p.subplans)
    ]

    return Report(
        now=now,
        mainline=rev,
        stale_days=stale_days,
        selected=[p.meta.prefix for p in selected],
        shallow=shallow,
        summary=_summary(git, plans, shallow),
        open_subplans=open_subplans,
        plans=evidence,
    )


# --------------------------------------------------------------------------
# Text rendering.


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _unknown(value: object) -> str:
    return "unknown" if value is None else str(value)


def render_summary(report: Report) -> list[str]:
    header = ("status", "plans", "commits", "creation_date", "closed_date", "last_date")
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in report.summary:
        cells = [
            row.status,
            str(row.plans),
            _unknown(row.commits),
            _cell(row.creation_date),
            _cell(row.closed_date),
            _cell(row.last_date) if row.commits is not None else "unknown",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    for item in report.open_subplans:
        lines.append(f"{item.plan}: {item.open} of {item.total} subplans open")
    return lines


def _render_plan(item: PlanEvidence) -> list[str]:
    lines = [f"## {item.prefix} {item.title or item.slug} ({item.status})", ""]
    lines.append(f"path: {item.path}")
    lines.append(f"created: {item.created}")
    if item.concluded:
        lines.append(f"concluded: {item.concluded}")
    lines.append(f"last reviewed: {item.last_reviewed or 'never'}")
    lines.append(f"window: since {item.window_start}, judged at {item.evidence_rev}")
    if item.branch:
        lines.append(f"branch: {item.branch}")
    if item.pr:
        lines.append(f"pr: {item.pr}")

    if item.commits is None:
        lines.append("commits since: unknown (shallow clone)")
    else:
        lines.append(f"commits since: {len(item.commits)}")
        lines.extend(f"  {c.sha} {c.date[:10]} {c.subject}" for c in item.commits)
    if item.tags:
        lines.append(
            "tags since: " + ", ".join(f"{t.name} ({t.date[:10]})" for t in item.tags)
        )

    if item.code_refs:
        lines.append("code references:")
        for ref in item.code_refs:
            note = ref.state
            if ref.path and ref.path != ref.ref:
                note += f" at {ref.path}"
            if ref.changed is None and ref.state != "unresolved" and ref.path:
                note += ", changes unknown"
            elif ref.changed:
                shas = " ".join(ref.changed[:5])
                note += f", changed in {len(ref.changed)} commit(s): {shas}"
            if ref.detail:
                note += f" ({ref.detail})"
            lines.append(f"  `{ref.ref}` {note}")
    if item.plan_refs:
        lines.append(
            "plans named: "
            + ", ".join(f"{r.ref} ({r.status or 'not found'})" for r in item.plan_refs)
        )
    if item.subplans:
        lines.append(
            "subplans: "
            + ", ".join(f"{s['letter']} ({s['status']})" for s in item.subplans)
        )

    state = item.branch_state
    if state is not None:
        origin = None if state.remote is None else ("yes" if state.remote else "no")
        lines.append(
            f"branch state: local {'yes' if state.local else 'no'}, "
            f"origin {_unknown(origin)}, "
            f"ahead {_unknown(state.ahead)}, last commit {_unknown(state.last_commit)}"
        )
        if state.worktree:
            dirty = _unknown(
                None if state.dirty is None else ("dirty" if state.dirty else "clean")
            )
            lines.append(f"worktree: {state.worktree} ({dirty})")
    if item.pr_state is not None:
        lines.append(f"pr state: {item.pr_state.state} {item.pr_state.url}".rstrip())
    elif item.pr or (
        item.status in {s.value for s in CAREFUL_STATUSES} and item.branch
    ):
        lines.append("pr state: unknown")
    for flag in item.flags:
        lines.append(f"flag: {flag}")
    return lines


def render_text(report: Report) -> str:
    lines = [f"review at {report.now} against {report.mainline}", ""]
    lines.extend(render_summary(report))
    if report.shallow:
        lines += [
            "",
            "note: shallow clone; commit counts and change history are unknown.",
        ]
    if not report.plans:
        lines += ["", "no plans selected."]
    for item in report.plans:
        lines.append("")
        lines.extend(_render_plan(item))
    return "\n".join(lines) + "\n"
