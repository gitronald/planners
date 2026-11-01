---
id: 19
slug: resumable-start
status: done
branch: feature/resumable-start
created: 2026-10-28T10:18:56-07:00
concluded: 2026-10-31T15:41:45-07:00
pr: https://github.com/gitronald/planners/pull/61
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
- **2026-10-31T15:28:48-07:00** — PR opened: https://github.com/gitronald/planners/pull/61
- **2026-10-31T15:31:23-07:00** — Added `planners start` and rewrote the implement skill around it.
  - Inventory of the skill against `activate`: `activate` covered status, branch, Log entry, index, and commit. The rest was prose: the base checks, the `.worktrees/` ignore, the base push, the branch and worktree, setup, the branch push, the PR, and `set-pr`. The skill went from 445 lines to about 365.
  - Departure from step 6, decided by the user: `start` does not push. `finish.py` keeps publishing out of `finish` because a permission rule sees only the outer command, and `planners permissions` shows `assist` grants `planners` and `uv run` without `git push`. A push from inside `start` would skip that gate, on a re-run with real code on the branch. It stops and prints the push instead, and a first run stops twice. It does open the draft PR, which publishes nothing the push did not.
  - Departure from step 6: the PR waits for a commit, since GitHub opens none on a branch level with its base. The `pr` step is `skipped` until then and a re-run from the worktree opens it.
  - Additions to the listed steps: `ignore` and `push-base`, both in the skill and missing from the plan's list.
  - Step 3 says the branch starts from the activation's base commit. The Log's `Base` sha is the commit before the activation, so a branch from it would lack the activation. A new branch starts at the base's tip instead, which is what the skill did.
  - Step 1 says level with origin. Only behind is refused there: ahead is the usual state, with the plan's own commits, and `push-base` handles it with the sorted report.
  - Stricter than the old skill, as this plan specifies: a dirty main checkout stops `start`, where the skill left unrelated changes alone.
  - Setup finishing is recorded in a marker under the worktree's git directory, since a hook's result cannot be read back and a `.venv` can be a sync that stopped partway.
  - Checks at c9e9ed3: 663 tests pass with coverage 94.83%, ruff and pyrefly clean, and the start and entry tests pass on Python 3.11. Run on this plan from its worktree, `start` opened this PR through real `gh`. The other paths ran against a bare local remote and a fake `gh`, so the base-push and branch-push stops have not run against GitHub.
  - This plan's branch is `feature/resumable-start` because it was activated with the installed 0.13.4, which predates the `feature/<NNN>-<slug>` default.
- **2026-10-31T15:33:19-07:00** — Implemented: 9 commits ahead of `dev`.
- **2026-10-31T15:41:56-07:00** — Review gate on PR 61 at medium level, posted to the PR. Fixed in 88cf802; checks after it: 666 tests pass with coverage 94.87%, ruff and pyrefly clean.
  - Review follow-up, actioned with tests: a `.gitignore` commit that failed no longer blocks the re-run (a file differing from HEAD by the rule alone is pending, any other edit is still a dirty tree); a `.claude/` copy that stopped partway no longer reads as finished setup (built beside the marker and renamed in); the PR body link uses the URL `gh` reports, for an enterprise host.
  - Review follow-up, actioned under existing tests: the upstream lookup moved to `proc.upstream` for all three callers, and the worktrees directory name to `entries.WORKTREES_DIR`.
  - Review follow-up, conscious no-ops: run from a linked worktree holding the base, the ignore rule lands on the base while the new worktree sits under the main checkout, which is cosmetic and ends when the base merges; `start._shown` and `cli._shown` have different contracts.
  - Rejected in verification: `_uncommitted`'s slicing of porcelain output, since `must` does not strip it; the second `git worktree list`; the repeated detection in `_start_pr`.
  - Not verified: the base-push and branch-push stops against GitHub, as noted above, and the enterprise link against a real enterprise host.
- **2026-10-31T15:43:46-07:00** — Merged `dev` after the close commit, since plan 020 landed there and GitHub reported the PR as conflicting. `CHANGELOG.md` was the only conflict, resolved by keeping both entries. Plan 020's check that every command is accounted for failed on `start`, so `start` is now listed among the guarded commands. Checks on the merged tree: 711 tests pass with coverage 94.84%, ruff and pyrefly clean.
  - `concluded` stays at the commit `conclude` read, which predates this merge and the one-line test change.

## Retrospective

- The plan's step 6 had `start` push, and that was the one part that did not survive: a permission rule sees only the outer command, so a push from inside `start` would skip the gate `confirm` exists to open. Stopping with the command to run costs a first run two stops, and it keeps the same reasoning `finish` already follows.
- The skill shrank less than hoped, from 445 lines to about 365. Most of what remains is judgment, so the gain is resumability and not length.
- Both defects the review confirmed were in the plan's own promise, resuming: a step's partial write looked like either a dirty tree or a finished step. When adding a resumable step, test a stop between its write and its commit, or partway through a copy, and not only a stop at the step's boundary.
- A marker for "setup finished" only helps if everything before it is whole. Build a copy aside and rename it in, so the marker never records a partial result.
