---
id: 15
slug: skill-language-review
status: done
branch: update/skill-language-review
created: 2026-10-10T18:29:26-07:00
concluded: 2026-10-10T19:50:19-07:00
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
- **2026-10-10T19:27:54-07:00** — Settled open questions 2 to 5 as edits on this
  branch, one commit each: `implement` names which `single-branch` push
  publishes (step 3) or is rejected (step 4); `backfill` reads identity from the
  directory name; `index` states every sort key after status as descending;
  `pipeline` scopes "always opens a draft PR" to GitHub. `uv run pytest`: 576
  passed after the edits.
- **2026-10-10T19:33:01-07:00** — Settled open question 1: `close`'s minimal
  gate fixes at the source or records a conscious no-op, as the full gate does,
  and needs no paired regression test. This is the one deliberate meaning change
  in the plan; it resolves an ambiguity rather than rewording.
- **2026-10-10T19:38:41-07:00** — Implemented: 13 commits ahead of `dev`.
- **2026-10-10T19:51:00-07:00** — Close review gate: `/code-review` at medium
  on PR #47 (a meaning-drift finder and a consistency finder). The CI gate was
  green before and after the fixes: ruff check, ruff format --check, pyrefly,
  and pytest (576 passed, coverage 94.38%).
  - **Review follow-up.** Four findings. Fixed: `close`'s minimal-gate paragraph
    and `backfill` step 2 still had a long line each, so both are rewrapped
    (`ae65af0`). The CHANGELOG now names the clarity pass and the four
    clarifying edits (`c126422`). The Handoff still called settled questions
    open; it is rewritten in this close. No regression tests: the fixes are
    prose and wrapping, with no behavior to test. A conscious no-op: `close`'s
    and `pipeline`'s one-line summaries of the minimal gate do not mention the
    dropped test, because they do not list the full gate's details either.
    The meaning-drift finder found nothing.

## Handoff

### State

Done. Order steps 1 to 4 are committed on `update/skill-language-review` and
merge with PR #47. Every question below is settled. Not verified: the
installed always-on rule (`planners install`) gets the new principle only
after a release that carries this change is installed.

### Questions (all settled)

These ambiguities came up during the clarity pass. The pass left them alone,
because settling them changes meaning. Questions 2 to 5 were checked against
the CLI code and the skill text on 2026-10-10, with the finding under each.

1. **`close`, review gate.** Does "each with a paired regression test" also
   apply on the minimal-review path? Not answerable from the code: the minimal
   gate says "fix what the skim finds the same way the full gate does", which
   can be read either way. This is a policy decision. *Settled 2026-10-10: no;
   edited in `17627a1`.*
2. **`implement` step 2.** "`single-branch` also changes steps 3, 4, and 7,
   where the push would be rejected or would publish" does not say which push
   is rejected and which publishes. Finding: the skill's own steps answer it.
   Step 3's push of the base publishes (line "On a `single-branch` remote, do
   not push the base"), step 4's `git push -u` is rejected ("the remote rejects
   any branch but its own"), and step 7 skips its push. *Settled 2026-10-10:
   edited in `23c9840`.*
3. **`backfill` step 2.** It reads "filename" as if it were a frontmatter field.
   Finding: identity validates against the plan's directory name, which is read
   alongside the frontmatter, not from it. *Settled 2026-10-10: edited in
   `b86219a`.*
4. **`index`.** In the sort order "status, then concluded, PR, and plan number
   (descending)", it is unclear whether "descending" covers every key or only
   the last. Finding: `sort_plans` in `planners/index.py` sorts status by the
   fixed order and concluded, PR, and plan number all descending (newest
   concluded first, a missing value after a present one). *Settled 2026-10-10:
   edited in `b0d63ee`.*
5. **`pipeline`.** The contract says a run always opens a draft PR; a later
   bullet says a non-GitHub remote opens none. The exception is stated but the
   contract line reads as absolute. Finding: the pipeline's own implement
   bullet already says "Off GitHub ... there is no PR", so "always" is the only
   word out of line. *Settled 2026-10-10: edited in `671d9b9`.*

Questions 2 to 5 were settled on 2026-10-10: the user chose to edit each on this
branch so the text matches the code, one commit per question. Question 1 was
settled the same day: no paired regression test on the minimal path, since what
the skim looks for mostly has no behavior to test and a test per fix would undo
the lighter gate the user asked for.

## Retrospective

- Reading every hunk for drift caught two edits a test suite could not. One
  dropped an "always". The other turned a statement of fact into an
  instruction. A prose pass needs that read as its gate, not pytest alone.
- Holding the ambiguities as numbered questions kept the clarity pass
  meaning-neutral. Four of the five turned out to be answerable from the code
  or the skill's own text. Only one needed a policy decision.
- One commit per settled question made each meaning change easy to review and
  cite. The Handoff answers point at those commits.
- The pass left long lines in two edited paragraphs, and the review caught
  them. A length check on touched lines (`awk 'length>88'`) before the gate
  would have found them sooner.
- The CHANGELOG first listed only the deliberate meaning changes. Text that
  `planners skill` prints is user-facing, so a rewording pass gets an entry
  too.
