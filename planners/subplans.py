"""Nested subplans: a plan split into files under its own ``subplans/`` directory.

    .planners/plans/NNN-<slug>/
      plan.md                  # the umbrella
      subplans/
        a-<step>.md            # one file per step
        b-<step>.md

A nested subplan carries a small frontmatter of its own (``status`` and
``branch``, plus the optional ``pr``, ``needs``, and ``moved_to``) and no ``id``
or ``sub``, so it stays out of the index and out of the default ``validate``.

**The subplan's frontmatter is the status of record.** The umbrella's table is
generated from it, between two marker comments, and only its Status column is
ever written. Two hand-kept copies drift, and the table is the one that gets
updated, because it is the one people read.

Everything here is a pure transform. The CLI does the reading and writing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from planners.body import fenced_lines, insert_after_first_subsection
from planners.metadata import Status, extract_title
from planners.utils import parse_frontmatter, split_frontmatter

__all__ = [
    "FIRST_STEP_LETTER",
    "SUBPLANS_DIRNAME",
    "TABLE_END",
    "TABLE_START",
    "UNFINISHED_STATUSES",
    "SubplanError",
    "SubplanMetadata",
    "check_set",
    "is_subplan_filename",
    "next_letter",
    "phases",
    "render_order",
    "render_subplan",
    "table_disagreements",
    "write_table",
]

SUBPLANS_DIRNAME = "subplans"

# <letter>-<step>.md. The letter is the subplan's identity inside its umbrella,
# as the number is a plan's. Groups: (letter, step).
FILENAME_RE = re.compile(r"^([a-z])-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")

# `a` is the investigation, reserved from the first split whether or not one is
# written yet. Making room for it later would shift every letter after it.
FIRST_STEP_LETTER = "b"

# The statuses an umbrella cannot close over: work that has not started, is in
# progress, or is waiting on someone. `inactive` is set aside, not unfinished.
UNFINISHED_STATUSES = frozenset({Status.draft, Status.active, Status.blocked})

TABLE_START = "<!-- planners:subplans:start -->"
TABLE_END = "<!-- planners:subplans:end -->"
TABLE_HEADER = ("Subplan", "Scope", "Status", "Note")

# Where a generated table goes when the umbrella has no table yet: near the top
# of the spec, after its opening subsection. An umbrella with no spec section at
# all gets it ahead of the record of what happened.
_SPEC = "Plan"
_AFTER_SPEC = ("Log", "Handoff", "Retrospective")

_PLAN_REF_RE = re.compile(r"^\d+[a-z]?$")
_LINK_RE = re.compile(r"^\[([^\]]*)\]\([^)]*\)$")
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


class SubplanError(ValueError):
    """A subplan file that cannot be read as a subplan at all."""


def is_subplan_filename(name: str) -> bool:
    """True when ``name`` is ``<letter>-<step>.md``."""
    return bool(FILENAME_RE.match(name))


def _parse_needs(fm_text: str) -> tuple[str, ...]:
    """The ``needs:`` list, from either YAML list form.

    ``needs: [a, b]`` and ``needs: a, b`` are read from the line itself. A bare
    ``needs:`` is followed by ``- a`` items, one per line, up to the next key.
    The flat frontmatter parser cannot see the second form, so it is read here.
    """
    lines = fm_text.splitlines()
    for i, raw in enumerate(lines):
        key, sep, value = raw.partition(":")
        if not sep or key.strip() != "needs" or raw.lstrip().startswith("#"):
            continue
        value = value.strip()
        if value and value.lower() != "null":
            inner = (
                value[1:-1] if value.startswith("[") and value.endswith("]") else value
            )
            items = [item.strip().strip("\"'") for item in inner.split(",")]
            return tuple(item for item in items if item)
        found: list[str] = []
        for later in lines[i + 1 :]:
            stripped = later.strip()
            if not stripped:
                continue
            if not stripped.startswith("-"):
                break
            item = stripped[1:].strip().strip("\"'")
            if item:
                found.append(item)
        return tuple(found)
    return ()


@dataclass
class SubplanMetadata:
    """A nested subplan's frontmatter, its letter, and its title.

    ``branch`` and ``pr`` keep the plan schema's empty-versus-``None``
    distinction. An empty ``branch`` means the umbrella's branch.
    """

    letter: str
    step: str
    status: Status
    branch: str | None = ""
    pr: str | None = ""
    needs: tuple[str, ...] = ()
    moved_to: str = ""
    title: str = ""
    filename: str = field(default="")

    @classmethod
    def from_text(cls, text: str, filename: str) -> SubplanMetadata:
        """Parse a subplan file; ``filename`` supplies the letter and the step.

        Raises ``SubplanError`` for what prevents construction: a name that is
        not ``<letter>-<step>.md``, no frontmatter, or a missing or unknown
        ``status``. Everything else is left for :meth:`validate` to report.
        """
        match = FILENAME_RE.match(filename)
        if match is None:
            raise SubplanError(f"{filename!r} is not <letter>-<step>.md")
        fm, body = split_frontmatter(text)
        if fm is None:
            raise SubplanError("missing YAML frontmatter")
        data = parse_frontmatter(fm)

        raw_status = data.get("status")
        if not isinstance(raw_status, str) or raw_status == "":
            raise SubplanError("missing 'status'")
        try:
            status = Status(raw_status)
        except ValueError:
            raise SubplanError(f"invalid status: {raw_status!r}") from None

        moved_to = data.get("moved_to", "")
        return cls(
            letter=match.group(1),
            step=match.group(2),
            status=status,
            branch=data.get("branch", ""),
            pr=data.get("pr", ""),
            needs=_parse_needs(fm),
            moved_to=moved_to if isinstance(moved_to, str) else "",
            title=extract_title(body),
            filename=filename,
        )

    def validate(self) -> list[str]:
        """Rule violations within this one subplan (empty = valid)."""
        errors: list[str] = []
        for name in ("branch", "pr"):
            value = getattr(self, name)
            if isinstance(value, str) and value.strip() in ("none", "None"):
                errors.append(
                    f"{name} is the literal string {value!r}; use empty or null"
                )
        if isinstance(self.pr, str) and len(self.pr.split()) > 1:
            errors.append(f"pr {self.pr!r} must be a single URL, not multiple values")

        for need in self.needs:
            if not re.fullmatch(r"[a-z]", need):
                errors.append(f"needs entry {need!r} must be a single letter a-z")
            elif need == self.letter:
                errors.append(f"needs entry {need!r} names the subplan itself")
        if len(set(self.needs)) != len(self.needs):
            errors.append(f"needs lists a letter twice: {', '.join(self.needs)}")

        if self.moved_to:
            if not _PLAN_REF_RE.match(self.moved_to):
                errors.append(
                    f"moved_to {self.moved_to!r} must be a plan number like 015"
                )
            if self.status != Status.retired:
                errors.append(
                    f"moved_to is set on a {self.status.value} subplan; it belongs "
                    "to one that closed as retired"
                )
        return errors


def render_subplan(title: str, umbrella_title: str, branch: str = "") -> str:
    """A new subplan's text: minimal frontmatter, a back-link, and empty sections."""
    branch_line = f"branch: {branch}" if branch else "branch:"
    back = umbrella_title or "the umbrella plan"
    return (
        "---\n"
        "status: draft\n"
        f"{branch_line}\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        f"Part of [{back}](../plan.md).\n"
        "\n"
        "## Plan\n"
        "\n"
        "## Log\n"
    )


