---
id: 17
slug: validate-timestamp-ordering
status: implemented
branch: feature/validate-timestamp-ordering
created: 2026-08-20T10:56:15-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/59
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
- **2026-10-31T14:53:54-07:00** — PR opened: https://github.com/gitronald/planners/pull/59
- **2026-10-31T14:53:55-07:00** — Added the ordering check to `PlanMetadata.validate` with `parse_instant`, as the plan specified. Checks at the commit carrying this work: ruff, pyrefly, and 622 tests passed, run by this session.
  - Departure from the spec: `conclude` and `retire` now write `created` when the date from git is older than the plan, through `PlanMetadata.conclude_at`. A scratch repo showed `conclude` writing `concluded` about ten months before `created` for a plan written after its work. The new check would have made the hook reject that close, and timestamps are not typed by hand, so the plan could not have closed.
  - The rule file and the backfill skill state the ordering rule. Backfill picks `concluded` from git, so it can hit the same case.
  - Survey, read-only: the new `validate --no-index` over the 50 local repos with a `.planners/` tree flags 60 plans in 16 repos. To repeat it, run that command in each repo and count `is before created`.
  - The survey contradicts the Background's reading of these values as paste errors. Most are migration batches that stamped one `created` on many plans, and retroactive plans written after their work, so `concluded` is true and `created` is what is off. See the Handoff.
  - Timestamps with no offset read as UTC, per `parse_instant`. A naive or date-only value on the same day as an offset value could be flagged falsely. Conscious no-op: the survey's 1149 closed plans hold no naive value and 3 date-only `created` values, and of those 3 the one flagged is days apart.
- **2026-10-31T14:54:05-07:00** — Implemented: 5 commits ahead of `dev`.

## Handoff

- State: the check, the lifecycle fix, the docs, and the tests are committed and pushed on the plan's branch, with the PR open.
- Open questions:
  1. The check flags 60 existing plans in 16 local repos, 15 of which have the validate hook. Merge it as a hard error, as the plan specifies, and repair those plans in a follow-up before the next stable release? The hook passes only staged plan files, so a flagged plan fails when it is next edited or on a whole-repo `planners validate`, not on every commit. None of the 16 runs `planners validate` in CI.
- Not verified: the hook's behavior after a release in a downstream repo. The survey ran this branch's CLI read-only and changed nothing in those repos.
- Remaining: the review gate, then close. Waits on the owner's answer to question 1.
