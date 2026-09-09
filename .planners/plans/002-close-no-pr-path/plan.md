---
id: 2
slug: close-no-pr-path
status: draft
branch:
created: 2026-07-13T17:27:27-07:00
concluded:
pr:
---

# Support a no-PR close path in the close skill

## Plan

### Motivation

A user closed a plan with "no PR, minimal review, just merge into dev" — but
the branch already had an open PR (recorded in the plan's frontmatter), so the
close was reinterpreted as "merge through the existing PR, skip the ceremony."
The result was fine, but the instruction and the action diverged: "no PR"
should not silently become "merge the PR."

### Goal

Give the close skill an explicit no-PR path and a rule for conflicts:

1. **No-PR close mode** — when the user asks to close without a PR, merge the
   branch locally (`git merge --no-ff` into the base branch, honoring the
   merge-commit subject conventions), set `pr: null` in frontmatter, and skip
   the PR review/ready/merge steps. Review gate still runs (possibly a
   lighter "minimal review" variant — see below).
2. **Conflict rule** — if a no-PR close is requested but an open PR already
   exists for the branch, STOP and ask: merge via the existing PR, or close
   it unmerged and merge locally. Never reinterpret silently.
3. **Minimal-review variant** — a sanctioned lighter gate (project checks +
   diff skim, no posted review comment) the user can invoke by saying
   "minimal review," instead of the full review→post→fix→verify loop.

### Scope

- Update the `close` skill instructions (and `pipeline`, which embeds close).
- Frontmatter semantics already support it: merged-without-PR is the
  documented `pr: null` case.
