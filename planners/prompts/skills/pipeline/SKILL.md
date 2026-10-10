---
name: pipeline
description: Drive a plan end to end — implement, do the work, then close — pausing only at the review gate. Use when the user wants a plan taken from draft to done in one run.
metadata:
  version: "1.0.0"
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

- **implement** leaves: `status: implemented` (its last step runs
  `{cli} implemented {NNN}` once the work is committed and pushed), `branch:`
  filled, a `.worktrees/` worktree on that branch, and an open PR taken out of
  draft, ready for review. Off GitHub (`{cli} remote` is not `github`) there is
  no PR, and on a `single-branch` remote no pushed branch either.
- **close** requires exactly that state to begin — `status: implemented` with a
  branch, worktree, and ready PR. If any piece is missing, the handoff failed:
  stop and report rather than improvising. A plan still `active` means the
  implement stage did not finish: `{cli} implemented` refused (uncommitted or
  unpushed work, which it names) or was never run.
- A pipeline run always opens a draft PR, so a request for a **no-PR close**
  ("no PR, just merge into dev") meets `close`'s conflict rule at the gate: the
  PR exists, and the request says there should be none. `close` asks which the
  user wants rather than reinterpreting; that question joins the review-gate
  pause rather than adding a second one. Say so up front when the request
  names both a pipeline and no PR.
- The exception is a remote that is not GitHub. When `{cli} remote` reports any
  other kind, implement opens no PR and close takes the no-PR path on its own,
  so a "no PR" request there raises no conflict. Say at the start which path
  the run will take.
- For an umbrella with **nested subplans**, the work is finished when
  `{cli} subplans {NNN} --require-closed` passes: no subplan is `draft`,
  `active`, `implemented`, or `blocked`, and the umbrella's table agrees with the subplan
  frontmatter. `close` refuses until it does.

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

## Umbrellas and orchestrated runs

An umbrella's subplans are worked through in their execution order, one at a
time, in the same agent. Fan them out to subagents **only when the user asks for
subagents or a workflow**; the guidance is *An orchestrated run* in
`{cli} skill implement`, and it applies to the work stage of a pipeline as it
does to a bare `implement`. Two of its points shape the pipeline itself:

- **Questions are held.** Collect open questions as the run goes, write them to
  the plan's `## Handoff` section as they arise, and ask them together at the
  review gate, which is the run's one pause. An interrupted run then loses
  nothing.
- **A blocked step does not stop the run.** A step that needs a human is marked
  `blocked`, with what it waits on in the table's Note column, and the run
  carries on with whatever does not depend on it. It does stop the close: a
  `blocked` subplan is finished or moved to a follow-up plan first.

## Human-input points

`close` stops at a **mandatory review gate** (review the PR diff, post it
best-effort, fix or consciously no-op every finding; or the minimal gate when
the user asked for "minimal review") before it merges. The pipeline **pauses**
at that gate — it does not abort and does not merge unreviewed. Surface the review, wait for approval, then resume `close` from the
gate (final log, retrospective, closing frontmatter, merge, cleanup). This is
the one expected pause in an otherwise unattended run.

## Steps

1. Read the plan; if `status` is already `done` or `retired`, stop — it is closed.
2. Run **implement** (`{cli} skill implement`) and follow it to a draft PR.
3. Do the implementation work, committing and pushing in logical chunks.
4. Mark it implemented: `{cli} implemented {NNN}`, then `git push`. That takes
   the PR out of draft for the review gate.
5. Run **close** (`{cli} skill close`); pause at the review gate for approval.
6. On approval, finish `close` through its step 6: commit and push the closing
   edit, then, from the main checkout, run `gh pr merge` and `{cli} finish {NNN}`.
   The session runs these itself. A step goes to the user only after a call to
   it was refused, quoting the refusal, and never on the assumption that it
   would be.
7. Confirm the plan's `status` is `done` (or `retired`) and report what shipped.
