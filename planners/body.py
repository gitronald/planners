"""Pure helpers for editing a plan's markdown body without rewriting it.

A plan's text is the record, so every command that touches a body makes the
smallest edit that does the job: one frontmatter line, one entry appended to a
section, one table cell. Nothing here re-renders a body from a model of it, and
nothing here touches the filesystem, git, or the clock.

Lines inside a fenced code block are never treated as structure. A plan that
documents a heading or a marker comment in an example would otherwise have the
example edited in place of the real thing.

Text is taken to end its lines with ``\n``, which is what the CLI hands over:
it reads with universal newlines, so a CRLF file arrives here already converted.
"""

from __future__ import annotations

import re

__all__ = [
    "append_to_section",
    "fenced_lines",
    "insert_before_section",
    "section_span",
    "set_frontmatter_key",
]

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# An ATX heading. The closing run of `#` is optional and must be set off by a
# space or tab, as CommonMark has it, so a title that ends in `#` keeps it.
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")


def fenced_lines(lines: list[str]) -> list[bool]:
    """For each line, True when it is a code fence or sits inside one.

    A fence closes only on a run of the same character at least as long as the
    one that opened it, so a four-backtick block can quote a three-backtick one.
    An unclosed fence runs to the end of the text, which is how markdown reads it.
    """
    flags: list[bool] = []
    opener: str | None = None
    for line in lines:
        match = _FENCE_RE.match(line)
        if opener is None:
            if match:
                opener = match.group(1)
                flags.append(True)
            else:
                flags.append(False)
            continue
        flags.append(True)
        if (
            match
            and match.group(1)[0] == opener[0]
            and len(match.group(1)) >= len(opener)
            and line.strip() == match.group(1)
        ):
            opener = None
    return flags


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Every heading outside a code fence, as ``(line index, level, text)``."""
    fenced = fenced_lines(lines)
    found: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if match:
            found.append((i, len(match.group(1)), match.group(2)))
    return found


def section_span(text: str, title: str, level: int = 2) -> tuple[int, int] | None:
    """The line span ``[start, end)`` of the section headed ``title``, or ``None``.

    ``start`` is the heading's own line. ``end`` is the next heading of the same
    or a higher level, or the end of the text. The title is matched whole and
    case-sensitively, so ``Log`` does not match ``Logistics``.
    """
    lines = text.splitlines(keepends=True)
    headings = _headings(lines)
    for position, (index, found_level, found_title) in enumerate(headings):
        if found_level != level or found_title != title:
            continue
        for later_index, later_level, _ in headings[position + 1 :]:
            if later_level <= level:
                return index, later_index
        return index, len(lines)
    return None


def _ends_with_newline(text: str) -> bool:
    return text == "" or text.endswith("\n")


def insert_before_section(text: str, block: str, titles: tuple[str, ...]) -> str:
    """Insert ``block`` before the first level-2 section named in ``titles``.

    ``block`` lands at the end of the text when none of the sections exists. It is
    separated from its neighbors by one blank line on each side.
    """
    lines = text.splitlines(keepends=True)
    spans = [span for title in titles if (span := section_span(text, title))]
    block = block.strip("\n") + "\n"
    if not spans:
        head = text if _ends_with_newline(text) else text + "\n"
        gap = "" if head == "" or head.endswith("\n\n") else "\n"
        return head + gap + block
    at = min(start for start, _ in spans)
    head = "".join(lines[:at])
    gap = "" if head == "" or head.endswith("\n\n") else "\n"
    return head + gap + block + "\n" + "".join(lines[at:])


def append_to_section(
    text: str, title: str, entry: str, before: tuple[str, ...] = ()
) -> str:
    """Append ``entry`` to the end of the level-2 section headed ``title``.

    The section is created when it is absent: before the first section named in
    ``before`` that exists, or at the end of the text. Trailing blank lines stay
    after the entry, so the section keeps its distance from the next heading.
    """
    entry = entry.strip("\n") + "\n"
    span = section_span(text, title)
    if span is None:
        return insert_before_section(text, f"## {title}\n\n{entry}", before)

    lines = text.splitlines(keepends=True)
    start, end = span
    last = end
    while last > start + 1 and lines[last - 1].strip() == "":
        last -= 1
    head = "".join(lines[:last])
    if not _ends_with_newline(head):
        head += "\n"
    # An empty section has only its heading, which the entry is set off from.
    gap = "\n" if last == start + 1 else ""
    tail = "".join(lines[last:])
    return head + gap + entry + tail


def set_frontmatter_key(text: str, key: str, value: str | None) -> str:
    """Set one ``key: value`` line in ``text``'s frontmatter, leaving the rest alone.

    An existing line for ``key`` is replaced where it stands. A new key is added
    as the last line of the block. ``""`` renders as the bare ``key:`` and
    ``None`` as ``key: null``, the empty-versus-null convention the plan schema
    uses. Text with no frontmatter gains a block holding only this key.
    """
    if value is None:
        rendered = f"{key}: null"
    elif value == "":
        rendered = f"{key}:"
    else:
        rendered = f"{key}: {value}"

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return f"---\n{rendered}\n---\n\n{text}" if text else f"---\n{rendered}\n---\n"

    close = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
        None,
    )
    if close is None:
        return f"---\n{rendered}\n---\n\n{text}"

    for i in range(1, close):
        name, sep, _ = lines[i].partition(":")
        if sep and name.strip() == key and not lines[i].lstrip().startswith("#"):
            lines[i] = rendered + "\n"
            return "".join(lines)

    lines.insert(close, rendered + "\n")
    return "".join(lines)
