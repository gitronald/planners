---
id: 19
slug: resumable-start
status: active
branch: feature/resumable-start
created: 2026-10-28T10:18:56-07:00
concluded:
pr:
---

# Add a resumable planners start command

## Plan

The `implement` skill (about 445 lines of prose) walks a session through steps that are
mostly mechanical: check the base, activate the plan, create the branch and worktree, set
up the worktree, and open the draft PR. A session interrupted partway (a lost VM, a
refused command, a context reset) has to work out by hand which steps already ran. Plan
005 moved activation from prose into code for the same reason; `start` is the next step
in that direction.

### Approach

- Add `planners start <NNN>`, which runs the mechanical steps in order and checks each
  one's result before running it, so a re-run resumes where the last one stopped:
  1. HEAD on the mainline, tree clean, level with origin.
  2. `activate` (already idempotent: an active plan writes no second Log entry).
  3. The branch recorded in `branch:` (default `feature/<NNN>-<slug>`) exists, created
     from the activation's base commit.
  4. The worktree at the recorded path (`.worktrees/<NNN>-<slug>` by default) exists on
     that branch.
  5. Worktree setup the skill describes (environment sync, an untracked `.claude/`
     copied in), reported rather than guessed when the repo needs something else.
  6. The branch pushed with upstream tracking and a draft PR open, recorded with
     `set-pr`.
- Each step prints `done`, `ran`, or `skipped` with the reason, so the output is the
  resume record.
- Shrink the `implement` skill to the judgment it still needs (reading the plan, the
  work itself), and point it at `start` for the rest.

### Order

1. Inventory the skill's mechanical steps against what `activate` already does.
2. Implement `start` step by step, each with a test that re-runs it after a stop at
   that step.
3. Rewrite the skill around it.

### Out of scope

- Closing out (`finish` already covers it).
- Harness-specific setup for other agents (see the Codex harness work in pkgskills).

## Log

- **2026-10-31T15:07:37-07:00** — Activated.
  - Branch: `feature/resumable-start`
  - Base: `dev` at `d34beac`
  - Worktree: `.worktrees/019-resumable-start`
  - PR: pending
