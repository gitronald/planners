---
id: 15
slug: skill-language-review
status: active
branch: update/skill-language-review
created: 2026-10-10T18:29:26-07:00
concluded:
pr:
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

## Handoff

### Open questions

Ambiguities found during the clarity pass and left unchanged, because settling
them changes meaning. None was checked against the CLI code yet.

1. **`close`, review gate.** Does "each with a paired regression test" also
   apply on the minimal-review path?
2. **`implement` step 2.** "`single-branch` also changes steps 3, 4, and 7,
   where the push would be rejected or would publish" does not say which push
   is rejected and which publishes.
3. **`backfill` step 2.** It reads "filename" as if it were a frontmatter field.
4. **`index`.** In the sort order "status, then concluded, PR, and plan number
   (descending)", it is unclear whether "descending" covers every key or only
   the last.
5. **`pipeline`.** The contract says a run always opens a draft PR; a later
   bullet says a non-GitHub remote opens none. The exception is stated but the
   contract line reads as absolute.
