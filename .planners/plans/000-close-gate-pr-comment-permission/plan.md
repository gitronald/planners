---
id: 0
slug: close-gate-pr-comment-permission
status: done
branch: feature/close-gate-pr-comment-permission
created: 2026-07-08T14:39:15-07:00
concluded: 2026-07-09T01:16:11-07:00
pr: https://github.com/gitronald/planners/pull/6
---

# Handle blocked PR-comment posting in the close review gate

## Plan

### Problem

`close` step 2 (the review gate) mandates posting the review to the PR:

    gh pr comment <number> --body-file <file>

Under Claude Code's auto-permission mode this external write is routinely
**blocked by the auto-mode classifier** — it publishes a self-authored comment
under the user's identity, and "close the plan" does not obviously request
posting a comment. When it's blocked the gate step can't complete as written,
even though the review itself ran fine.

Observed 2026-07-08 (data-voids PR #21): `gh pr comment 21 --body-file ...` was
denied, classifier reason ~ "posting a self-authored review comment … the user
asked to finish and close the plan, not to post a PR review comment." The rest
of the close (`gh pr ready`, `gh pr merge`, branch/worktree cleanup) proceeded
normally — only the publish step was blocked.

### Options (not yet decided)

1. **Document the permission.** In the close instructions, note that posting the
   review needs a Bash allow-rule — `Bash(gh pr comment:*)` (and optionally
   `Bash(gh pr ready:*)`) in `~/.claude/settings.json` (all repos) or the repo's
   `.claude/settings.local.json`. Precedence is deny > allow > classifier, so an
   explicit allow-rule pre-authorizes the command and skips the classifier's
   contextual judgment. Point users at `/update-config`.
2. **Degrade gracefully.** If the post is denied/unavailable, fall back to
   surfacing the review inline and recording that it wasn't posted — the review
   still happened; only publishing was blocked. Don't let a denied comment stall
   the close.
3. **Make posting opt-in.** Consider whether auto-posting a comment under the
   user's identity should be optional in the skill (some users won't want it),
   with inline-only as the default.

### Scope

Edit to the packaged `close` skill text (and possibly a one-line note in the
top-level planners rules about the permission). Keep it brief; likely (1) + (2)
together. `merge` is the consequential, irreversible step and should stay behind
the classifier regardless.

## Log

### 2026-07-09 — implement

Shipped options (1) + (2) together, as anticipated:

- `close.md` review gate: posting the review is now explicitly **best-effort** —
  a blocked `gh pr comment` surfaces the review inline and carries on instead of
  stalling the close. Documented the `Bash(gh pr comment:*)` allow-rule (deny >
  allow > classifier) via `/update-config`, and kept `gh pr merge` behind the
  classifier.
- Extended the same degrade-don't-stall treatment to **`gh pr ready`**, the
  blocked-self-authored-write twin (a draft can't be merged, so a blocked ready
  pauses before merge rather than looping).
- Softened `pipeline.md`'s gate summary to "post it best-effort" for consistency.

Option (3) (opt-in posting) was folded into the best-effort framing rather than a
separate flag. The allow-rule note lives in `close.md` where it's contextual; the
broader permission story became plan 001 (automation levels).

**Review follow-up.** The close review gate flagged one issue: the `pipeline.md`
edit left a 97-char prose line inconsistent with the file's ~78-char wrap.
Re-wrapped the paragraph (commit `413af90`). No code paths changed, so no
regression test applies; `uv run pytest` stayed green (263 passed).

## Retrospective

- The fix split cleanly into "works with zero grants" (graceful degradation) and
  "opt into fewer prompts" (the allow-rule) — keeping both meant the close never
  hard-depends on a permission the user may not have set.
- Finding `gh pr ready`'s identical failure mode mid-implementation was the useful
  surprise: the same class of blocked self-authored write, one step later, where
  it actually pauses the merge instead of being cosmetic.
- Dogfooding paid off — this very close posted its review comment successfully and
  degraded nowhere, but the guidance is now in place for the sessions where it
  won't.
- Scope discipline held: the "should planners grant the permission itself?"
  question was deliberately spun out to plan 001 rather than growing this plan.
