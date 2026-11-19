---
name: pipeline
description: Drive a plan end to end — implement, do the work, then close — pausing only at the review gate. Use when the user wants a plan taken from draft to done in one run.
metadata:
  version: "1.0.0"
---

# pipeline — drive a plan from implement to close

Take one plan to a terminal status in one driven run: start it, get the work
done and reviewed, pause once for approval, then close it. Parse the plan
number or path from the request; if ambiguous, glob
`.planners/plans/{NNN}-*/plan.md`.

This session is the **orchestrator**. It runs the lifecycle commands, checks
each handoff, talks to the user, and takes the merge. The work and the review
each run in a **worker**: a subagent, or a headless session, with a context of
its own. One context that also does the work fills with file reads, test
output, and the diff long before the close.

## Stages

| Stage | Runs in | Follows | Ends with |
|---|---|---|---|
| 1. Start | this session | `implement`, steps 1 and 2 | `status: active`, a branch, a worktree |
| 2. Work | a worker | `implement`, steps 3 to 5 | `status: implemented`, everything pushed |
| 3. Review | workers, one at a time | `close`, steps 1 and 2 | each finding fixed or a recorded no-op, checks clean |
| 4. Gate | this session and the user | | the user's approval |
| 5. Close | this session | `close`, steps 3 to 6 | `status: done`, merged, `{cli} finish` done |

Every step is an existing subskill's. Print `{cli} skill implement` at stage 1
and `{cli} skill close` at stage 3, not both at the start. Keep this session's
shell on the main checkout, and reach the worktree with a subshell
(`(cd <worktree> && ...)`).

**The plan on disk is the run's state.** Once the plan has a worktree, the
copy there is the current one: the base's copy stays `active` until the merge.
Its frontmatter `status` says how far the run is, and `done` (or `retired`)
ends it; a merged PR supports that and does not replace it. When a worker has
reported, check its stage's *Ends with* by command, not from the report: that
frontmatter, and `git status -sb` in the worktree, which shows anything
uncommitted or unpushed. If a piece is missing, the handoff failed: stop and
report rather than improvising. A plan still `active` after the stage 2 worker
has reported means `{cli} implemented` refused or never ran.

**Before the first worker starts**, log the choices the user made for the run
(which review, which close) with `{cli} log`, from the worktree. They are then
on the branch, not only in this session.

**After an interruption or a compacted context**, read that frontmatter and
the end of the Log:

- `draft`, or `active` with no worktree: stage 1. Run `{cli} start {NNN}` again
  from the main checkout; it resumes.
- `active`: stage 2. Uncommitted changes in the worktree can mean a worker is
  still at work. Wait for its message or ask the user, and never start a
  second worker in a worktree that has one.
- `implemented`: stage 3, or stage 4 once the Log ends with a
  *Review follow-up* entry.
- `done` or `retired`: closed. Run `{cli} finish {NNN}` if the worktree is
  still there, and stop.

**A plan that is a few edits to a file or two** runs in this session instead:
follow `implement`, then `close`, as written. Say at the start which way the
run goes.

## Keeping this session small

- **Read the plan once**, at stage 1. After that, and where `close` says to
  read the plan, read its frontmatter (the first ten lines), its `## Handoff`,
  and the last few entries of its Log, not the whole file.
- **Do not read the code or the diff here.** Check a claim with a command that
  has a short answer (`git log --oneline <base>..HEAD`, `git diff --stat`), or
  leave it to the reviewer. Do not fix code here either: a failure goes back
  to a worker.
- **Send long output to a file** in the scratch directory and read the exit
  status. Read the end of the file only when the command fails.
- **Wait for a worker's final message.** Do not poll it or read its
  transcript.
- **What has to outlast this session goes in the plan**, when it arises: the
  work in the Log, open questions in `## Handoff`.

## Workers

Use a subagent by default. Use a headless session (`claude -p` under Claude
Code) when the harness has no subagents, when the stage is long enough to walk
away from, or when the user asks. Name the model for each: the work and the
review both turn on judgment.

One worker at a time is not a fan-out. Run workers in parallel **only when the
user asks for subagents or a workflow**, and follow `{cli} doc
orchestrated-run` first.

