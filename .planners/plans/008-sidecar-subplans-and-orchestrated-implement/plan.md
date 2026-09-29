---
id: 8
slug: sidecar-subplans-and-orchestrated-implement
status: done
branch: feature/sidecar-subplans-and-orchestrated-implement
created: 2026-09-27T00:14:23-07:00
concluded: 2026-09-29T03:19:42-07:00
pr: https://github.com/gitronald/planners/pull/28
---

# Support nested subplans and an orchestrated implement run

## Plan

### Goal

Two ways of working already succeed with `planners` but are documented nowhere, so each session
has to rediscover them:

1. **Nested subplans.** A plan split into files under its own directory, rather than into
   numbered `NNN<letter>` sibling plans.
2. **An orchestrated implement run.** One `implement` of the umbrella that works through the
   subplans in dependency order, fanning independent ones out to subagents.

This plan documents both as supported shapes, and gives them the small amount of tooling that
keeps them honest.

### The nested shape

```
.planners/plans/NNN-<slug>/
  plan.md                  # umbrella: goal, decisions, order, risks, out of scope
  subplans/
    a-<step>.md            # one file per step or workstream
    b-<step>.md
```

- The umbrella keeps everything the pieces share, a subplan table (scope, step, status), and
  the execution order as a one-line dependency chain, e.g. `a -> (b, c, d) -> e`.
- Each subplan has its own `## Log`, and a minimal frontmatter of `status` and `branch`.
- Subplans carry no `id` or `sub`, so they stay out of the index and out of `validate`.
- **The subplan's frontmatter is the status of record, and the umbrella's table is generated
  from it.** Two hand-kept copies drift: the table gets updated because it is what people
  read, the frontmatter does not, and an umbrella can close as `done` with subplans still
  reading `active`. The table's Status column holds only the enum; anything else ("waiting on
  review") goes in a Note column that stays hand-written.
- An empty `branch` means the umbrella's branch. A value names a sub-branch that merges into
  the umbrella's branch, or the branch of a step that lands somewhere else (see below).
- **The umbrella holds decisions, not findings.** It keeps the goal, the numbered decisions,
  the order, the risks, and what is out of scope. The inventory, the research, and the
  measurements behind them belong to the investigation subplan. An umbrella that keeps the
  whole design is still too long after the split and has to be split again.
- **Letters are fixed once assigned**, as plan numbers are. `a` is reserved for the
  investigation from the first split, whether or not one is written yet. Making room for it
  later shifts every letter, which means rewriting every cross-link and leaves earlier Log
  entries naming files by letters they no longer have.
- **A subplan is one node in the order.** An order that needs part of one subplan before
  another and the rest after it, e.g. `c (1-2) -> b -> c (3)`, is a sign that `c` is two
  subplans. Splitting by workstream reads well and orders badly; when the two disagree,
  split by order.
- **A subplan closes when its own work is finished**, not when the effort is. An
  investigation left `active` after its questions are answered reads as work in progress
  when there is none.

**Splitting a plan that already exists.** Sections move to `subplans/` verbatim. Headings are
raised to fit their new file, relative links are repointed, and nothing is condensed or
dropped on the way. The moved text is then diffed against the original, which is how a
dropped instruction gets caught. The split is committed by the session that made it, not
left staged for the next one. The umbrella's Log records the split and what moved where.

**The shape of a subplan's Log entry.** These headings are a suggestion for the skills to
offer, not a schema. Each has earned its place by being the thing a later session went
looking for:

| Heading | Holds |
|---|---|
| What was done | the work, with its commits |
| Departures from the spec | the spec is left as written; each departure and its reason go here |
| Surprises | defects and discoveries outside the step's scope |
| Dead ends | approaches that failed, so they are not tried again |
| Deferred | work passed to a later subplan, named by letter, and repeated in the umbrella's Log |
| Gaps | what the step was meant to cover and did not |
| Not verified | what was not run, not compared, or not looked at |