def next_letter(existing: list[str]) -> str:
    """The next free step letter: one past the highest taken, and never ``a``.

    ``a`` is reserved for the investigation, so the first step is ``b`` whether or
    not an investigation exists. Raises ``ValueError`` when ``b``-``z`` is used up.
    """
    taken = [s for s in existing if len(s) == 1 and FIRST_STEP_LETTER <= s <= "z"]
    if not taken:
        return FIRST_STEP_LETTER
    following = chr(ord(max(taken)) + 1)
    if following > "z":
        raise ValueError("subplan letters b-z are exhausted")
    return following


def phases(subplans: list[SubplanMetadata]) -> list[list[str]]:
    """Group the letters into phases: each runs once every earlier one has landed.

    Subplans in one phase have no dependency between them. A need that names a
    letter with no subplan is ignored here, since :func:`check_set` reports it.
    Raises ``ValueError`` naming the letters involved when the needs form a cycle.
    """
    letters = {sub.letter for sub in subplans}
    waiting = {sub.letter: {n for n in sub.needs if n in letters} for sub in subplans}
    waiting = {letter: needs - {letter} for letter, needs in waiting.items()}
    ordered: list[list[str]] = []
    landed: set[str] = set()
    while waiting:
        ready = sorted(letter for letter, needs in waiting.items() if needs <= landed)
        if not ready:
            raise ValueError(f"needs form a cycle among: {', '.join(sorted(waiting))}")
        ordered.append(ready)
        landed.update(ready)
        for letter in ready:
            del waiting[letter]
    return ordered