Every brief names the plan, the worktree to run every command from, the repo's
checks, what must not run or be written, the decisions the user has already
made, and where to stop. **No worker merges the plan's branch into the base,
closes the plan, or runs `{cli} finish`.** A worker cannot ask the user:

- A question that does not stop the work goes in the plan's `## Handoff`, and
  the worker carries on with what does not depend on it.
- A step that needs a person is marked `blocked`, and the run carries on.
- A finding that would change the plan stops the worker, which reports it.

A headless worker's brief adds two things: note a refused command and do not
reword it, and stop at the stopping point even where the instructions go on.
Write that brief in the scratch directory, outside the repository, since
`start` refuses a tree with an untracked file. Launch the session in the
background.

**The work brief.** Run `{cli} rule planners` and `{cli} skill implement`.
Step 2 is done; follow steps 3 to 5 and stop after `{cli} implemented {NNN}`
and its push. Log what the commits did and where the work departed from the
plan with `{cli} log`. Then report, in under 40 lines:

- the status reached, and the commits and whether they are pushed;
- each check with its exit status and the commit it ran at;
- departures from the plan, and what would help next time;
- what is not verified, every refused command, and the open questions.

**The review brief.** Review the branch's diff against the base with the
repo's review skill, and against what the plan asked for. Change no file in
the repository. Report, in under 60 lines, the findings in order of weight,
each with its `path:line`, why it is wrong, and a fix; then what was not
checked.

After each worker, run `git status --short` in the worktree and in the main
checkout. A brief is not always obeyed.

## Stage notes

**2. Work, on an umbrella.** `{cli} subplans {NNN}` prints the execution order.
Give each subplan its own worker, one at a time in that order, and run
`{cli} subplans {NNN}` after each. A subplan's brief follows *Implementing one
nested subplan* in `implement` and stops after the subplan's Log entry and
`{cli} subplans {NNN} --set <letter>=done`. The first one also opens the draft
PR (`implement` step 4). The last one also covers the merge of the base, the
final checks, and step 5. A `blocked` subplan does not stop the run: a subplan
that needs it waits with it, and the rest go on.

**3. Review.** `close` step 1 is this session's, except that an umbrella's
`--require-closed` check waits for stage 5. In step 2 the reviewer is a worker
that did not write the code. Save its findings to a file in the scratch
directory: that file is what gets posted, as `close` says, and what the fixing
worker reads. The fixing worker is the one that did the work, continued where
the harness can, since it still holds the code; else brief a new one. It fixes
each finding as `close` step 2 says, with a paired regression test, or says why
it is a no-op, runs the checks, logs a *Review follow-up* entry (raised, fixed,
no-op), and pushes. Then run the check gate here once, output to a file: a
worker's "checks pass" is a report, not a check. A failure goes back to the
worker with that file.

Under a "minimal review" there is no reviewer and nothing is posted. This
session runs the checks. The skim is a worker's, unless `git diff --stat` shows
under two hundred lines: that is the one diff this session may read. What the
checks or the skim find goes to a worker to fix.

**4. Gate.** This is the run's one pause; nothing merges unreviewed. Show the
count of findings and what became of each, the result of the checks this
session ran, the held questions from `## Handoff`, each `blocked` subplan with
the choice `close` gives for it (finish it, or move it to a follow-up plan),
and which close follows. Wait for approval. Finishing a subplan returns the run
to stage 2 for it.

**5. Close.** Write the final Log entry, the Handoff, and the Retrospective
from the workers' reports, then follow `close` through `{cli} conclude`, the
merge, and `{cli} finish {NNN}`, on its no-PR path when that is the close. This
session runs all of it. Confirm the base's copy of the plan reads `done`, and
report what shipped.

## PR or no PR

On GitHub a pipeline always opens a draft PR, so a request for a **no-PR
close** ("no PR, just merge into dev") meets `close`'s conflict rule: the PR
exists, and the request says there should be none. `close` asks which the user
wants. In a pipeline that question waits for the gate's pause; say so up front
when a request names both. When `{cli} remote` reports any kind but `github`,
`start` opens no PR, and on `single-branch` pushes nothing, and `close` takes
the no-PR path on its own. Say at the start which path the run will take.
