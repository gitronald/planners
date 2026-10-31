---
id: 17
slug: validate-timestamp-ordering
status: active
branch: feature/validate-timestamp-ordering
created: 2026-08-20T10:56:15-07:00
concluded:
pr:
---

# Validate concluded is not before created

## Plan

### Background

`planners validate` checks frontmatter presence and shape but not chronology.
A downstream repo's plan migration shipped an archive plan whose `concluded`
predated its own `created` by about a minute — the value had been pasted from
a sibling plan's `created` field — and validation passed silently, baking the
impossible date into the generated index. A plan cannot conclude before it
exists, so ordering is a schema-level invariant validate should enforce.

### Approach

1. Add a chronological check to `planners validate`: when both `created` and
   `concluded` parse as timestamps, fail with an error if `concluded` is
   earlier than `created`.
2. The error message names the plan file and prints both timestamps so the
   bad value is obvious at a glance.
3. Skip the check when `concluded` is empty or `null` (draft, active, and
   inactive plans) — presence rules for those states are already covered by
   the existing status checks.
4. Tests: a conformant done plan passes; `concluded` before `created` fails
   with the new error; empty and `null` `concluded` are ignored.

### Out of scope

- Cross-checking timestamps against git history (e.g., that `concluded`
  matches the closing commit) — validate stays a pure frontmatter check.

## Log

### 2026-10-27 - Renumbered

- First added as 004 on 2026-08-20 in a clone that was never pushed;
  upstream has since used 004 for another plan. Re-added unchanged under a
  new number. The check can reuse `planners.utils.parse_instant`, which now
  compares timestamps across UTC offsets.
- **2026-10-31T14:33:30-07:00** — Activated.
  - Branch: `feature/validate-timestamp-ordering`
  - Base: `dev` at `af6e12d`
  - Worktree: `.worktrees/017-validate-timestamp-ordering`
  - PR: pending
