---
id: 17
slug: validate-timestamp-ordering
status: done
branch: feature/validate-timestamp-ordering
created: 2026-08-20T10:56:15-07:00
concluded: 2026-10-31T14:55:54-07:00
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
- **2026-10-31T14:59:12-07:00** — Review gate passed at medium level, and the owner approved the merge as a hard error. Final checks at the commit that fixed the skills: ruff, pyrefly, and 622 tests passed, run by this session. CI passed on 3.11 to 3.14 at the commit before it, and that fix touches only skill text.
  - Review follow-up: the correctness and reuse finders returned nothing. A further pass found the close and update skills still saying `concluded` is always the git date; fixed in the skills, with no paired test because it is prose only. The review is posted on the PR.
  - Conscious no-ops: same-day naive or date-only values against offset values, as logged above.
  - Re-ran the scratch repo repro on this branch: a plan written after its work closed with `concluded` equal to `created`, and `validate` passed.

## Handoff

- State: the check, the lifecycle fix, the docs, and the tests are finished, reviewed, and on the plan's branch.
- Questions:
  1. Merge as a hard error even though it flags 60 existing plans in 16 local repos? Answered 2026-10-31: yes, merge. The repair of those plans is handed to a plan in the owner's private workspace, outside this repo.
- Not verified: the hook's behavior after a release in a downstream repo. That `created` rather than `concluded` is the wrong value in each flagged plan is inferred from shared `created` values and plan slugs, not checked plan by plan.
- Remaining: nothing in this repo. Downstream repos see the check once a release carries it.

## Retrospective

- The check itself was the small part and went as planned. The real work was what enforcing it exposed, which the plan had not looked for.
- The plan's premise was only partly right. "A plan cannot conclude before it exists" holds for a value pasted by mistake, but `conclude` deliberately dates the last work commit, and work can come before the plan. A new invariant needs a check of who writes the value as well as who reads it.
- Writing `created` in `conclude` and `retire` loses the true work date for a retroactive plan. The alternative was a close the hook rejects with no sanctioned fix, and git still holds the date.
- Running a new rule over real plans before merging turned a surprise on some later commit into a decision made at the gate. Do this for any new `validate` rule.