def render_order(ordered: list[list[str]]) -> str:
    """The phases as a one-line dependency chain, e.g. ``a -> (b, c, d) -> e``."""
    return " -> ".join(
        phase[0] if len(phase) == 1 else f"({', '.join(phase)})" for phase in ordered
    )


def check_set(subplans: list[SubplanMetadata]) -> list[str]:
    """Rule violations that only show across an umbrella's subplans together."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for sub in subplans:
        if sub.letter in seen:
            errors.append(
                f"letter {sub.letter!r} is used by both {seen[sub.letter]} and "
                f"{sub.filename}"
            )
        else:
            seen[sub.letter] = sub.filename
    for sub in subplans:
        for need in sub.needs:
            if re.fullmatch(r"[a-z]", need) and need not in seen:
                errors.append(f"{sub.filename}: needs {need!r}, which has no subplan")
    try:
        phases(subplans)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def _cells(line: str) -> list[str]:
    """The cells of one table row, trimmed, without the outer pipes."""
    parts = _CELL_SPLIT_RE.split(line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.strip() for part in parts]


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _row_letter(cell: str) -> str | None:
    """The subplan letter a first-column cell names, or ``None``.

    Accepts the bare letter, the letter in backticks, and either as the text of a
    link, so a table written by hand is read the same as a generated one.
    """
    text = cell.strip()
    link = _LINK_RE.match(text)
    if link:
        text = link.group(1).strip()
    text = text.strip("`").strip()
    return text if re.fullmatch(r"[a-z]", text) else None


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-+:?", cell) for cell in cells)


@dataclass
class _Table:
    """The marked table inside an umbrella's text, located but not yet changed."""

    lines: list[str]
    start: int  # index of the start marker
    end: int  # index of the end marker
    header: int | None  # index of the header row
    status_col: int | None
    rows: dict[str, int]  # letter -> line index of its row


def _find_table(text: str) -> _Table | None:
    lines = text.splitlines(keepends=True)
    fenced = fenced_lines(lines)
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if not fenced[i] and line.strip() == TABLE_START
        ),
        None,
    )
    if start is None:
        return None
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if not fenced[i] and lines[i].strip() == TABLE_END
        ),
        None,
    )
    if end is None:
        return None

    header: int | None = None
    status_col: int | None = None
    rows: dict[str, int] = {}
    for i in range(start + 1, end):
        if not lines[i].strip().startswith("|"):
            continue
        cells = _cells(lines[i])
        if header is None:
            header = i
            lowered = [cell.lower() for cell in cells]
            status_col = lowered.index("status") if "status" in lowered else None
            continue
        if _is_separator(cells):
            continue
        letter = _row_letter(cells[0]) if cells else None
        if letter is not None and letter not in rows:
            rows[letter] = i
    return _Table(lines, start, end, header, status_col, rows)