**Name.** The rule and the skills call this shape **nested subplans**, because that is what
people ask for. "Sidecar" stays the word for any extra file in a plan directory (a script, a
fixture, a data file), which a plan can hold alongside its subplans. **Subplans are nested from now on.** Any
request for subplans gets this shape, whatever words it uses. Lettered sibling plans are
made only when the request describes them, each step with a branch and a PR of its own, and
they stay supported for the plans that already use them. Building the lettered shape by
mistake means folding it back by hand.

**A plan is not split until it needs it.** Most plans are one file and stay that way. The
skills split a plan into nested subplans when it would cross the length guidance, or when
the user asks, and not before. A short plan with a few ordered steps keeps them as a list.

The two shapes, for the rule and the `add` skill:

| Shape | Use when |
|---|---|
| nested subplans | the default whenever a plan is split. One PR into the mainline carries the whole effort |
| `NNN<letter>` subplans | on request only: each step has its own branch, PR, and lifecycle |

One PR for the effort does not mean every step lands through it. Two cases are normal and
stay nested:

- **A step that lands in another repo**, through that repo's own PR. Its subplan records
  that branch, and the PR URL in an optional `pr`.
- **Parallel steps that commit for themselves.** Each gets its own worktree and a sub-branch
  off the umbrella's branch, merged back with `--no-ff`. Two writers in one worktree share
  one git index, so one's commit can carry the other's staged changes. See the two ways to
  run in parallel, below.

A suggested arc for the steps, which `add` can offer as a starting point: investigate or
spike, the work itself in one or more steps, review, then documentation. An investigation
first tends to pay for itself, because its findings change the steps after it.

### The orchestrated implement run

Guidance for the `implement` and `pipeline` skills, used only when the user asks for subagents
or a workflow:

- **Scout first, then fan out.** The orchestrator reads the umbrella and every subplan, then
  groups the subplans into phases from the execution order. Subplans with no dependency between
  them run in parallel; each phase's results are read before the next is launched.
- **Mark the subplan active first.** Before a phase is launched, its subplans are set to
  `active` and that change is committed. A run whose first phase is a spike otherwise has
  nothing to commit, so the branch stays level with the base, the draft PR cannot open, and
  the plan files say nothing is in progress while agents are at work.
- **Lay the groundwork before the fan-out.** The orchestrator lands what the parallel steps
  share before it launches them: the scaffold, and an empty entry for each step in any file
  they would all edit. Each agent then fills in its own entry, and the shared file stays
  the orchestrator's.
- **Two ways to run in parallel.** Pick per phase, and say which in the brief.

  | Way | Git | Fits |
  |---|---|---|
  | One worktree | Agents write files and never touch git. The orchestrator commits each agent's output as its own logical chunk | Short steps whose files do not overlap |
  | A worktree per agent | Each agent has its own worktree, environment, and sub-branch, and commits for itself with the checks green at every commit. The orchestrator merges with `--no-ff` and resolves the conflicts | Long steps where the history of each matters, or where files overlap |

  In neither way does an agent push, merge, or touch a branch that is not its own. With a
  worktree per agent, expect conflicts at the merge, and have each agent mark anything
  temporary it added to keep its own tree working.
- **Disjoint file ownership.** Every agent's brief names the paths it may touch. Work that
  would overlap is sequenced, or the orchestrator stages it outside the tree and places it
  once the owning agent has finished.
- **The orchestrator keeps its own lane.** While agents run it works on files none of them
  owns, and reads the code the plan describes. That reading is where a plan's own errors
  show up.
- **Spikes stay in scratch.** An investigative step writes nothing to the repo; its findings
  come back through the agent's report and land in the subplan's Log.
