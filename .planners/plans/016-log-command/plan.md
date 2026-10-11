---
id: 16
slug: log-command
status: implemented
branch: feature/log-command
created: 2026-10-11T15:18:30-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/50
---

# Stamp Log entries and concluded from the CLI, not by hand

## Plan

### Problem

Every Log entry that a lifecycle command writes (`activate`, `set-pr`,
`implemented`, `retire`) is stamped by the command from the clock, at the moment
the entry is written. Two are still hand-written. One is the `log` action of
`/planners update`, together with the close skill's final entry and the dated
entries in nested subplans. The other is the closing `concluded`. For both, the
skill prompts tell the agent to run `date -Iseconds` or `git log --format=%aI
-1`. Nothing enforces that, so an agent sometimes types a plausible timestamp
from memory. At close it sometimes back-fills entries afterwards from nearby
commit times. Either way the record looks real and is not.

Repairing stamps at close only moves the guess. The fix is to take the
timestamp out of the agent's hands where the entry is made. The command that
writes the entry reads the clock, as the other lifecycle commands already do.

### Decisions

1. **`planners log <ref> <note>`** appends `- **<now>** — <note>` to the plan's
   `## Log`, creating the section ahead of `## Handoff` and `## Retrospective`
   when it is missing (the same `append_to_section(..., before=...)` call
   `retire` uses). `<now>` comes from `_now()`, the same clock the other entries
   use. The command takes no option that sets the time.
2. **The ref takes the same forms as `retire`:** `016` for a plan, `016d` for a
   nested subplan, whose entry goes in the subplan's own `## Log`. `_resolve_ref`
   already resolves both.
3. **Multi-line entries.** The close skill's "Review follow-up" sub-entry and
   the headings a subplan entry carries need more than one line. `<note>` may be
   `-` to read from stdin. The first line is the entry's sentence, and each later
   line is indented two spaces under it, kept as written, so `- ` sub-bullets
   nest. A note that is empty after stripping is refused.
4. **Commit by default**, as `add`/`activate`/`retire` do:
   `plan [log]: {NNN} - <summary>`. `--summary` gives the summary. Without it,
   the subject uses the slug, which is what every other plan subject names.
   `--no-commit` writes only. The command carries no mainline guard, because
   log commits belong on the feature branch, where the work is. The index is not
   touched, since a Log entry changes nothing the index shows.
5. **`concluded` is written by a command, not typed.** `planners close-plan`, or
   a `--conclude` flag on an existing command (to be settled in implementation:
   question 1), sets `status: done`. It fills `concluded` from the authored date
   of the last commit on the plan's branch, the rule the close skill states
   today. It also writes `null` for a `pr`/`branch` that was never filled, and
   refreshes the index. This is the same frontmatter step `retire` already owns
   for the other closed status.
6. **The prompts stop telling the agent to stamp anything.** The `update` skill's
   **Log** action, the `close` skill's steps 3 and 5, the `implement` skill's
   subplan entries, and the `add` skill's "A subplan's Log entry" all point at
   the command. The bundled `planners` rule's "Use real timestamps" paragraph
   says the CLI writes them. `review` already stamps from its own `now`. It
   keeps its own path, and its prompt gains a line saying to prefer `planners
   log` for any entry written outside `review --commit`.

### Optional backstop (question 2)

A pre-commit check could catch a hand-typed entry after the fact. It would read
the Log lines the staged diff adds, and fail when a stamp is more than a few
minutes from the commit's time. That is a check at commit time, not a repair at
close, but it only runs where the hook is registered (best-effort, per clone).
It is not required if decision 6 removes the reason to hand-write entries.

### Order

1. `entries.log_entry(when, note)`: a pure function that formats the
   multi-line indent, with tests.
2. `planners log` in `cli.py`, with tests for a plan, a nested subplan, a
   missing `## Log`, stdin input, an empty note, and `--no-commit`.
3. The `concluded` command (decision 5), with tests mirroring `retire`'s.
4. The prompt and rule edits (decision 6), and a reinstall to check that the
   generated rule matches.
5. Changelog entry under `[Unreleased]`.

### Out of scope

- Rewriting existing plans' timestamps. A blame check of every Log line in this
  repo against the commit that added it found no drift beyond the example entry
  in plan 012's spec.

## Log

- **2026-10-11T15:21:13-07:00** — Activated.
  - Branch: `feature/log-command`
  - Base: `dev` at `689fe01`
  - Worktree: `.worktrees/log-command`
  - PR: pending
- **2026-10-11T15:25:26-07:00** — PR opened: https://github.com/gitronald/planners/pull/50
- **2026-10-11T15:27:44-07:00** — Implemented the plan's Order, steps 1-5.
  - What was done: `entries.log_entry` and `planners log` (e707dd3); `planners conclude`, with `--no-pr` added for local merges (e707dd3, then the `--no-pr` commit); the prompt, rule, and README edits; the changelog entry. Checks: ruff, ruff format --check, pyrefly, and 601 tests, all passing.
  - Departures from the spec: `concluded` is the authored date of the last commit past the recorded base that touches more than the plan's own files and the index (merges left out), else HEAD. HEAD alone would date the final `log` commit, which now lands just before `conclude`. `conclude` also takes `--no-pr`, since the no-PR close records `pr: null` even when a PR was opened and closed unmerged. Both written up in decision 5's terms in the close skill.
  - Departures from the spec: the review skill's `now` line also offers `planners log <NNN> "<entry>" --no-commit` for review entries, beside the line the plan asked for.
  - Refactor: retire's unfinished-subplan check moved to `_refuse_open_subplans`, shared with `conclude`; `ahead.commits()` split out of `ahead.count()`.
  - Not done: the global rule was not reinstalled. `install --check` reports it as drifted, and a diff of the installed rule against the new source shows only this plan's edits. Reinstall after the release.
- **2026-10-11T15:27:51-07:00** — Implemented: 6 commits ahead of `dev`.

## Handoff

State: every step in the Order is committed and pushed on `feature/log-command`
(PR #50). The plan is marked `implemented`, awaiting review.

Questions:

1. Should the `concluded` step be a new command (`close-plan`/`conclude`) or a
   flag on an existing one? `finish` runs after the merge, on the mainline,
   which is too late for a `concluded` committed on the feature branch.
   **Answered 2026-10-11 (in implementation):** a new command, `planners
   conclude`, the `done` counterpart of `retire`. It commits `plan [close]`, so
   the close skill's hand-written commit is gone too. Open for the reviewer to
   overrule.
2. Is the pre-commit backstop wanted, or does the command alone suffice?
   **Answered 2026-10-11 (in implementation):** not built. Decision 6 removes
   the reason to hand-write a stamp, which the plan named as the condition for
   leaving it out. Open for the reviewer to ask for it as a follow-up plan.

Not verified: the new close flow (`log` -> `conclude` -> push -> merge ->
`finish`) has not been run end to end on a real plan. Closing this plan is its
first run.
