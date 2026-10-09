---
id: 12
slug: review-status-and-activation-log
status: active
branch: feature/review-status-and-activation-log
created: 2026-10-09T13:22:44-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/37
---

# Add an implemented status and a standard activation log entry

## Plan

**Context.** Between `activate` and `close`, a plan reads `active` the whole
time. That one word covers a plan nobody has started, one halfway through, and
one whose code is finished and waiting on review. The plan file also does not
say where the work lives. To check on an active plan, you have to rebuild its
state from git: which branch, which worktree, what base it came from, whether
a PR exists. This plan fixes both gaps: a status for "implemented, awaiting
review" (`implemented`), and a standard Log entry written at activation that records where the
work is.

### Scope

**1. An `implemented` status.**

- Add `Status.implemented`: the implementation is complete and the PR is ready for
  the review gate. It is an open status, like `active` and `blocked`, so
  `concluded` stays empty and nothing closes over it.
- Keep it distinct from `blocked`. `blocked` waits on a person for something
  the work needs (a decision, access). `implemented` waits on a person to accept
  finished work.
- Add it to `OPEN_STATUSES` and to the unfinished set used by `subplans
  --require-closed` and `retire`, so an umbrella cannot close over a subplan in
  the `implemented` status. In the index sort order it goes directly after `active`.
- **Automatic transition.** Add `planners implemented <NNN>`. It flips
  `active` to `implemented`, appends a standard Log entry (below), refreshes
  the index, and commits on the feature branch as
  `plan [implemented]: NNN - <slug>`. When the plan has a `pr`, it also takes
  the PR out of draft by calling GitHub's `gh pr ready`. It refuses a
  plan that is not `active`. The `implement` and `pipeline` skills call it as
  their last step once the work is committed and pushed. The command works
  for nested subplans as well (`implemented 012b`), writing the subplan's frontmatter and
  regenerating the umbrella's table.
- **`implemented` does not close.** It does not merge, write a Retrospective, fill
  `concluded`, or remove a branch or worktree. Those stay in `close`, which
  runs only when the user invokes it. The one duty that moves is taking the PR
  out of draft: the `implement` skill now says the PR stays a draft until
  `close`, and under this plan it leaves draft at `planners implemented`,
  because the `implemented` status means the PR is open for review. `close`
  still runs `gh pr ready` itself for a plan that skipped the step.
- `planners implemented` refuses when the branch has uncommitted changes or commits not
  pushed to its upstream, and says which (question 2). A plan marked
  implemented must match what the reviewer sees on the PR.
- **Back to work.** Review feedback that needs more work flips `implemented` back
  to `active` through `planners activate`. That transition happens on the
  feature branch, so the mainline guard applies only to activating a `draft`,
  `blocked`, or `inactive` plan, not to returning from `implemented`.
- `close` accepts a plan in `implemented` (the normal case) or in `active` (a plan
  that skipped the step).

**2. A standard activation Log entry.**

- `planners activate` appends a dated entry to the plan's `## Log`, creating
  the section if it is missing (before `## Handoff` or `## Retrospective` if
  either exists). The entry is generated, not hand-written, so every plan
  carries the same fields:

  ```markdown
  - **2026-01-01T12:00:00-08:00** — Activated.
    - Branch: `feature/<slug>`
    - Base: `dev` at `abc1234`
    - Worktree: `.worktrees/<slug>`
    - PR: pending
  ```

- `Base` records the base branch and the commit the activation sits on,
  which is HEAD before the activation commit is made.
- `Worktree` defaults to `.worktrees/<branch-suffix>`, the path the
  `implement` skill creates. `--worktree <path>` records a different one, and
  `--no-worktree` records `none (main checkout)`. Paths are always
  repo-relative. An absolute path is refused, so no local path is ever
  committed.
- `set-pr` and `implemented` each append a one-line entry of the same form
  (`PR opened: <url>`, `Implemented: <n> commits ahead of <base>`). They
  do not edit the activation entry. Together the entries give a timeline that
  reads at a glance: activated, PR opened, implemented. `close` adds the last
  entry when the user runs it later.
- Re-running `activate` on an already-active plan writes no second entry
  (it stays idempotent). Returning from `implemented` writes a short `Reactivated`
  entry.

**3. Docs and skills.**

- Update the status enum text in the schema description, the generated rule,
  and the `update`, `implement`, `pipeline`, and `close` skills.
- Add `implemented` to the `--status` choices of plan 011's `planners review`
  command, if 011 lands first.
- Add a CHANGELOG entry.

### Open questions

1. The status name `review` matches the name of plan 011's `planners review`
   subcommand, which is a different thing (an evidence report on stale
   plans). Keep `review` as the user asked, or use `in-review` to avoid
   confusion? Default: `review`. A third option is `ready`, which matches
   the command that sets it (`planners ready` sets `status: ready`) and
   GitHub's "ready for review". **Answered 2026-10-09: `implemented`, for
   both the command and the status.** `ready` was rejected because it could
   follow any stage and collides with `gh pr ready`.
2. Should `planners implemented` refuse when the branch has uncommitted or unpushed work?
   Default: yes, and say which. **Answered 2026-10-09: yes.**

### Out of scope

- A `planners status <NNN>` command that reads the activation entry and checks
  it against live git (does the worktree exist, how far ahead is the branch,
  what state is the PR in). It is a natural follow-up once the entry exists.

### Order

1. `Status.implemented`, the open and unfinished sets, the index order, and tests.
2. The activation Log entry in `activate`, with `--worktree` and
   `--no-worktree`, and tests.
3. `planners implemented`, the `set-pr` entry, the `implemented` to
   `active` path, and tests.
4. Skills, the rule, and the CHANGELOG.