- **Scratch is not a record.** It may survive the session or it may not, so nothing depends
  on it. The Log entry for a spike carries the steps to repeat it, not only its result. A
  probe script worth running again is committed to the plan directory as a sidecar file. A
  tool the work depends on is installed where the next session will find it. A plan
  never points at a scratch path. When an earlier session's scratch does survive, a later
  one copies from it and builds in its own, since the old outputs are what the earlier
  results were measured on.
- **Questions are held.** Open questions are collected as the run goes and asked together at
  the end. They are written to the plan's Handoff section as they arise, not only into the
  final message, so an interrupted run does not lose them. A step that needs a human (a
  decision, a manual check, access only they have) is marked blocked in the table and the run
  carries on with whatever does not depend on it.
- **Truthful status.** A subplan is marked done only when its checks ran and passed. "Not run"
  and "not verified" are recorded in those words. So is who ran a check: a result the
  orchestrator re-ran is recorded differently from one a subagent only reported. A run that
  a broken script made meaningless is recorded as void, not deleted. A check the user waives
  is recorded as waived, and by whom.
- **Read the evidence, not the summary.** The orchestrator opens what an agent produced (the
  output, the raw numbers) before it uses a claim. Agents report conclusions their own
  evidence does not support: a benchmark that timed a warm cache against a cold one, a
  saving counted twice. A claim that does not survive is logged as untested,
  not dropped.
- **Audit each agent's side effects.** After every hand-back the orchestrator checks the
  tree with `git status`, any place outside the repo the agent was allowed to write, and
  any process or port it started. Briefs are not always obeyed, and an agent's own
  account of what it touched is not a check.
- **Evidence names its commit.** A measurement records the commit it was taken at, and
  whether the source was fetched first. A checkout that is behind its remote gives a
  true result about stale code.
- **Measure again before asking.** A question put to the user carries a number measured
  against the branch as it stands, not one copied from an earlier Log entry. A stale figure
  asks the user to decide on a problem that may no longer exist.
- **Check the seam.** After parallel work is merged, the orchestrator runs the checks on the
  combined tree, from more than one working directory. One step can quietly break what
  another landed, e.g. one renames a setting that the other's code still reads, while
  each branch's own tests stay green.
- **Hand work forward in writing.** What one subplan leaves for a later one is listed in the
  umbrella's Log as well as its own, so the later subplan's re-read finds it.
- **Re-read each subplan before starting it.** Subplans are written together, before any of
  them runs, so the later ones go stale as the earlier ones land: names that have changed,
  numbers that have moved, work that is no longer needed. The orchestrator checks the
  subplan against the branch as it stands and logs the corrections. It does not rewrite the
  spec.
- **One shared brief.** The rules every agent in a fan-out follows are written once, to a file
  each agent reads first: where to work, what it must not touch, the repo's standing rules
  (no git, no recursive deletes, how to run the interpreter), and the shape of the report.
  Each agent's own prompt is then its task and its scratch directory. A brief for agents that
  measure says how many others share the machine, so timings are repeated. The report lists
  every point where what the agent found contradicts the plan.
- **Name the directory.** A shell keeps the directory the last command left it in. A command
  that writes, and a check whose answer depends on where it runs, both name their directory.
  A shell left in a subdirectory writes generated files there, and a check run from a
  stale directory reports on the wrong tree.
- **Findings come back in the report.** An agent returns what it found as its final message,
  and keeps scripts and raw output in its scratch directory. The brief does not ask it to
  write a report file. A harness may refuse that to a subagent, and each agent then works
  around the refusal in its own way.
- **Name the model for every agent.** Subagents inherit the session's model unless told
  otherwise, which is rarely what a fan-out wants. Steps that turn on judgment (a spike, a
  review) get the stronger model, and mechanical ones the cheaper.

### Tooling

