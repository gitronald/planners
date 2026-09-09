"""Repo-mode plan index: render the plans table and the full ``.planners/README.md``.

Pure transforms only. The CLI handles discovering plan files and writing the
result back; this module just turns a list of ``PlanMetadata`` into a table and
wraps that table in a titled index document (a full regeneration — there is no
curated content to preserve)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from planners.metadata import PlanMetadata, Status

# The index's own location, relative to the repo root. It lives here rather than
# in the CLI because two unrelated modules need it — the CLI writes the file, and
# ``install`` writes the ``.gitattributes`` line naming it — and a path spelled in
# two places is the drift hazard this package keeps warning about.
INDEX_PATH = Path(".planners/README.md")

EM_DASH = "—"

# Index sort order over statuses (open work first, then closed, parked last).
STATUS_ORDER = [
    Status.active,
    Status.draft,
    Status.done,
    Status.inactive,
    Status.retired,
]
_STATUS_RANK = {status: rank for rank, status in enumerate(STATUS_ORDER)}

_PR_NUM_RE = re.compile(r"/pull/(\d+)")

CURATED_HEADER = ("#", "Plan", "Status", "Concluded", "PR")
WIDE_HEADER = ("#", "Plan", "Status", "Branch", "Created", "Concluded", "PR")


def _instant(value: str | None) -> float | None:
    """Parse an ISO-8601 timestamp to a comparable UTC instant (epoch seconds).

    Returns ``None`` for empty/null or unparseable values. Comparing the parsed
    instant — rather than the raw string — keeps ordering correct across plans
    written with different UTC offsets, where lexical order does not match
    chronological order.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _concluded_key(meta: PlanMetadata) -> tuple[int, float]:
    # Present instants sort before missing/unparseable; newer instant first.
    instant = _instant(meta.concluded)
    return (1, instant) if instant is not None else (0, 0.0)


def _pr_key(meta: PlanMetadata) -> tuple[int, int]:
    if not meta.pr:
        return (0, 0)
    match = _PR_NUM_RE.search(meta.pr)
    return (1, int(match.group(1))) if match else (1, 0)


def sort_plans(metas: list[PlanMetadata]) -> list[PlanMetadata]:
    """Order plans for the index: by status, then concluded, PR, and id (desc).

    Built from stacked stable sorts applied least-significant first. Every plan —
    umbrella, standalone, or subplan — sorts by its *own* keys, so the Status
    column stays monotonic: a ``done`` subplan of an ``active`` umbrella sorts
    into the done section rather than being hoisted to the top under its umbrella.
    ``(id desc, sub asc)`` are the least-significant tiebreakers, so when status,
    concluded, and PR all tie an umbrella still leads its subplans and same-id
    plans stay adjacent. ``(id, sub)`` is unique, so the result is a deterministic
    total order.
    """
    rows = list(metas)
    rows.sort(key=lambda m: m.sub)  # least significant: "" < "a" < "b" on a tie
    rows.sort(key=lambda m: m.id, reverse=True)
    rows.sort(key=lambda m: _pr_key(m), reverse=True)
    rows.sort(key=lambda m: _concluded_key(m), reverse=True)
    rows.sort(key=lambda m: _STATUS_RANK.get(m.status, len(STATUS_ORDER)))
    return rows


def _escape(text: str) -> str:
    """Escape characters that would break a markdown table cell."""
    return text.replace("|", "\\|")


def _cell(value: str | None) -> str:
    return _escape(value) if value else EM_DASH


# US zones, each mapped to a DST-agnostic catch-all acronym. A saved timestamp
# carries only a UTC offset, not a zone name, so the offset is matched against
# these zones *at the timestamp's own instant* to recover an acronym — which
# disambiguates zones that share an offset only in one season (e.g. -07:00 is
# Pacific in summer but Mountain in winter). All observe DST, so at any instant
# their offsets are distinct; order does not matter.
_US_ZONES = (
    ("America/New_York", "ET"),
    ("America/Chicago", "CT"),
    ("America/Denver", "MT"),
    ("America/Los_Angeles", "PT"),
)


def _zone_label(parsed: datetime) -> str:
    """A timezone acronym for ``parsed``'s saved offset, or the literal offset.

    No conversion: the offset is taken as saved and matched to a US zone at this
    instant (UTC -> ``UTC``). An offset matching no listed zone — another region,
    or a host without the IANA tz database — falls back to its own ``+HH:MM`` form
    so the timestamp is labeled honestly rather than mislabeled. A naive value
    (no offset) gets no label.
    """
    offset = parsed.utcoffset()
    if offset is None:
        return ""
    if offset == timedelta(0):
        return "UTC"
    for name, acronym in _US_ZONES:
        try:
            if parsed.astimezone(ZoneInfo(name)).utcoffset() == offset:
                return acronym
        except ZoneInfoNotFoundError:
            continue
    raw = parsed.strftime("%z")  # e.g. "-0700"
    return f"{raw[:-2]}:{raw[-2:]}" if raw else ""


def _format_instant(value: str | None) -> str:
    """Render a saved ISO-8601 timestamp as ``YYYY-MM-DD HH:MM <zone>``.

    The saved wall-clock time and offset are shown verbatim — no normalization to
    the viewer's zone — with the offset rendered as a US catch-all acronym (see
    :func:`_zone_label`), so the output is deterministic across machines and rows
    may legitimately mix zones. Empty/null -> em-dash; an unparseable value falls
    back to the raw string so it is shown, not dropped.
    """
    if not value:
        return EM_DASH
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return _escape(value)
    stamp = parsed.strftime("%Y-%m-%d %H:%M")
    label = _zone_label(parsed)
    return _escape(f"{stamp} {label}" if label else stamp)


def _pr_cell(pr: str | None) -> str:
    if not pr:
        return EM_DASH
    match = _PR_NUM_RE.search(pr)
    label = f"#{match.group(1)}" if match else "PR"
    return f"[{label}]({pr})"


def _plan_cell(meta: PlanMetadata) -> str:
    dirname = meta.dirname or f"{meta.prefix}-{meta.slug}"
    # Link is relative to .planners/README.md; plan dirs live under plans/, so
    # the target is plans/{NNN}[x]-{slug}/plan.md.
    return f"[{_escape(meta.title or meta.slug)}](plans/{dirname}/plan.md)"


def render_plans_table(metas: list[PlanMetadata], cols: str = "curated") -> str:
    """Render the markdown plans table. ``cols`` is ``curated`` or ``all``."""
    wide = cols == "all"
    header = WIDE_HEADER if wide else CURATED_HEADER
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for meta in sort_plans(metas):
        cells = [meta.prefix, _plan_cell(meta), meta.status.value]
        if wide:
            cells += [_cell(meta.branch), _format_instant(meta.created)]
        cells += [_format_instant(meta.concluded), _pr_cell(meta.pr)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_index(title: str, table: str) -> str:
    """Render the full index document: a ``# {title}`` heading then ``table``.

    This is a complete regeneration of ``.planners/README.md`` — unlike the old
    splice, there is no curated content to preserve, so the output is just the
    title and the table. ``table`` already carries its trailing newline, so the
    result ends in exactly one. Idempotent by construction."""
    return f"# {title}\n\n{table}"