def table_disagreements(text: str, subplans: list[SubplanMetadata]) -> list[str]:
    """Where the umbrella's table and the subplan frontmatter disagree.

    An umbrella with no subplans and no table agrees with itself. With subplans
    and no table, the missing table is the disagreement.
    """
    table = _find_table(text)
    if table is None:
        if not subplans:
            return []
        return [
            "the umbrella has no subplan table (no "
            f"{TABLE_START} ... {TABLE_END} markers)"
        ]
    if table.header is None:
        return ["the subplan table is empty"] if subplans else []
    if table.status_col is None:
        return ["the subplan table has no Status column"]

    problems: list[str] = []
    by_letter = {sub.letter: sub for sub in subplans}
    for sub in subplans:
        at = table.rows.get(sub.letter)
        if at is None:
            problems.append(f"{sub.letter}: no row in the table ({sub.filename})")
            continue
        cells = _cells(table.lines[at])
        shown = cells[table.status_col] if table.status_col < len(cells) else ""
        if shown != sub.status.value:
            problems.append(
                f"{sub.letter}: table says {shown or 'nothing'!r}, frontmatter says "
                f"{sub.status.value!r}"
            )
    for letter in sorted(set(table.rows) - set(by_letter)):
        problems.append(f"{letter}: the table has a row with no subplan file")
    return problems


def _new_row(sub: SubplanMetadata, header: list[str], status_col: int) -> str:
    """A row for a subplan the table does not list yet.

    The title seeds the Scope column as a starting point. Every other hand-kept
    column starts empty.
    """
    cells = [""] * len(header)
    cells[0] = f"[{sub.letter}]({SUBPLANS_DIRNAME}/{sub.filename})"
    cells[status_col] = sub.status.value
    for i, name in enumerate(header):
        if name.lower() == "scope" and i not in (0, status_col):
            cells[i] = (sub.title or sub.step).replace("|", "\\|")
    return _row(cells)


def _fresh_table(ordered: list[SubplanMetadata]) -> list[str]:
    """The lines of a table started from nothing: header, separator, and rows."""
    header = list(TABLE_HEADER)
    status_col = header.index("Status")
    return [
        _row(header),
        "|" + "|".join(["---"] * len(header)) + "|",
        *(_new_row(sub, header, status_col) for sub in ordered),
    ]


def write_table(text: str, subplans: list[SubplanMetadata]) -> str:
    """Bring the table's Status column into line with the subplan frontmatter.

    Only a row whose status is wrong is rewritten, so every other row keeps its
    bytes. A subplan with no row gains one at the end of the table. A row with no
    subplan is left alone: it was written by hand, and deleting it would lose
    whatever its Scope and Note say. An umbrella with no table gains one near the
    top of its ``## Plan`` section: after the first subsection, or at the end of
    the section when it has none. Without a ``## Plan`` the table goes before
    ``## Log``.

    Raises ``ValueError`` when the table exists but has no Status column, since
    there is then no column this function is allowed to write.
    """
    ordered = sorted(subplans, key=lambda sub: sub.letter)
    table = _find_table(text)
    if table is None:
        if not ordered:
            return text
        block = "\n".join(
            ["### Subplans", "", TABLE_START, *_fresh_table(ordered), TABLE_END]
        )
        return insert_after_first_subsection(text, block, _SPEC, _AFTER_SPEC)

    lines = list(table.lines)
    if table.header is None:
        # Markers with nothing between them: the table is ours to start.
        lines[table.end : table.end] = [line + "\n" for line in _fresh_table(ordered)]
        return "".join(lines)
    if table.status_col is None:
        raise ValueError("the subplan table has no Status column")

    header = _cells(lines[table.header])
    added: list[str] = []
    for sub in ordered:
        at = table.rows.get(sub.letter)
        if at is None:
            added.append(_new_row(sub, header, table.status_col) + "\n")
            continue
        cells = _cells(lines[at])
        cells += [""] * (len(header) - len(cells))
        if cells[table.status_col] == sub.status.value:
            continue
        cells[table.status_col] = sub.status.value
        ending = "\n" if lines[at].endswith("\n") else ""
        lines[at] = _row(cells) + ending
    if added:
        lines[table.end : table.end] = added
    return "".join(lines)
