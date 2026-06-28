"""Pure helpers shared across planners modules.

Nothing here touches the filesystem, git, or the clock — these are the
transform primitives the higher-level modules build on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

# kebab-case: lowercase alphanumeric words joined by single hyphens
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class FieldDoc:
    """One documented frontmatter field: its name, type label, and description."""

    name: str
    type: str
    description: str


class _Serializable:
    """Mixin giving a dataclass schema introspection over its frontmatter fields.

    A field is excluded from the schema when its metadata carries
    ``{"frontmatter": False}`` (used for derived attributes like the title or
    source plan-directory name that are not part of the YAML block).
    """

    @classmethod
    def schema(cls) -> list[FieldDoc]:
        # cls is a concrete dataclass subclass at every real call site.
        docs: list[FieldDoc] = []
        for f in fields(cls):  # type: ignore[arg-type]
            if not f.metadata.get("frontmatter", True):
                continue
            type_label = (
                f.type
                if isinstance(f.type, str)
                else getattr(f.type, "__name__", str(f.type))
            )
            docs.append(
                FieldDoc(
                    name=f.name,
                    type=type_label,
                    description=str(f.metadata.get("description", "")),
                )
            )
        return docs


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split leading YAML frontmatter from the body.

    Returns ``(frontmatter, body)``. ``frontmatter`` is the raw text *between*
    the ``---`` fences (without the fence lines); it is ``None`` when the text
    has no opening fence or no closing fence. This function is total — it never
    raises for any string — and when ``frontmatter`` is ``None`` the body is the
    input verbatim (lossless), so a missing fence, a lone ``---``, or ``---``
    rules in the body are all handled without losing content.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n").strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    # opening fence with no closing fence -> treat as no frontmatter, lossless
    return None, text


def parse_frontmatter(fm_text: str) -> dict[str, str | None]:
    """Parse flat ``key: value`` frontmatter into a dict.

    The plan schema is flat, so a YAML library is unnecessary — and would in
    fact erase the distinction this package depends on: a bare ``pr:`` (pending)
    maps to ``""`` while ``pr: null`` (closed and N/A) maps to ``None``. Both
    parse to YAML null, but here they stay distinct. Surrounding quotes on a
    value are stripped; the first ``:`` separates key from value, so colons in
    timestamps and URLs are preserved.
    """
    out: dict[str, str | None] = {}
    for raw in fm_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            out[key] = ""
        elif value.lower() == "null":
            out[key] = None
        else:
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            out[key] = value
    return out


def is_safe_slug(slug: str) -> bool:
    """True when ``slug`` is kebab-case and cannot escape ``.planners/``.

    Rejects path separators, ``..`` traversal, and null bytes outright before
    the kebab-case check, so a slug can never be used to write outside the
    plans directory.
    """
    if "/" in slug or "\\" in slug or ".." in slug or "\x00" in slug:
        return False
    return bool(SLUG_RE.fullmatch(slug))
