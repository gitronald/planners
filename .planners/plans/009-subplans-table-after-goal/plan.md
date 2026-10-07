---
id: 9
slug: subplans-table-after-goal
status: active
branch: feature/subplans-table-after-goal
created: 2026-10-06T15:01:33-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/31
---

# Place the generated subplans table at the top of the umbrella's spec

## Plan

### Problem

When an umbrella has no subplans table yet, the first nested `add` inserts one at the end
of the `## Plan` section, ahead of `Log`, `Handoff`, and `Retrospective`
(`_AFTER_SPEC` in `planners/subplans.py`, used by `write_table`). The table is the
umbrella's summary of its steps and their status, and it is the first thing a reader
looks for. Putting it after decisions, risks, and out-of-scope sections buries it under
the material it summarizes, and umbrellas end up rearranged by hand.

The markers already allow any placement: `write_table` finds the table by
`<!-- planners:subplans:start -->` wherever it is. Only the default insertion point
changes.

### Change

1. In `write_table`, when no table exists, insert the block near the top of `## Plan`
   instead of at its end:
   - after the first `###` subsection of `## Plan` when there is one (the umbrella's
     opening summary, usually a Goal or Scope section), or
   - directly after the `## Plan` heading and its lead paragraph when `## Plan` has no
     subsections yet, or
   - as now, before `_AFTER_SPEC`, when there is no `## Plan` section at all (the
     scaffold straight from `planners add`), so the umbrella still gets one.
2. Add a helper in `planners/body.py` for "insert after the first subsection of section
   X", beside `insert_before_section`, so the placement rule lives with the other body
   edits and is tested the same way.
3. Keep moving the table by hand working: a pre-placed empty marker pair, or an existing
   table anywhere in the file, is found and used as today. Add a test for each.
4. Update the `add` skill text: "at the end of the umbrella's `## Plan` section" becomes
   "after the first subsection of the umbrella's `## Plan` section (the opening summary),
   or at the top of it". Keep the paragraph on pre-placing the markers.
5. `CHANGELOG.md` `[Unreleased]`: a behavior change for new umbrellas; existing tables are
   not moved.

### Tests

- Fresh scaffold (no `## Plan`): table lands before `Log`, as before.
- `## Plan` with a lead paragraph and no subsections: table follows the lead paragraph.
- `## Plan` with `### Goal` then `### Decided`: table lands between them.
- Existing table at the end of the spec: left where it is, status column regenerated.
- Empty marker pair placed by hand: filled in place.

### Out of scope

Moving tables in umbrellas that already have one. `planners subplans --write` keeps the
table where it finds it.

## Log

- **2026-10-06T18:05:21-07:00** — Implemented on `feature/subplans-table-after-goal` (PR #31). Added
  `insert_after_first_subsection` to `planners/body.py`; `write_table` now uses it with
  `## Plan` as the section and `Log`/`Handoff`/`Retrospective` as the fallback. Five body
  tests and five `write_table` placement tests cover the cases listed under Tests; the
  full suite (356 tests), ruff, and pyrefly pass. Checked end to end with
  `planners add --parent 000 --nested` in a scratch repo: the table landed between
  `### Goal` and `### Decided`. Skill text and `CHANGELOG.md` updated.
