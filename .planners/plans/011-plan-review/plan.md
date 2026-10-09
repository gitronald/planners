---
id: 11
slug: plan-review
status: draft
branch:
created: 2026-10-09T12:14:51-07:00
concluded:
pr:
---

# Add a review subcommand that checks plans against the repo

## Plan

**Context.** Plans go stale without anyone deciding they should. A draft
written months ago may already be done by a later plan, be half done, rest on
files that no longer exist, or still be open with a different scope than the
one it describes. A manual pass over one repo's open drafts showed the pattern
well. Of seven drafts, one was moot because the files it would import had been
deleted. One was half done as a side effect of a later plan. Five were still
open, and one of those had a real data gap that a later retry mechanism did
not cover. Each draft got a dated Log entry saying what had changed in the
repo since it was created. The steps were mechanical enough to repeat, and the
judgment calls were consistent enough to write down.

This plan packages that pass as `planners review`. A CLI command gathers the
evidence and never writes. A `review` skill holds the procedure and prompts
that turn the evidence into a verdict and a Log entry per plan.

### Scope

**1. `planners review` (CLI, read-only).** It selects plans by status and
prints an evidence report for each one. It never edits a file, commits, or
changes a branch.

- `--status/-s`, repeatable, one of `all`, `active`, `draft`, `done`,
  `retired`, `blocked`, or `inactive`. The default is `active`, `draft`,
  and `blocked`, the open statuses (question 1). `all` is shorthand for
  every value in the enum and cannot be combined with the others.
- A positional plan ref (`011`, `012d`) reviews one plan, whatever its status.
- `--json` emits the same report in machine-readable form for the skill, so
  the prompt does not parse prose. It includes a `now` field, the command's
  own `date -Iseconds`, for the skill to stamp Log entries with.
- `--stale-days N` (default 14) sets the idle threshold for active and
  blocked plans in section 3.
- A repo still on the legacy `docs/plans/` + `TODO.md` layout is refused
  with a non-zero exit and a pointer to the migration. `review` reads only
  `.planners/`.
- For each plan, the evidence is:
  - frontmatter, title, and `created`;
  - the repo's commits since `created` on the mainline, excluding the
    tool-written `plan [...]` and `version [...]` subjects, plus the tags and
    releases in that window;
  - the code references the plan names: backticked paths, modules, and
    functions, each marked present, missing, or changed since `created`
    (`git log --since=<created> -- <path>`);
  - other plans the body names (`plan NNN`), with their current status;
  - for `active` and `blocked` plans, the branch state: whether `branch`
    exists locally or on the remote, commits ahead of the mainline, whether a
    worktree has it checked out (`git worktree list --porcelain`), whether
    that worktree is dirty, and the PR state when `gh` is available.
- Missing `gh`, a missing remote, or a shallow clone downgrades the matching
  field to `unknown`. None of them is an error.
- The report opens with a short summary table, with status as the index:

  | status | plans | commits | creation_date | closed_date | last_date |
  |---|---|---|---|---|---|
  | active | 1 | 4 | 2026-10-09 | | 2026-10-09 |
  | draft | 7 | 9 | 2026-06-10 | | 2026-10-09 |
  | done | 12 | 61 | 2026-01-25 | 2026-10-08 | 2026-10-09 |
  | retired | 3 | 6 | 2026-03-02 | 2026-10-07 | 2026-10-09 |
  | total | 23 | 80 | 2026-01-25 | 2026-10-08 | 2026-10-09 |

  `plans` is the count of plans with that status. `commits` is the number of
  distinct commits that touched those plans' directories
  (`git log --format=%H -- <plan dirs>`). `creation_date` is the earliest
  `created` in those plans' frontmatter, the date the oldest of them was
  opened. `closed_date` is the latest `concluded` among those plans, the
  date the most recent of them was closed. It is empty by default: a status
  whose plans have no `concluded` (every open status, and `inactive`) leaves
  the cell blank, and `--json` gives it as `null`. `last_date` is the
  authored date of the newest of those commits. Rows follow the index's
  status order, a status with no plans is omitted, and a `total` row closes
  the table. The summary covers every status, whatever `--status` selects,
  so the review shows what it left out. `--json` carries it as a `summary`
  list of row objects.

  The table counts top-level plans only; nested subplans are not rows. A
  note under the table names each umbrella with an open subplan (`draft`,
  `active`, or `blocked`), for example `012: 2 of 4 subplans open`, since
  those are invisible in the umbrella's own status.

