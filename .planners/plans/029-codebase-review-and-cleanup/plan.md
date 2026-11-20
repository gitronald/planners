---
id: 29
slug: codebase-review-and-cleanup
status: done
branch: feature/029-codebase-review-and-cleanup
created: 2026-11-20T11:14:12-08:00
concluded: 2026-11-20T11:46:04-08:00
pr: https://github.com/gitronald/planners/pull/81
---

# Review and clean up the codebase

## Plan

### Goal

Act on a whole-codebase review that looked for code to simplify, repeated work to
remove, docs and skill text that disagree with the code, and historical cruft. The
review's report is the sidecar [`review.md`](review.md). This plan records how each of
its fifteen findings holds up against the current tree, decides which to act on, and
orders the work.

### Where the review stands

- The report describes commit `19787b9` (0.18.1a0). The tree has since moved to
  `aad4ae3` (0.19.1a0): sixteen files changed, including `planners/cli.py`,
  `planners/start.py`, a new `planners/aftermerge.py`, and a rewrite of the `pipeline`
  skill.
- The reviewer could not run anything, so its findings rest on reading the code.
- Each finding was checked again at `aad4ae3`, by reading the code it names and, where
  it was cheap, by running it. Fourteen of the fifteen still hold; one (D2) is mostly
  superseded.
- The review found no legacy shims left to remove and judged the README command list
  current. It did not measure CLI start-up time, and it does not claim to have found
  every unused name.
- Nothing added after `19787b9` has been reviewed. That includes
  `planners/aftermerge.py` and the 0.19.0 changes to `start` and `index`.

### Assessment of the findings

Line numbers are the current tree's (`aad4ae3`), not the report's. "Reproduced" means
the behavior was run in a scratch repository. "Read" means the code was read and the
claim follows from it, with no run.

| ID | Finding | Holds at `aad4ae3` | Checked by | Decision |
|---|---|---|---|---|
| S1 | `review` crashes on a plan that is not valid UTF-8 | yes | reproduced | fix, narrowly |
| S2 | a re-run of `start` reports the PR step done while the PR record is uncommitted | yes | read | fix |
| S3 | `tests/test_cli.py` duplicates helpers it imports | yes | read | fix |
| O1 | a first activation detects the mainline three times | yes | read | leave, see below |
| O2 | index checks parse every plan twice | yes | read | leave |
| O3 | `review` repeats identical `git show` and `git log` calls | yes, in part | read | leave, see below |
| O4 | every test runs `git init`, pure unit tests included | yes | measured | leave |
| D1 | the `close` skill's no-PR section contradicts its opening | yes | read | fix |
| D2 | the `pipeline` skill calls a run finished before the merge | mostly superseded | read | one sentence |
| D3 | the core rule forbids what two skills instruct | yes | read | fix |
| D4 | the `add` skill puts the subplans table in the wrong place | yes | read | fix |
| D5 | the `add` skill's finalize guarantee omits a failed commit | yes | read | fix |
| D6 | `log` leaves an already-repaired index out of its commit | yes | reproduced | fix |
| C1 | a docstring names a constant that no longer exists | yes | read | fix |
| C2 | the deferred-add test asserts on an unrelated slug | yes | read | fix |

**S1.** `_load` reads each plan at `planners/review.py:584`, outside the `try` that
follows it, and that `try` catches only `PlanError` (`:587`). The CLI catches only
`ReviewError` around the gather (`planners/cli.py:3092`). With one plan file holding
bytes that are not UTF-8, `planners review` exits 1 with a `UnicodeDecodeError`
traceback. `PlanMetadata.from_file` already turns a read or decode error into a
`PlanError` (`planners/metadata.py:220`), and the same function already tolerates an
unreadable subplan (`planners/review.py:601`). The report proposes a shared discovery
and loading seam for the CLI and `review` (size L). The crash needs far less: read
inside the `try` and report the plan as skipped, as a plan that fails to parse is.

**S2.** `_start_pr` returns "done" as soon as the working copy of the plan has a `pr`
value (`planners/cli.py:2194`). `_set_pr` writes the URL and the Log entry before it
commits (`:1577` to `:1586`), and on a re-run it can tell a pending record from a
committed one (`:1563` to `:1573`). `start` does not reach that check: a re-run takes
the early return, and `check_branch_pushed` compares commits only
(`planners/start.py:455`), so an uncommitted record passes it. The record is left
uncommitted after a `plan [pr]` commit that a hook rejected, although the `implement`
skill says to run `start` again after any interruption. This was not reproduced: it
needs a hook that rejects that one commit. It is narrow, and the fix is to route a
recorded URL through `_set_pr` before reporting the step done.

