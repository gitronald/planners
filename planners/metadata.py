"""The plan-frontmatter schema, defined as code.

``PlanMetadata`` is the single source of truth for a plan file's frontmatter:
its fields, their order, parsing, rendering, and validation rules all live here
rather than being restated in prose. Everything in this module is a pure
transform — the only filesystem touch is ``from_file``, a thin read that
delegates all logic to ``from_text``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from planners.utils import (
    _Serializable,
    is_safe_slug,
    parse_frontmatter,
    split_frontmatter,
)

# NNN[x]-slug — the plan *directory* name, where NNN is one or more digits and
# the optional letter run is the subplan suffix (``""`` for an ordinary/umbrella
# plan, ``a``/``b``/… for a subplan that shares its umbrella's number). A plan's
# identity lives in its containing directory; the file inside is always plan.md.
# The suffix is matched as ``[a-z]*`` (not ``[a-z]?``) so a malformed multi-letter
# dir like ``010ab-x`` is still discovered and then loudly flagged by ``validate``
# rather than silently skipped. Groups: (id, sub, slug).
DIRNAME_RE = re.compile(r"^(\d+)([a-z]*)-(.+)$")

# The fixed file name inside every plan directory.
PLAN_FILENAME = "plan.md"


def is_plan_dirname(name: str) -> bool:
    """True when ``name`` matches the ``NNN[x]-slug`` plan directory pattern."""
    return bool(DIRNAME_RE.match(name))


class Status(StrEnum):
    """The five plan statuses. The only terminal status is ``retired`` (neutral:
    superseded or no longer needed); there is no separate failed/cancelled state."""

    draft = "draft"
    active = "active"
    done = "done"
    inactive = "inactive"
    retired = "retired"


# Open or parked: nullable fields stay empty (pending), never YAML null.
OPEN_STATUSES = frozenset({Status.draft, Status.active, Status.inactive})
# Terminal: concluded is required; a genuinely-absent branch/pr renders as null.
CLOSED_STATUSES = frozenset({Status.done, Status.retired})


class PlanError(ValueError):
    """Frontmatter that cannot be parsed into a ``PlanMetadata`` at all."""


def extract_title(body: str) -> str:
    """Return the text of the first level-1 (``# ``) heading in ``body``."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "#":
            return ""
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _as_str(value: str | None) -> str:
    return value if isinstance(value, str) else ""


def _parses_iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _kv(key: str, value: str | None) -> str:
    """Render one frontmatter line, honoring the empty-vs-null convention."""
    if value is None:
        return f"{key}: null"
    if value == "":
        return f"{key}:"
    return f"{key}: {value}"


@dataclass
class PlanMetadata(_Serializable):
    """A plan file's frontmatter plus its title.

    The nullable fields (``branch``, ``concluded``, ``pr``) carry a meaningful
    empty-vs-``None`` distinction: ``""`` is *pending* (an open plan), ``None``
    is *closed and genuinely N/A*. ``render`` and ``validate`` both respect it.
    """

    id: int = field(
        metadata={"description": "plan number; MUST equal the directory's NNN prefix"}
    )
    slug: str = field(
        metadata={"description": "kebab-case; MUST equal the directory's slug"}
    )
    status: Status = field(
        metadata={"description": "draft | active | done | inactive | retired"}
    )
    branch: str | None = field(
        default="",
        metadata={"description": 'feature branch; "" = pending, null = closed & N/A'},
    )
    created: str = field(
        default="", metadata={"description": "ISO-8601 capture time at creation"}
    )
    concluded: str | None = field(
        default="",
        metadata={
            "description": 'ISO-8601 from concluding commit; "" if open, null if N/A'
        },
    )
    pr: str | None = field(
        default="",
        metadata={"description": 'full PR URL; "" = pending, null = closed & N/A'},
    )
    # ``sub`` is part of identity (like id/slug) and renders right after ``slug``
    # — but a dataclass forbids a defaulted field before the non-defaulted
    # ``status``, so it is declared here among the defaulted fields and placed in
    # canonical position by ``render_frontmatter`` (which orders lines by hand).
    sub: str = field(
        default="",
        metadata={"description": 'subplan letter; "" = ordinary/umbrella, else a–z'},
    )
    title: str = field(
        default="",
        metadata={"description": "the # Title heading", "frontmatter": False},
    )
    dirname: str | None = field(
        default=None,
        metadata={"description": "source plan directory name", "frontmatter": False},
    )

    @property
    def prefix(self) -> str:
        """The ``NNN[x]`` identity prefix — the plan's directory name minus the slug."""
        return f"{self.id:03d}{self.sub}"

    @classmethod
    def from_text(cls, text: str, dirname: str | None = None) -> PlanMetadata:
        """Parse frontmatter + title from full plan-file text.

        Raises ``PlanError`` only for failures that prevent construction
        (missing/non-integer ``id``, missing ``slug``, missing/unknown
        ``status``). Value-level rule violations are left for ``validate`` to
        report, so a malformed-but-parseable plan can still be diagnosed.
        """
        fm, body = split_frontmatter(text)
        if fm is None:
            raise PlanError("missing YAML frontmatter")
        data = parse_frontmatter(fm)

        raw_id = data.get("id")
        if not isinstance(raw_id, str) or raw_id == "":
            raise PlanError("missing 'id'")
        try:
            plan_id = int(raw_id)
        except ValueError:
            raise PlanError(f"non-integer id: {raw_id!r}") from None

        slug = data.get("slug")
        if not isinstance(slug, str) or slug == "":
            raise PlanError("missing 'slug'")

        raw_status = data.get("status")
        if not isinstance(raw_status, str) or raw_status == "":
            raise PlanError("missing 'status'")
        try:
            status = Status(raw_status)
        except ValueError:
            raise PlanError(f"invalid status: {raw_status!r}") from None

        return cls(
            id=plan_id,
            slug=slug,
            status=status,
            branch=data.get("branch", ""),
            created=_as_str(data.get("created", "")),
            concluded=data.get("concluded", ""),
            pr=data.get("pr", ""),
            sub=_as_str(data.get("sub", "")),
            title=extract_title(body),
            dirname=dirname,
        )

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> PlanMetadata:
        """Read a plan file and parse it; the parent dir name drives validation.

        Identity comes from the containing ``NNN-slug/`` directory, not the file
        (which is always ``plan.md``)."""
        p = Path(path)
        return cls.from_text(p.read_text(encoding="utf-8"), dirname=p.parent.name)

    def render_frontmatter(self) -> str:
        """Emit the frontmatter block in canonical field order.

        ``sub`` renders right after ``slug`` — but only for a subplan: an empty
        ``sub`` emits no line at all, so every ordinary plan stays byte-identical
        to the pre-subplan format (no ``sub:`` churn).
        """
        lines = ["---", f"id: {self.id}", f"slug: {self.slug}"]
        if self.sub:
            lines.append(f"sub: {self.sub}")
        lines += [
            f"status: {self.status.value}",
            _kv("branch", self.branch),
            _kv("created", self.created),
            _kv("concluded", self.concluded),
            _kv("pr", self.pr),
            "---",
        ]
        return "\n".join(lines) + "\n"

    def render(self) -> str:
        """Emit a full plan file: canonical frontmatter, then the title heading."""
        return f"{self.render_frontmatter()}\n# {self.title}\n"

    def validate(self) -> list[str]:
        """Return a list of human-readable rule violations (empty = valid)."""
        errors: list[str] = []

        # An empty dirname (e.g. from a path with no parent component) carries no
        # directory context, so it is skipped like ``None`` rather than flagged.
        if self.dirname:
            match = DIRNAME_RE.match(self.dirname)
            if not match:
                errors.append(f"directory {self.dirname!r} is not NNN-slug")
            else:
                dir_id, dir_sub, dir_slug = (
                    int(match.group(1)),
                    match.group(2),
                    match.group(3),
                )
                if dir_id != self.id:
                    errors.append(f"id {self.id} != directory prefix {dir_id}")
                if dir_sub != self.sub:
                    errors.append(f"sub {self.sub!r} != directory sub {dir_sub!r}")
                if dir_slug != self.slug:
                    errors.append(f"slug {self.slug!r} != directory slug {dir_slug!r}")

        if not is_safe_slug(self.slug):
            errors.append(f"slug {self.slug!r} is not kebab-case")

        if self.sub and not re.fullmatch(r"[a-z]", self.sub):
            errors.append(f"sub {self.sub!r} must be a single letter a–z")

        for name in ("branch", "created", "concluded", "pr"):
            value = getattr(self, name)
            if isinstance(value, str) and value.strip() in ("none", "None"):
                errors.append(
                    f"{name} is the literal string {value!r}; use empty or null"
                )

        # A PR URL is a single token — internal whitespace means the value is
        # malformed (e.g. the URL accidentally stored twice), which the index
        # then renders verbatim into a broken markdown link.
        if isinstance(self.pr, str) and len(self.pr.split()) > 1:
            errors.append(f"pr {self.pr!r} must be a single URL, not multiple values")

        if self.created == "":
            errors.append("created is required")
        elif not _parses_iso(self.created):
            errors.append(f"created {self.created!r} is not ISO-8601")

        if self.status in CLOSED_STATUSES:
            if not self.concluded:
                errors.append(
                    f"{self.status.value} plan requires a concluded timestamp"
                )
            elif not _parses_iso(self.concluded):
                errors.append(f"concluded {self.concluded!r} is not ISO-8601")
        else:
            for name in ("branch", "pr", "concluded"):
                if getattr(self, name) is None:
                    errors.append(
                        f"{self.status.value} plan must not use null for {name}"
                    )
            if self.concluded:
                errors.append(f"{self.status.value} plan must leave concluded empty")

        return errors


def next_number(existing_ids: list[int]) -> int:
    """The next plan number: one past the current maximum, or 0 when empty.

    Subplans reuse their umbrella's number, so duplicate ids in ``existing_ids``
    do not change the maximum — a top-level ``add`` after umbrella 10 with
    subplans 10a/10b still yields 11.
    """
    return max(existing_ids) + 1 if existing_ids else 0


def next_sub(existing_subs: list[str]) -> str:
    """The next subplan letter: one past the current max, or ``"a"`` when empty.

    Only well-formed single-letter ``a``–``z`` subs count toward the maximum: the
    umbrella's empty ``sub`` is ignored, and a malformed multi-letter sub (which
    ``validate`` flags separately) is skipped here rather than crashing ``ord`` on
    a length-2 string. Raises ``ValueError`` when ``a``–``z`` is exhausted, instead
    of emitting a past-``z`` character that later directory scans would silently
    drop.
    """
    letters = [s for s in existing_subs if len(s) == 1 and "a" <= s <= "z"]
    if not letters:
        return "a"
    nxt = chr(ord(max(letters)) + 1)
    if nxt > "z":
        raise ValueError("subplan letters a–z are exhausted")
    return nxt