**2. The `review` skill** (`planners/prompts/skills/review/SKILL.md`). It runs
the CLI, then checks each plan's claims against the code itself: grep, read
the named functions, and run the tests or coverage the plan mentions. It then
assigns one verdict per plan:

| Verdict | Meaning | Default action |
|---|---|---|
| still open | nothing material has changed | log only |
| narrowed | partly done elsewhere | log the remaining scope |
| accounted for | done by other work | propose `retire --into <NNN>` |
| moot | its premise no longer holds | propose `retire --note` |
| unclear | evidence conflicts | log the question, no status change |

Every reviewed plan gets a dated Log entry. The entry names what changed in
the repo since `created`, or since the plan's last review entry, and the
verdict with its evidence (commit SHAs, function names, test counts).

The entry opens with a fixed marker so the next review can find it
(question 3):

    - **2026-10-09T12:09:25-07:00** — Review: narrowed. <evidence>

`planners review` reads the newest marker in a plan's Log and uses its
timestamp as the start of the evidence window in place of `created`, and
reports it as `last_reviewed`. The marker lives in the Log, not the
frontmatter, so the seven-key schema is unchanged. The `review` CLI does not
write markers; the skill writes them with the Log entries.

Every timestamp the skill writes, in a Log entry or a marker, is the report's
`now` or a fresh `date -Iseconds`. The skill never types a timestamp from
memory or estimates one.

For a run of more than about ten plans, the skill checks them in batches and
may hand each batch to a subagent on a smaller model, each returning its
verdicts and draft Log entries as text. The main loop merges them into the
one verdict table; only the main loop writes files or commits.

Retirement is only ever proposed. The skill presents the proposals in a single
table and retires only the ones the user confirms. A review never activates or
closes a plan, and never edits a plan's `## Plan` section; the scope change
for a narrowed plan is written in the Log.

**3. Care with active plans.** Someone else may be working on an active
plan right now, in another session, a worktree, or a branch that is not
pushed yet. The mainline is the wrong place to judge it from. The rules:

- **Read only, always.** The skill never edits an active or blocked plan's
  file, on any branch, and never touches its branch or worktree. Its output
  for these plans is a report section with a suggested Log entry that the
  plan's owner can paste in where the work lives.
- **Judge from the branch, not the mainline.** Evidence comes from the
  branch tip when the branch exists. Uncommitted work in a worktree counts as
  "in progress", not "missing".
- **Lean toward "still open".** "Accounted for" and "moot" are not available
  verdicts for an active plan. The strongest finding is "possibly overlaps
  with <commit or plan>, confirm with the owner", and it is phrased as a
  question.
- **Flag, don't fix.** Staleness signals are reported as observations, never
  as a reason to act. Examples: no commits on the branch for `--stale-days`
  days (default 14), a branch
  that no longer exists, an active plan with no branch, or a merged PR on a
  plan still marked active.
- `blocked` gets the same treatment, since its wait may be resolving outside
  the repo.

**4. Closed plans (`done`, `retired`)**, only when asked for. The check is
for drift, not reopening: whether the deliverable still exists or was later
reverted, whether `pr` points at a merged PR, and whether a `retired` plan's
`moved_to` target exists. Findings are Log entries. A review never reopens a
closed plan.

**5. Where the writes land.** The Log entries for draft, done, and retired
plans go in one commit on the mainline, made by the skill after the user sees
the verdict table. The CLI writes nothing.

