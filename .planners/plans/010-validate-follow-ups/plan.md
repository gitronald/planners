---
id: 10
slug: validate-follow-ups
status: active
branch: feature/validate-follow-ups
created: 2026-10-06T20:28:54-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/34
---

# Follow-ups from the validate --no-index review

## Plan

**Context.** PR #30 (0.9.0) added `validate --no-index`, which skips the
stale-index comparison and checks frontmatter alone, for a caller that
validates plans in a repo whose index it cannot regenerate. Two independent
review passes approved the flag as the right seam over a separate subcommand,
an environment toggle, argument-shape dependence, or caller-side handling, and
left a few items as optional follow-ups. This plan holds them for a later look;
none is urgent and each may resolve to "no change".

### 1. A distinct exit code for a stale-only failure

`validate` exits 1 for a frontmatter violation, for a stale index, and for a
zero-file match (`planners/cli.py`, the `if failures or stale:` block near the
end of `validate`, and the zero-match `Exit(1)` earlier in the function). A
script that wants both checks but different handling (fail on frontmatter,
warn on stale) has to parse stderr for `stale —`. `--no-index` sidesteps this
for the one known caller, so the question is whether any caller needs both.

To check:

- Whether any consumer of `validate`'s exit code exists beyond the pre-commit
  hook written by `install` (`planners/host.py`) and the skills' own
  instructions. Grep the prompts under `planners/prompts/` for `validate`.
- Cost of a new code: the hook and every documented invocation treat non-zero
  as failure, so a new code (say 3 for stale-only) is backward compatible for
  them. Typer reserves 2 for usage errors, which callers already use to detect
  an option the installed version lacks; do not reuse it.
- If adopted: one code for "frontmatter violations present" (1), one for
  "stale index only" (new), zero-match stays 1; the summary line already
  distinguishes the two counts. Add it to the `validate` docstring and the
  changelog.

Default if nothing needs it: close as `retired` with the reasoning above.

### 2. The stale check's cost on large repos

`_index_is_stale` re-parses every plan in the repo once per distinct root; the
comment above the `roots` set in `validate` records an earlier quadratic case.
Not a finding from the review, but worth a measurement while here: time
`validate .` on a repo with a few hundred plans with and without `--no-index`,
and record the numbers. If the difference is large, the flag's help text could
mention it as a second reason to use it in bulk checks.

### Settled during the review

- **Rules text.** Whether the generated rule (`planners/prompts/rules/planners.md`,
  written by `install`) should mention `--no-index`: added in `00789e9` as a
  one-sentence parenthetical. Done.
- **Test control.** The first version of the `--no-index` test did not show
  the stale tree failing without the flag; a control assertion was added in
  PR #30 before merge.
- **Date of the stale check.** It shipped in 0.6.0 (`aff48b3`), not 0.8.0 as
  the PR first said; the changelog entry was corrected.

### Not verified

- `--no-index` combined with `--subplans` is exercised by no test; the two
  touch different blocks of `validate`, so a failure is unlikely, but add the
  case if item 1 touches the summary logic.

### Out of scope

- Changing what the pre-commit hook runs (`host.py`); it should keep checking
  the index.

## Log

- **2026-10-09T12:45:12-07:00** — Both items investigated; both resolve to no
  code change.
  - **Item 1 (distinct stale-only exit code): not adopted.** The consumers of
    `validate`'s exit code are the `planners-validate` pre-commit hook
    (`planners/host.py`), `scripts/install.sh` (`|| die`), and the skills'
    prose, which only says `validate` "fails". All of them treat any non-zero
    exit as failure. A search of the other local repos that use planners found
    one script calling `validate`, an eval checker that passes only on exit 0.
    No caller needs frontmatter failures told apart from a stale index, and
    `--no-index` covers the one caller that wanted to skip the stale check, so
    the code stays 1.
  - **Item 2 (stale check cost): measured, small.** `bench_validate.sh` (in
    this directory) builds a synthetic repo with N plans and a fresh index,
    then reports the best of 5 wall-clock runs via `uv run planners validate`.
    Run at `e63f662`:

    | plans | dir, index | dir, `--no-index` | files, index | files, `--no-index` |
    |---|---|---|---|---|
    | 50 | 78 ms | 77 ms | 79 ms | 76 ms |
    | 300 | 95 ms | 82 ms | 93 ms | 83 ms |
    | 1000 | 131 ms | 103 ms | 132 ms | 102 ms |

    The stale check costs about 13 ms at 300 plans and 30 ms at 1000. Startup
    (`uv run` plus import) dominates. Passing files one by one, which is how
    the hook calls it, costs the same as passing a directory, so the
    per-root deduplication holds. That is too little for the `--no-index` help
    text to mention speed. To repeat:
    `.planners/plans/010-validate-follow-ups/bench_validate.sh <new-scratch-dir> 300 5`.
  - **`--no-index` with `--subplans`:** left untested. The plan made adding
    that test depend on item 1 touching the summary logic, and it did not.

## Handoff

- **State:** nothing outstanding in code. The branch carries only the timing
  script and this log. The work is pushed, and draft PR #34 is open.
- **Next:** `/planners close 010`. Both items resolved without a change, so
  close as `done` (the investigation was the deliverable) or `retired`.
  That choice is the user's to make at close.
- **Open questions:** none.