**S3.** `_commit_all` (`tests/test_cli.py:831`) repeats `commit_all`
(`tests/helpers.py:37`), `_git_log` (`:837`) is `git_out(path, "log", "--oneline")`
(`tests/helpers.py:46`), and `_write_staged` (`:577`) has the same body as
`_write_plan` (`:21`). Between them they have about two dozen call sites, all in that
file. The dated commit helper in `tests/test_review.py` is a different helper and
stays.

**O1.** On a first activation that commits, `detect` runs from `_guard_base_branch`
(`planners/cli.py:535`), from `_activation_entry` (`:1481`), and from
`_current_branch` (`:1499`), which wants only the branch name. Each `detect` is up to
six git processes (`planners/base.py:152`). The repeat is real. Its cost was not
measured, and a dozen short git calls in a command that then commits is unlikely to
be felt.

**O2.** `validate` parses each plan in its own loop and again inside
`_index_is_stale` (`planners/cli.py:3440`, `:575`). `log` and `finish` call
`_index_is_stale` and then `_refresh_index`, which parses them again (`:2643`,
`:2097`, `:615`). At this repo's thirty plans the cost is negligible, and passing
parsed metadata between these functions would couple them for no visible gain.

**O3.** `_Git` caches trees, tags, and whether `origin` exists
(`planners/review.py:343`), and its `show` and `log` are not cached (`:392`, `:397`).
That much was confirmed. The report's count, five subprocesses for two distinct
queries on one fixture, was not checked. `review` is run rarely and by hand, so this
is left until a run of it on a large repo is shown to be slow.

**O4.** The fixture is as described (`tests/conftest.py:54`). Measured: the seven
pure-unit test files hold 210 tests and run in 1.3 seconds together, and 150
`git init` calls take 0.5 seconds. The full suite takes about 33 seconds. Making the
fixture opt-in would save well under a second and would put a marker on every CLI
test module.