The commit is made by a small CLI step, `planners review --commit`, so it
gets the same treatment as the other lifecycle writes: the mainline guard
that `add` and `activate` use (refuse off the mainline, `--allow-branch` to
override), an index refresh, and a tool-written subject,
`plan [review]: <N> plans`. It stages only the plan files whose Log changed
and refuses if any of them is an active or blocked plan. Confirmed
retirements go through `planners retire` as separate commits, as they do
today.

### Implementation order

1. Evidence gathering in a new `planners/review.py`, with tests against the
   fixture repos the existing tests build: status selection, the summary
   table's counts and dates, the subplan note, the commits-since window,
   code-reference extraction, branch and worktree state (including a dirty
   worktree), `--stale-days`, and the legacy-layout refusal. One test
   rebuilds the summary table independently from `git log` and the
   frontmatter and checks the command's output against it.
2. The `review` command in `cli.py`: text and `--json` output, status
   validation, and `--commit` with its mainline guard and active-plan
   refusal.
3. The `review` skill, registered with the others, and the rule summary's
   skill list. Add `planners review` (read-only) to the `assist` permission
   profile, and `planners review --commit` alongside the other self-authored
   lifecycle commits.
4. README, CHANGELOG `[Unreleased]`, and a dry run on this repo's own plans.

### Open questions

1. Should the default also include `blocked`? The request named `active` and
   `draft`. `blocked` is open too, but it waits on a person, so a review
   rarely changes it. Proposed: no, it is reachable with `-s blocked`.
   **Answered 2026-10-09: yes.** The default is all three open statuses;
   blocked plans get the active-plan care in section 3.
2. How far should code-reference extraction go? Backticked paths are reliable.
   Bare function names give false positives. Proposed: paths and
   `module.function` forms only, with the skill doing the rest by hand.
   **Answered 2026-10-09: as proposed** (left to the implementer, who took
   the proposal).
3. Should a review leave a machine-readable marker (for example a
   `reviewed:` line in the Log entry) so the next review can diff from it? The
   proposal is to rely on the last Log entry's timestamp and add nothing to
   the frontmatter.
   **Answered 2026-10-09: yes, leave a marker.** It is a fixed
   `Review: <verdict>.` prefix on the Log entry, not a frontmatter field; see
   section 2.
4. What should the summary's `commits` count? Proposed: commits that touched
   the plan directories, which is cheap and defined for every status. The
   alternative is the commits on each plan's `branch`. That measures the
   implementation work, but it is undefined for drafts and for plans merged
   with no branch.
   **Answered 2026-10-09: as proposed**, commits that touched the plan
   directories. A dry run on one repo showed the cost: every row's
   `last_date` was the same day, because one day's plan-log and close
   commits touched every status group. Recorded as a known limitation, not a
   reason to change the definition.

### Out of scope

- Automatic retirement or status changes of any kind.
- Reviewing nested subplans on their own; a subplan is covered as part of its
  umbrella's evidence.
- Cross-repo checks, such as a plan whose work lands in another repo through
  its own PR, beyond reporting the `pr` URL's state.

## Log

- **2026-10-09T12:35:34-07:00** — Answered open questions 1-4 (see each
  question). Spec changes: the default status set adds `blocked`, and section
  2 defines a `Review: <verdict>.` Log marker that `planners review` reads as
  the start of its evidence window.
- **2026-10-09T12:37:34-07:00** — Added a `creation_date` column to the
  summary table: the earliest frontmatter `created` among each status's
  plans.
- **2026-10-09T12:37:54-07:00** — Added a `closed_date` column to the summary
  table: the latest frontmatter `concluded` among each status's plans, blank
  when none has one.
- **2026-10-09T12:40:18-07:00** — Filled gaps found on a re-read: the
  `review --commit` step with the mainline guard and a `plan [review]:` subject; `--stale-days` (default
  14); a `now` field in `--json` so the skill never writes a timestamp from
  memory; refusal of the legacy layout; `review` in the `assist` permission
  profile; top-level-only summary rows with a note on open subplans; batched
  checking for large runs; and a test that rebuilds the summary table
  independently.
