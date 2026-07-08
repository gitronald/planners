---
id: 0
slug: close-gate-pr-comment-permission
status: draft
branch:
created: 2026-07-08T14:39:15-07:00
concluded:
pr:
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