| Item | Change |
|---|---|
| `planners subplans <NNN>` | List a plan's nested subplans with their `status` and `branch`, and exit non-zero when the umbrella's table disagrees with the subplan frontmatter. With `--write`, regenerate the table's Status column between two marker comments and leave the Scope and Note columns alone. With `--set <letter>=<status>`, change one subplan's status and regenerate the table in the same step, so the two cannot be updated apart |
| `implement <NNN><letter>` | Start one nested subplan on its own, e.g. `implement 012d`. Today the skill globs for a plan directory of that name, finds none, and has no path for a subplan inside an umbrella. For a nested subplan there is nothing to activate on the mainline and no branch to create: the umbrella is already `active`, so the skill sets the subplan `active`, re-reads it against the branch, and works on the umbrella's branch |
| `close` | Refuse to close an umbrella while a subplan is `draft`, `active`, or `blocked`, and list them. Each one is finished, or moved |
| Moved work | A step that waits on people (a decision, a manual check, someone else's input) often outlasts the code and is carried to a follow-up plan. Its subplan closes as `retired` with `moved_to: <NNN>`. A step that was partly done closes as `done`, with what moved named in the Note column. The subplan's Log maps each open item to its place in the follow-up. The follow-up plan lists what it inherits, and sorts the inherited "not verified" items into those it will check and those it leaves open |
| `validate` | Opt-in check of subplan frontmatter (`status` in the shipped enum). Off by default, so existing plans with free-form subplan files keep passing |
| `add <slug> --parent <NNN> --nested` | Scaffold a nested subplan with its frontmatter and a back-link to the umbrella. It reuses `--parent`, which lettered subplans already take, and assigns the next free letter from `b`. `--letter a` makes the investigation. The skills always pass `--nested`; `--parent` without it still makes a lettered sibling plan |
| Execution order | An optional `needs:` list in subplan frontmatter, so the dependency chain is data the orchestrator reads, not prose it interprets |
| Blocked state | `blocked` joins the status enum, for work that is waiting on a person. It is distinct from `draft` (not started) and `inactive` (set aside). Like `active` it is an open state, so `concluded` stays empty and nothing closes over it. What it waits on goes in the table's Note column, and in Handoff when it is a question |

### Related improvements

Found while running the shapes above. Each is small and independent of the rest.

- **`implement` assumes the base is checked out in the main checkout.** When the base branch
  lives in a worktree of its own, step 2 should say to find it with `git worktree list` and
  run `activate` there, and step 4 should resolve `.worktrees/` against the main repo root,
  not the current directory.
- **Recording the PR is three hand steps.** Editing `pr:`, refreshing the index, and
  committing is the same shape `activate` already automates. Add `planners set-pr <NNN> <url>`,
  or an equivalent, so the index cannot be forgotten.
- **Worktree setup is per-repo knowledge.** `implement` creates the worktree and stops. A hook
  point, such as a documented `post-worktree` step the repo can define, would cover the
  environment sync and gitignored links a fresh worktree needs. `close` wants the matching
  step before teardown, for whatever the repo has to release first. `implement` should also
  warn that a dependency given as a relative path (`path = "../lib"`) resolves from the main
  checkout and not from a worktree, which sits deeper.
- **A plan-level `## Handoff` section.** The rule names Plan, Log, and Retrospective. A
  held-questions list has no home, so it ends up in chat and is lost with the session. The
  same is true of "where to pick this up" when an effort spans sessions. Without a home, a
  new state section gets appended at the end of each session and the older ones are amended
  in place, until the umbrella is long again. Handoff is one section, between Log and
  Retrospective, and it is **rewritten in place**: the one exception to append-only, because
  it describes the present and the Log keeps the history. It holds:
  - the state of each piece, including what is uncommitted or unpushed;
  - the open questions, numbered once and never renumbered, so "question 3" means the same
    thing in every session, with each answer and its date written beside its question;
  - the questions that are settled or handed to another plan, marked as such and naming the
    plan, so a later session does not raise them again;
  - what is not verified;
  - the order of the remaining work, and who each item waits on.

  The test of a Handoff section is that a fresh session can start from "continue plan NNN"
  and nothing else. A pick-up prompt that has to restate the state is a sign the section is
  missing something.
- **Length guidance counts the umbrella only.** The ~500-line guidance should say that it
  applies to each file on its own, the umbrella and every subplan. What grows in an umbrella
  after a split is its Log, so whole-effort entries stay short and point to the subplan's
  Log for the detail.
- **Activation pushes whatever the base has not pushed.** Step 3 of `implement` runs
  `git push` right after `activate`. When the base is ahead of its upstream, that publishes
  every unpushed commit along with the activation. Step 2 already counts them; step 3 should
  show the count and confirm before pushing when it is not zero.
- **`activate` reports the wrong branch.** It prints `activated <plan> on <branch>`, naming
  the branch it recorded in the frontmatter. The commit landed on the mainline, so the line
  reads as if the guard had failed. It should name both: the branch recorded, and the branch
  committed on.
- **`validate` with no argument is an error.** It exits on a missing `paths` argument, and
  in a chained command that reads as the check having run. It should default to the
  current repo.
- **`close` deletes the branch with `git branch -d`, which can refuse a merged branch.** `-d`
  tests against the branch's upstream or the current HEAD, so it can refuse when the main
  checkout is on some other branch. The skill should confirm the merge against the base with
  `git merge-base --is-ancestor <branch> <base>` and say what to do when `-d` still refuses.
- **A lifecycle step described from memory is described wrongly.** The stub should tell the
  harness to print a subcommand's instructions before it explains what that subcommand
  does, not only before it runs it.
- **Retiring a plan is hand-edited.** A plan absorbed into a subplan is retired with three
  frontmatter edits, a Log entry, an index refresh, and a commit. `planners retire <NNN>`
  would do for `retired` what `activate` does for `active`, with `--into <NNN>` to record
  where the work went.

### Implementation order

| Step | Work |
|---|---|
| 1 | Document the nested shape, its name, and the choice between shapes in the rule and the `add` skill |
| 2 | Add the orchestration guidance to the `implement` and `pipeline` skills |
| 3 | `planners subplans`, its `--write`, and the opt-in `validate` check, with tests |
| 4 | `add --parent --nested`, `needs:`, the `blocked` status, and `moved_to`, once step 3 has settled the frontmatter |
| 5 | `implement <NNN><letter>` for a nested subplan, and the `close` check for unfinished subplans |
| 6 | The related improvements, each as its own commit |

### Out of scope

- Converting existing `NNN<letter>` subplans to nested ones, or the reverse.
- Running subagents from the CLI. The CLI stays a plan-file tool; orchestration is guidance
  for the harness that drives it.
- Indexing nested subplans in `.planners/README.md`.

## Log

- **2026-09-29T01:43:55-07:00** — Revised the spec, before any implementation, from
  experience running the shape on real plans. Adopted: the name "nested subplans" and the
  default it implies; the sidecar frontmatter as the one status of record, with a generated
  table; sidecars that land on a sub-branch or in another repo; the `close` check and
  `moved_to`; five additions to the orchestration guidance (scratch does not persist,
  who ran a check, re-read before starting, one shared brief, a named model); the Handoff
  section in place of "Open questions"; per-file length guidance; and the confirmation before
  an activation push. Considered and left out: converting lettered subplans to nested ones
  with a command (still out of scope, since the naming fix removes the usual cause), and a
  fixed format for sidecar titles.
- **2026-09-29T01:52:54-07:00** — Reworded the title and the spec to "nested subplans". A subplan
  file is now called a subplan, and "sidecar" is kept for other files in a plan directory.
  The proposed flag is `add --nested`. The slug keeps "sidecar", since it is fixed by the
  directory name.
- **2026-09-29T01:58:58-07:00** — Second revision, after a fuller review of earlier runs.
  Added to the shape: what the umbrella holds, fixed letters with `a` reserved, one subplan per node in the order, when a subplan closes, how
  to split an existing plan, and a suggested Log entry shape. Added to the run: marking a
  subplan active first, groundwork before the fan-out, the orchestrator's own lane, reading
  the evidence, auditing side effects, evidence that names its commit, measuring again
  before asking, checking the seam, handing work forward, naming the directory, and findings
  in the report. "One writer for git" became one of two ways to run in parallel, the other
  being a worktree per agent. "Scratch does not outlive the session" became "Scratch is not
  a record", since scratch sometimes survives and is worth reusing when it does. Added to
  the tooling: `subplans --set`, `implement <NNN><letter>`, and a fuller record for moved
  work. Added to the related improvements: the `activate` message, `planners retire`,
  `validate` with no argument, `git branch -d` at close, and printing a subcommand before
  describing it. The first revision's note on parallel steps was reworded: what matters
  is that each writer has its own worktree, not who the writers are.
- **2026-09-29T02:18:07-07:00** — Wording pass. Several examples were replaced with neutral ones or
  removed where the point stood without them, and the suggested Log headings were renamed.
  No guidance was added or dropped.
- **2026-09-29T02:33:14-07:00** — Three choices settled. `blocked` is a status, not a field. The
  scaffolding flag is `add <slug> --parent <NNN> --nested`, with the letter assigned.
  Subplans are always nested from now on, and a plan is split only when it needs it or the
  user asks. Lettered sibling plans stay supported, on request.
- **2026-09-29T03:11:07-07:00** — Implemented, in one session and without subagents for the
  work itself. The entry follows the headings the plan suggests for a subplan's Log.

  **What was done.** By implementation step:

  | Step | Commits |
  |---|---|
  | 3 | `20f6c73` (the `blocked` status), `1a0c475` (`planners/body.py` and `planners/subplans.py`, both pure), `a418cd3` (`planners subplans`, `validate --subplans`, and the nested scaffold) |
  | 4 | `a418cd3` (`add --parent --nested`, `--letter`), `1a0c475` (`needs:` and `moved_to`) |
  | 5 | `a418cd3` (`activate` on a nested reference points to `subplans --set`), `e68963e`, and `a524ad4` (the `implement` and `close` skills) |
  | 6 | `d0048a9` (`validate` with no argument), `bfbeca1` (the `activate` message), `142d25d` (`set-pr`), `495bcaa` (`retire`), and the skill prose in `e68963e` and `a524ad4` |
  | 1 | `358ca8a` (the rule and the `add` skill) |
  | 2 | `e68963e` (the `implement` and `pipeline` skills) |
  | docs | `4b33b63` (README and CHANGELOG) |

  **Departures from the spec.**

  - The steps ran 3, 4, 5, 6, 1, 2. The tooling was written first so that the rule and the
    skills describe commands as they behave, not as they were expected to.
  - "Each related improvement as its own commit" holds for the four that are code. The ones
    that are prose share commits with the other edits to the same skill file, since one file
    cannot be committed in parts without rewriting it in stages.
  - The instruction to print a subcommand before describing it went into the rule, not the
    stub. The stub's body is generated by the packaging library, which this repo does not
    own. The rule is loaded in every session, so the instruction is in front of the harness
    either way.
  - The worktree hook point is two optional scripts, `.planners/hooks/post-worktree` and
    `.planners/hooks/pre-worktree-remove`. The spec left the form open. A script was chosen
    over a documented section because the skill can test for it and run it.
  - `subplans` gained `--require-closed`, which the spec does not name. The `close` check is
    skill prose, and it needed a command whose exit status it could act on.
  - `validate --subplans` checks more than the status enum: the file name, `needs`,
    `moved_to`, and the rules that only show across a set (a letter used twice, a need with
    no subplan, a cycle).
  - `retire` and `set-pr` take a nested reference (`012d`) as well as a plan's.
  - `add --nested` applies the mainline guard only while the umbrella is not yet `active`.
    Under an active umbrella the subplan belongs on the branch with the work.
  - `blocked` sorts after `active` in the index, ahead of `draft`.

  **Surprises.**

  - `Path.read_text` converts CRLF to LF, and `write_text` writes LF, so every command that
    rewrites a plan also converts its line endings. This was already true of `activate`.
  - The flat frontmatter parser does not accept a trailing comment on any key
    (`status: draft # note` is an invalid status). `needs:` follows it.

  **Deferred.** The stub's own wording, which is a change to the packaging library.

  **Gaps.** None of the tooling items was left out. Converting existing lettered subplans,
  running subagents from the CLI, and indexing nested subplans stay out of scope, as
  planned.

  **Not verified.**

  - No skill was run from its new text. The orchestration guidance, `implement <NNN><letter>`,
    the two hook scripts, the confirmation before an activation push, and the `close` check
    for unfinished subplans are prose that no session has yet followed.
  - The installed stub and rule were not regenerated, so a session on this machine still
    loads the text of the released version until the next `install`.
  - The commands were run on Linux only. CI covers Python 3.11 to 3.14 on one platform.

  **Review follow-up.** The review of the PR ran at the medium level: two finders, four
  verifiers, and a sweep by the orchestrator. Fourteen findings survived and one candidate
  was rejected. The three that mattered had one cause, a command that wrote before it had
  settled everything that could refuse:

  | Raised | Outcome |
  |---|---|
  | Nested `retire` rewrote the subplan, then exited on a table it could not write, and a rerun refused the subplan as closed | fixed in `20a2588`, with a test |
  | `add --nested` wrote the subplan file, then exited the same way, leaving an orphan | fixed in `20a2588`, with a test |
  | `subplans --set` applied assignments one by one, so a bad one after a good one left the table stale | fixed in `20a2588`, with a test |
  | `retire` closed an umbrella over unfinished subplans (found in the sweep) | fixed in `20a2588`, with a test |
  | `subplans --set` gave a frontmatter to a free-form file (found in the sweep) | fixed in `20a2588`, with a test |
  | The heading pattern stripped a trailing `#` from a title | fixed in `4c6f801`, with a test |
  | Two resolvers, a lookup, and a load-and-regenerate block were each written twice | fixed in `20a2588` |
  | `write_table` built a fresh table twice; a constant was exported and unused | fixed in `cc2ed81` |
  | Git helpers were copied across the new test modules | fixed in `20a2588`; the copies that pre-date the PR were left alone |
  | `needs:` does not accept a trailing comment | no-op: the failure is loud, and every other key behaves the same |
  | The body helpers mix LF into CRLF text | no-op: no command passes them CRLF; the module now says what it expects |

  Each regression test was run against the code before its fix and failed there. The checks
  were run by the orchestrator, not reported by an agent: `ruff check`, `ruff format
  --check`, `pyrefly check`, and `pytest` pass at `cc3c759`, with 344 tests and 95%
  coverage. CI passed on the same commit.
- **2026-09-29T03:19:42-07:00** — Ran the new skills from their text, in a scratch repo, and
  fixed what the run found.

  **What was done.** A fresh agent followed `add`, `implement`, `update`, and `close` as
  printed by the command, with no access to the source. It worked in a throwaway repo with a
  local bare remote: it added an umbrella, split it into four nested subplans with `needs`,
  implemented each in order with real edits, blocked and unblocked one, retired a fifth into
  a follow-up plan, and closed the umbrella. The run ended with `validate`,
  `validate --subplans`, and `subplans --require-closed` all exiting zero. The orchestrator
  then read the scratch repo itself (the log, the umbrella, the retired subplan, and the
  edited script, which it ran) and confirmed that the working repo was untouched. The
  agent's account matched.

  | Found | Outcome |
  |---|---|
  | The confirmation before an activation push fires on every split plan, whose own `add` commits are all unpushed | the skill now pushes when every unpushed commit is the plan's own, and confirms otherwise (`c76ac08`) |
  | A remote given as a relative path cannot be reached from inside a worktree. Reproduced by the orchestrator | the skill says so, and pushes from the main checkout (`c76ac08`) |
  | `retire --into` does not find a follow-up plan added on the mainline during the work | the order is documented: add on the mainline, merge the base into the branch, then retire (`c76ac08`) |
  | The first nested `add` writes its own `### Subplans` heading, which the skill did not say | the skill says where the table goes, and how to place it elsewhere (`c76ac08`) |
  | A retired subplan printed as a root of the execution order | fixed in `57ae266`, with a test |
  | The Block paragraph sent a nested subplan to `activate`, and disagreed with the rule on where the wait is written | the skill has a path for a plan and one for a nested subplan (`c76ac08`) |
  | `needs:` has no flag, and the skill did not say it is added by hand | said (`c76ac08`) |
  | Two Log formats, one dated and one with headings | reconciled: the headings go inside a dated entry (`c76ac08`) |
  | The close commands read as one block but run in two directories | split by directory (`c76ac08`) |
  | `close` did not say `set-pr` usually fills `pr:` already | said (`c76ac08`) |

  **Left as found.**

  - The refusal on a feature branch names `--allow-branch`, and the agent reached for it once
    (with `--no-commit`, and undid it). The message pre-dates this plan.
  - The `close` skill's review gate names this repo's own check commands and assumes a PR
    exists. Both pre-date this plan.
  - A subplan's activation is a hand-written commit, since `subplans --set` writes none.

  **Not verified.**

  - Every `gh` step. The scratch repo had no remote on a forge, so the draft PR, `set-pr`
    after it, the PR comment, and the PR merge were not run from the new text there.
  - The orchestration guidance. The run used no subagents, as instructed.
  - The `post-merge` index hook, which the scratch repo did not install.
  - The installed stub and rule, which still carry the released text.

  The checks pass at `c76ac08`, run by the orchestrator: `ruff check`, `ruff format --check`,
  `pyrefly check`, and `pytest`, with 346 tests and 95% coverage.

## Handoff

**State.** Closed. The work is merged through the PR, and nothing is uncommitted or unpushed.

**Open questions.**

1. Should the stub tell the harness to print a subcommand's instructions before describing
   it? Handed on (2026-09-29): it is a change to the packaging library, not to this repo,
   and this plan put the instruction in the rule instead.
2. Should the confirmation before an activation push be enforced by `activate`, in code?
   Open, and not part of this plan. Today it is prose in the `implement` skill. A follow-up
   plan would own it.

**Not verified.** The `gh` steps of the new skill text, the orchestration guidance, and the
`post-merge` hook, as the last Log entry lists them.

**Remaining.** Nothing in this plan. After the next release, `install --force` regenerates
the installed stub and rule from the new text.

## Retrospective

- **The tooling was worth writing before the prose.** The rule and the skills describe
  commands that existed, so their examples could be run. The one place the prose still got
  ahead of the code, the Block paragraph, is where the scratch run found a wrong instruction.
- **The review found one defect three times.** `add --nested`, nested `retire`, and
  `subplans --set` each wrote a file and then checked whether the rest could be written. The
  fix was one function that settles every refusal first. A command that changes two files
  should be written that way from the start.
- **A reader who did not write the text finds what the author cannot.** Ten of the scratch
  run's findings were things the author knew and had not written down: that the first `add`
  writes a heading, that `needs:` is added by hand, that a follow-up plan is not on the
  branch yet. None of them showed in the tests, which passed throughout.
- **The plan followed its own guidance only in part.** It ran as one file, in one session,
  without subplans, so the nested shape was exercised in a scratch repo and not on the plan
  that specified it. It closes just over 500 lines, the length at which it would itself be
  split.
- **What would help next time:** run the skills from their text before the review, not after
  it. The scratch run changed both the code and the prose, and the review had already passed
  over the version it changed.
