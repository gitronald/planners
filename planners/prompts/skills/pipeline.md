---
name: pipeline
description: Drive a plan end to end — implement, do the work, then close — pausing only at the review gate. Use when the user wants a plan taken from draft to done in one run.
---

# pipeline — drive a plan from implement to close

Take a single plan all the way to a terminal status in one driven run: load
`implement`, do the implementation work, then load `close` — pausing only at
`close`'s review gate for human approval. Parse the plan number or path from the
request; if ambiguous, glob `.planners/plans/{NNN}-*/plan.md`.

This is an orchestrator, not new mechanics: every step is an existing subskill
(`{cli} skill implement`, `{cli} skill close`) run in sequence. It exists so
"take 021 to done" is one instruction instead of a hand-managed relay between
stages.

## Completion detection

The plan's frontmatter `status` is authoritative: the run is done when `status`
reaches `done` (or `retired`). A merged PR is the supporting signal, not the
gate — confirm the frontmatter, not just GitHub. Re-read the plan file at the end
of each stage rather than trusting in-memory state.

## Stage handoff contract

The stages hand off through the plan's on-disk state, so each can verify the
previous one landed before it starts:

- **implement** leaves: `status: active`, `branch:` filled, a `.worktrees/`
  worktree on that branch, and an open **draft** PR.
- **close** requires exactly that state to begin — `status: active` with a
  branch, worktree, and draft PR. If any piece is missing, the handoff failed:
  stop and report rather than improvising.

Check the contract between stages; do not paper over a missing piece.

## Execution model

Run the stages **in the same agent, sequentially** (load `implement`, act, load
`close`, act). One agent carries the plan's context straight through, so the
handoff is just on-disk state with nothing to serialize across a boundary —
simplest and least error-prone for a single plan.

Delegating each stage to its own background agent is a valid alternative when you
want failure isolation (a crashed stage can't poison the next) or are driving
many plans at once — but then the handoff contract above is the *only* shared
state, so each delegated stage must re-read the plan and re-verify the contract
before acting. Keep this chaining convention identical to any consumer-side
pipeline-loops convention so the loop is defined once, not twice.

## Human-input points

`close` stops at a **mandatory review gate** (review the PR diff, post it, fix or
consciously no-op every finding) before it merges. The pipeline **pauses** at
that gate — it does not abort and does not merge unreviewed. Surface the review,
wait for approval, then resume `close` from the gate (final log, retrospective,
closing frontmatter, merge, cleanup). This is the one expected pause in an
otherwise unattended run.

## Steps

1. Read the plan; if `status` is already `done` or `retired`, stop — it is closed.
2. Run **implement** (`{cli} skill implement`) and follow it to a draft PR.
3. Do the implementation work, committing and pushing in logical chunks.
4. Run **close** (`{cli} skill close`); pause at the review gate for approval.
5. On approval, finish `close` through merge and cleanup.
6. Confirm the plan's `status` is `done` (or `retired`) and report what shipped.
