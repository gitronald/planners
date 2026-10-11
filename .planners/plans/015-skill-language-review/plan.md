---
id: 15
slug: skill-language-review
status: active
branch: update/skill-language-review
created: 2026-10-10T18:29:26-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/47
---

# Clarify skill prompt language without changing meaning

## Plan

### Goal

Make the bundled skill bodies easier to follow without changing what a session
does when it follows them, and add one principle to the plans rule about
recording what the user said.

### Scope

1. **Plans rule.** In *No local or personal specifics*, add a standard principle
   (not tied to the visibility tiers): write what the user said as the decision,
   convention, or correction it set, with its reason, in the plan's own voice.
   Chat is candid and a plan is shared, so a plan translates between them.
2. **Clarity pass** over the eight skill bodies under
   `planners/prompts/skills/*/SKILL.md`:
   - split long multi-clause sentences, action first and reason after;
   - name the actor where a pronoun or passive voice hides it;
   - phrase instructions as what to do where the meaning is the same;
   - reflow ragged hard-wraps to the file width (about 85 characters).

### Constraints

- No meaning change: no instruction, condition, exception, or example is added,
  dropped, weakened, or strengthened.
- Code spans, commands, flags, frontmatter, step numbers, and headings are
  unchanged; other skills cite steps by number and sections by title.
- Command lines stay bare `planners ...` (the host rewrites them, and
  `tests/test_host.py` checks it). The word "abandoned" stays out of skill
  bodies (`tests/test_conventions.py`).
- "base", "mainline", and "default branch" name different things and are not
  unified.

### Order

1. Commit the rule line and its CHANGELOG entry.
2. Commit the clarity pass, one commit per group of skills.
3. Gate: `uv run pytest` green; read every hunk for meaning drift.
4. Settle the open questions in Handoff, each as its own follow-up edit or a
   separate plan.

### Out of scope

- Any change to CLI behavior or tests.
- The always-on rule beyond the one principle above.
- Resolving the ambiguities listed in Handoff within this pass; they change
  meaning, so each needs a decision.

## Log

- **2026-10-10T18:29:42-07:00** — Activated.
  - Branch: `update/skill-language-review`
  - Base: `dev` at `e69c4e2`
  - Worktree: `.worktrees/skill-language-review`
  - PR: pending
- **2026-10-10T18:30:23-07:00** — PR opened: https://github.com/gitronald/planners/pull/47
- **2026-10-10T19:22:46-07:00** — Gate (order step 3). `uv run pytest`: 576
  passed, coverage 94.38%. Read every hunk of the clarity pass for meaning drift;
  two hunks drifted and were restored:
  - `implement` step 7 had dropped "always" from "so the status always matches
    what the reviewer sees".
  - `review` turned "it needs migrating to `.planners/` first" into the
    instruction "migrate it to `.planners/` first", which reads as telling the
    session to migrate. Now "refuses ... until it is migrated".

## Handoff

### State

Order steps 1 to 3 are committed. Step 4, settling the open questions below,
waits on a decision for each.

### Open questions

Ambiguities found during the clarity pass and left unchanged, because settling
them changes meaning. Questions 2 to 5 were checked against the CLI code and the
skill text on 2026-10-10; the finding is under each.

1. **`close`, review gate.** Does "each with a paired regression test" also
   apply on the minimal-review path? Not answerable from the code: the minimal
   gate says "fix what the skim finds the same way the full gate does", which
   can be read either way. This is a policy decision.
2. **`implement` step 2.** "`single-branch` also changes steps 3, 4, and 7,
   where the push would be rejected or would publish" does not say which push
   is rejected and which publishes. Finding: the skill's own steps answer it.
   Step 3's push of the base publishes (line "On a `single-branch` remote, do
   not push the base"), step 4's `git push -u` is rejected ("the remote rejects
   any branch but its own"), and step 7 skips its push.
3. **`backfill` step 2.** It reads "filename" as if it were a frontmatter field.
   Finding: identity validates against the plan's directory name, which is read
   alongside the frontmatter, not from it.
4. **`index`.** In the sort order "status, then concluded, PR, and plan number
   (descending)", it is unclear whether "descending" covers every key or only
   the last. Finding: `sort_plans` in `planners/index.py` sorts status by the
   fixed order and concluded, PR, and plan number all descending (newest
   concluded first, a missing value after a present one).
5. **`pipeline`.** The contract says a run always opens a draft PR; a later
   bullet says a non-GitHub remote opens none. The exception is stated but the
   contract line reads as absolute. Finding: the pipeline's own implement
   bullet already says "Off GitHub ... there is no PR", so "always" is the only
   word out of line.