**D1.** The `close` skill's opening says any remote kind but `github` takes the no-PR
path without being asked (`planners/prompts/skills/close/SKILL.md:30`). The section
for that path opens with "Used only when the user asks for it" (`:247`). It then runs
`gh pr list` before any step (`:257`), pushes the closing commit on the feature
branch (`:274`), and runs `git pull` and `git push` on the base (`:285`, `:287`), none
of them conditioned on the remote. With no remote those commands fail, and on a
`single-branch` remote `start` never pushed the feature branch. The opening does
cover the one case that publishes (ask before the base's push on `single-branch`).

**D2.** The finding was written against the earlier `pipeline` skill. The current one
says the run ends at `status: done`, merged, with `finish` done
(`planners/prompts/skills/pipeline/SKILL.md:29`). What remains is its rule for
resuming a `done` plan: "Run `finish` if the worktree is still there, and stop"
(`:60`). `conclude` writes `done` before the merge, so a run interrupted between the
two resumes into a `finish` that stops and prints the merge command
(`planners/cli.py:1946`, `:1962`). The skill should say that this stop means the
merge is still owed.

**D3.** The always-on rule says of plan commit subjects "Do not write one by hand"
(`planners/prompts/rules/planners-core.md:19`). The `add` skill gives a hand-written
`plan [add]` commit for the `--no-commit` path
(`planners/prompts/skills/add/SKILL.md:65`), and the `implement` skill gives a
hand-written `plan [activate]` commit for a nested subplan
(`planners/prompts/skills/implement/SKILL.md:242`). The same rule says `plan [add]`
and `plan [activate]` belong on the mainline (`:15`), while a reactivation skips the
guard (`planners/cli.py:1400`) and the `add` skill says a nested subplan under an
active umbrella commits on the current branch. The full rule gives one subject form
(`planners/prompts/rules/planners.md:296`), while a batch `finalize` writes a range
and a count (`planners/cli.py:1233`) and `review` writes a count (`:2990`). The guard
on a nested `add` was not read.

**D4.** The skill says the table goes "at the top of that section when there are no
subsections yet" (`planners/prompts/skills/add/SKILL.md:100`). The code inserts at the
section's end, after its lead paragraph (`planners/body.py:140`), and its docstring
says so.

**D5.** "A refused finalize leaves the batch staged and recoverable, nothing
half-materialized" (`planners/prompts/skills/add/SKILL.md:239`) is true of the two
refusals, the mainline guard and the validation pass (`planners/cli.py:1116`,
`:1187`). It says nothing about a commit that fails after the plans are written
(`:1197` to `:1235`), which leaves numbered plans uncommitted and the staging
directory empty.

**D6.** `log` adds the index to its commit only when `_index_is_stale` says so
(`planners/cli.py:2643`), and that compares the working file with a fresh render
(`:572`). When the index was already regenerated and left uncommitted, the working
file is fresh, so the index is left out. Reproduced: with a stale index committed
and `planners index .` run after it, `planners log` committed the plan alone and
left the index modified. The docstring (`:2598`) and the `update` skill
(`planners/prompts/skills/update/SKILL.md:122`) both name this case as handled.
`finish` handles it, by also staging an index that differs from HEAD (`:2099`). The
failure the docstring warns of, the validate hook rejecting the commit once
pre-commit stashes the repair, was not reproduced. Since 0.19.0 the `post-merge` hook
puts the repair into the merge commit when it can, so this is reached only where the
hook leaves the repair uncommitted, or after `planners index .` run by hand.

**C1.** The `_index_is_stale` docstring says "see `install.INDEX_MERGE_ATTR`"
(`planners/cli.py:557`). There is no `planners/install.py`, and the declaration is
`planners.host.INDEX_ATTR` (`planners/host.py:93`), which `planners/index.py:19`
already names.

**C2.** `test_add_defer_stages_unnumbered_plan` creates `my-feature` and then asserts
that `000-alpha` does not exist (`tests/test_cli.py:602`). The assertion cannot fail,
so the test would pass if `--defer` also wrote a numbered plan.

### Decisions

1. **Fix the three behaviors, each with a regression test:** S1, D6, and S2.
2. **S1 gets the narrow fix.** The shared loader the report proposes is not part of
   this plan. It is a refactor of working code with different error reporting on
   each side, and the crash does not need it.
3. **D6 follows `finish`.** `log` stages the index when it is stale or when it differs
   from HEAD and matches a fresh render. An index edited by hand to something else is
   still left alone.
4. **Fix the five docs findings in the prompts:** D1, D2, D3, D4, and D5. These are
   text the installed skills and rules carry into every session, so a wrong line
   costs more than its size suggests.
5. **Do the three cleanups:** C1, C2, and S3.
6. **Leave the four optimizations.** O4 was measured and saves under a second. O2 is
   negligible at this size. O1 and O3 are real repeats with no measured cost; either
   can come back as its own plan with a timing that shows it matters.
7. **Skill text follows the repo's prompt conventions:** about 85 characters wide,
   `{cli}` for the command name, and `metadata.version` unchanged.

### Order of work

One commit each, lowest risk first. The subjects are suggestions.

1. C1: `update index docstring to name host.INDEX_ATTR`
2. C2: `update deferred add test to assert on its own plan`
3. S3: `remove duplicate helpers in the cli tests`
4. D4 and D5: `update add skill on table placement and finalize`
5. D3: `update core rule for the hand-written plan subjects`
6. D1: `update close skill's no-pr path for each remote kind`
7. D2: `update pipeline skill for a done plan not yet merged`
8. S1, with a test: `fix review crash on a plan that is not utf-8`
9. D6, with a test: `update log to commit an index repair left unstaged`
10. S2, with a test: `update start to commit a pending pr record`
11. `CHANGELOG.md`: an entry under `[Unreleased]` for S1, D6, S2, and the skill and
    rule changes.

After 5, 6, and 7, check that the rendered prompts carry no leftover `{cli}`, and
that `planners install --check` reports what a reinstall would change.

### Out of scope

- The shared plan-loading seam (the larger half of S1), and O1 to O4.
- A review of the code added after `19787b9`.
- CLI start-up time, which the review did not measure.
- Rewriting any plan file. They are records.

### Not verified

- S2 and the hook failure in D6 were read, not run.
- The report's subprocess counts for O1 and O3.
- Whether a nested `add` under an active umbrella skips the mainline guard (D3). The
  `add` skill says it does.
- The review's negative results (no legacy shims left, README current) were not
  re-derived.

## Log

- **2026-11-20T11:31:58-08:00** — Activated.
  - Branch: `feature/029-codebase-review-and-cleanup`
  - Base: `dev` at `69ae1bd`
  - Worktree: `.worktrees/029-codebase-review-and-cleanup`
  - PR: pending
- **2026-11-20T11:35:03-08:00** — PR opened: https://github.com/gitronald/planners/pull/81
- **2026-11-20T11:40:35-08:00** — Implemented all eleven steps of the order of work, one commit each, in the order given. The checks ran clean at `63b5148`, level with `dev`, which had not moved: `ruff check`, `ruff format --check`, `pyrefly check`, and `pytest` (846 passed, coverage 95%).
  - What was done: C1 `5f64268`, C2 `7634829`, S3 `54c650f`, D4 and D5 `082bfde`, D3 `ba0253a`, D1 `78c5075`, D2 `b95815a`, S1 `48036d7`, D6 `15bf8c8`, S2 `1573bd4`, changelog `63b5148`.
  - Each of the three behavior fixes has a regression test that was run with the fix reversed and failed, then passed with it restored.
  - Now verified, where the plan said read or not verified: S2 (without the fix, a re-run of `start` after a refused `plan [pr]` commit prints `done pr` and leaves the record uncommitted); the hook failure in D6 (a stand-in hook that reads the staged index rejects the commit of the plan alone); the nested `add` guard in D3 (skipped when the umbrella is `active`); and D5 (in a scratch repository, a `finalize` whose commit a hook rejects leaves the plans numbered and added to git's index, staging gone, and a second `finalize` finds nothing staged).
  - Departures from the spec: C2 asserts that nothing at all is under `plans/`, which is stricter than a check on the plan's own name; the report's added check that HEAD stays unborn was not written. D3 also names two cases the plan did not list: a nested subplan activated on the umbrella's branch, and a blocked plan returned on its own branch. D5 gives the recovery as well as the state (commit the paths with the subject the error names, do not run `finalize` again). D6 also corrects the `update` skill's sentence on it. S2 moves the pending-record test into one helper, `_pr_record_pending`, that `set-pr` and `start` both call. D1 adds that step 5's `pr:` check is skipped on the no-PR path.
  - Surprises, left alone: with no remote, the stop `finish` prints for an unmerged branch still ends in `&& git push`, since only a `single-branch` remote gets the wording without it (`finish --print-merge`, which the `close` skill uses, prints the merge alone). Two plans deferred in the same second were numbered in the reverse of the order they were staged in; the cause was not looked into.
  - Prompt checks: no rendered skill or rule carries a leftover `{cli}`. Run from this branch's build, `install --check` reports the two rule files as drifted, which is what a reinstall would change; nothing was reinstalled.
  - Not verified: the no-PR close was not run end to end on a `none`, `bare`, `other-forge`, or `single-branch` remote. Its table rests on reading `start` and `finish`, on the existing `finish` tests, and on running `git fetch`, `git pull`, and `git push` in a repository with no remote (the fetch exits 0, the other two fail). The review's negative results and its subprocess counts for O1 and O3 remain unchecked, as the plan says.
- **2026-11-20T11:40:40-08:00** — Implemented: 13 commits ahead of `dev`.
- **2026-11-20T11:46:11-08:00** — Review gate run at medium on PR #81 (two finders, one verifier); review posted to the PR. One commit followed it, `838b780`, and the checks ran clean after it: ruff check, ruff format --check, pyrefly, pytest (846 passed, coverage 95%).
  - Review follow-up: three nits survived of nine candidates. Actioned: the two log index tests repeated the duplicated-row setup; they now share `_commit_a_duplicated_row` and `_assert_log_committed_plan_and_index` (a test-only change, so no new regression test). Conscious no-op: `log` takes an untracked index that matches a fresh render into its commit, as `finish` does, and the index is tracked by design. Conscious no-op: `start` checks for a pending PR record and `set-pr` checks it again, two extra git calls on a rare re-run; `set-pr` needs its own check. Rejected: the pending path commits the whole plan file, which `set-pr` already did on `dev`.

## Retrospective

- Re-checking every finding at the current tree before deciding paid off: the report was two releases old, one finding (D2) was mostly superseded, and the line numbers had all moved.
- Choosing the narrow fix over the report's proposed seam (S1: catch the read error in `_load`, not a shared discovery layer) kept the change small and left the larger refactor for a plan that wants it.
- Reversing each behavior fix and watching its test fail turned three findings the plan had only read (S2, D6, D5) into verified ones.
- The doc findings (D1, D3, D4, D5) came from skill and rule text that had drifted from the code. Checking a skill's claim against the code it describes, as the close skill's remote table was checked against `finish`, is worth a step in any plan that edits prompts.
- Left open, and owned by no plan yet: the `finish` stop message with no remote ends in `&& git push`, two deferred plans finalized in the same second were numbered in reverse, and O1 to O4 (repeated work) were left as is.
