---
name: implement
description: Start implementing a plan — run the start command to activate it on the base and create its branch and worktree, begin coding, open a draft PR, and mark it implemented when the work is pushed.
metadata:
  version: "1.0.0"
---

# implement — start work on a plan

`{cli} start {NNN}` runs the mechanical steps: it activates the plan on the base,
creates the branch and worktree from that commit, sets the worktree up, and opens
the draft PR. A re-run resumes where the last one stopped. This skill is the
judgment around it: reading the plan, answering its stops, the work itself, and
marking the plan `implemented` once the work is pushed. Parse the plan
number (e.g. `021`) or path from the request; if ambiguous, glob
`.planners/plans/{NNN}-*/plan.md`.

A reference with a letter (e.g. `012d`) that matches no plan directory names a
**nested subplan**: a file under the umbrella's `subplans/`. It has nothing to
activate on the mainline and no branch to create, so skip the steps below and
follow *Implementing one nested subplan*.

`start` shells out to git. If commands prompt for permission every time,
`{cli} permissions` writes an allow-rule profile (default `assist`) that
pre-authorizes the reversible ones — see *Automation levels* in the planners rule.

## Steps

### 1. Read the plan

Read the plan file for its `# Title`, current `status`, `branch`, and the full
spec. If `status` is `done` or `retired`, stop and tell the user — it is closed.

### 2. Run `start` from the base

```bash
{cli} start {NNN}
```

Run it on the **base branch**, before any branch for the plan exists, so the
activation is recorded on the mainline whether or not the feature branch lands.
`{cli} base --all` prints the branches this repo counts as mainline. **The base may
live in a worktree of its own**: when the main checkout is on some other branch, find
the base with `git worktree list` and run `start` there. Do not check the base out a
second time (git refuses a branch that is already checked out).

`--branch <name>` chooses the branch (default `feature/<NNN>-<slug>`; a plan that
already records one keeps it). `--worktree <path>` (repo-relative) or `--no-worktree`
puts the work somewhere other than `.worktrees/<NNN>-<slug>`.

Each step reads its result first and prints one line, `done`, `ran`, or `skipped`,
with the reason:

| Step | What it settles |
|---|---|
| `base` | HEAD on the mainline, tree clean, not behind its upstream |
| `activate` | `status: active`, `branch:`, the Log entry, the index, the commit |
| `ignore` | the worktree path is ignored (`.worktrees/` committed when missing) |
| `push-base` | nothing on the base waits for a push |
| `branch` | the branch exists, from the base's tip or its copy on `origin` |
| `worktree` | the branch is checked out at the recorded path |
| `setup` | `.planners/hooks/post-worktree` ran, or else `.claude/` copied and `uv sync` run |
| `push` | the branch is on `origin` with tracking set |
| `pr` | a draft PR is open and recorded with `set-pr` |

**After any interruption, run it again.** The output is the resume record, so a lost
VM, a refused command, or a context reset costs one re-run. Do not edit the
frontmatter, run `{cli} index`, or redo a step by hand.

**A stop exits 1 and says what to do. Do that, then re-run:**

- **A push.** `start` publishes no code: a permission rule sees only the command a
  session runs, so a push from inside `start` would skip the gate that the `confirm`
  level exists to open. It prints the `git push` to run, and a first run stops this
  way for the base and again for the branch. A push from inside a worktree fails when
  `origin` is a relative path (`git remote get-url origin`), since it resolves from
  the main checkout; push from there instead.
- **Commits on the base that are not the plan's.** The stop before the base's push
  prints the same sorted report `activate` does (`6 are plan 008's own, 0 are other`).
  A commit is the plan's own when every path it touches is under the plan's directory
  or is the index. When the report says `0 are other`, push: a plan edited or split
  before activation arrives with several of its own. When it says more, show the
  listed commits to the user and confirm before pushing.
- **Off the mainline.** Ask whether to base the work on the current branch or on the
  first mainline branch, then check that branch out.
- **No mainline detected** (no `dev`, no `refs/remotes/origin/HEAD`, no
  `main`/`master`). Ask the user which branch is the base rather than guessing;
  `git remote set-head origin --auto` records the remote's default branch if that is
  what is missing. For a base `start` will not accept, go by hand: `{cli} activate
  {NNN} --allow-branch`, `git push`, then `git worktree add
  .worktrees/<NNN>-<slug> -b <branch> <base>`, and `git push -u origin <branch>`
  from inside it. Once on that branch `start` works again, for the setup and the PR.
- **A dirty tree.** Commit it or set it aside. If it belongs to other work the user
  wants left in place, ask.
- **Behind upstream.** Pull, so the activation commit sits on top of the latest.

**Read the `note:` lines under `setup`.** A worktree has the tracked files and nothing
else, and the rest is per-repo knowledge, so `start` reports what it does not guess: a
dependency on a relative path (`path = "../lib"`, which resolves from the main checkout
and not a worktree), a top-level symlink the worktree lacks, an environment no
`uv.lock` describes. Deal with each as the repo's own instructions say. A repo that
needs more than the defaults says so once, in an executable
`.planners/hooks/post-worktree`, which `start` runs from inside the new worktree in
place of its defaults.

**Other remotes.** `{cli} remote` names what `origin` is, from its URL and config:
`github`, `single-branch` (a hosted editor's git bridge that takes one branch, where
every push lands in the live document), `other-forge`, `bare`, or `none`. **Any kind but
`github` has no PR**: `start` skips the `pr` step, and the plan closes through `close`'s
no-PR path, so say that now. `single-branch` also skips both push steps. Pushing the
base there is a publish, so show the count `start` prints and ask before pushing; a
feature branch would be rejected, and the work is merged locally at close. When the
kind is wrong for this repo, commit `.planners/config.toml` with `kind = "<kind>"` under
`[remote]` (for every clone), or set `git config planners.remoteKind <kind>` (this
clone only, and it wins).

`start` ends by naming the worktree. **Run the remaining steps from inside it.**

### 3. Implement

Work inside the worktree. Follow the plan's implementation order; commit in
logical chunks and push as you go.

For an umbrella with **nested subplans**, run `{cli} subplans {NNN}` first. It
lists each subplan with its status and the execution order, and fails when the
umbrella's table disagrees with the subplan frontmatter. Work through the
subplans in that order, each as *Implementing one nested subplan* describes.
Fan them out to subagents only when the user asks for subagents or a workflow;
*An orchestrated run* is the guidance for that.

**Merge the base once, before the final checks**, not each time it moves. The
activation entry records the commit the work started from, and a branch that is
behind it is fine while the work is under way. Merge the base when the work is
done (or when a conflict or a change the work needs makes it necessary), then
run the full checks once on the result, and name the commit they ran at in the
Log entry that reports them. Each extra merge is another full run of the suite.

**A probe or scratch script stays out of the Log by path.** A plan is shared, so
`{cli} log` refuses a note naming an absolute or home-directory path
(`/tmp/probe.py`, `~/scratch`). Describe what the probe checked; when it is
worth keeping, copy it into the plan's directory as a sidecar and name that
repo-relative path. Write the entry right the first time: the Log is
append-only, and a later rewrite to remove a path is the edit it forbids.

### 4. Open the draft PR

Only on a `github` remote. For any other kind `pr:` stays empty until `close` writes
`pr: null`.

The activation commit lives on the base, so the new branch starts level with it, and
GitHub opens no PR until it is a commit ahead: `start` reports the `pr` step as
`skipped` until then. After your first implementation commit, push it and run `start`
again, from the worktree:

```bash
git push
{cli} start {NNN}
git push
```

It opens the draft, titled from the plan, with a body linking the plan on the base
branch, where the link is live at once and survives merge and branch deletion. It
records the URL with `{cli} set-pr`, which commits on the branch; the last push
publishes that. An open PR the plan does not record yet is adopted, not opened twice.

Keep pushing as you work so the draft PR stays current; it stays a draft until
the work is implemented.

### 5. Mark it implemented

Once the plan's work is finished, committed, and pushed, and its checks pass:

```bash
{cli} implemented {NNN}
git push
```

Off GitHub, `implemented` does not require the feature branch to have an
upstream (it prints `origin is <kind>: ...`), but it still refuses uncommitted
changes, and unpushed commits on a branch that has an upstream. On a
`single-branch` remote it checks uncommitted changes only, since the branch's
upstream, if any, is the live document. Skip the `git push` on a
`single-branch` remote, and on `none`, where there is nothing to push to.

It flips `active` to `implemented`, appends an `Implemented: <n> commits ahead
of <base>` Log entry, refreshes the index, commits `plan [implemented]: {NNN} -
<slug>` on the feature branch, and takes the PR out of draft with `gh pr ready`.
It refuses while the branch has uncommitted changes or unpushed commits, and
says which. It also refuses on the mainline or a detached HEAD, so the status
always matches what the reviewer sees. Push its commit so the PR shows it. A
failing `gh pr ready` is reported as a warning with the commit kept; run it by
hand.

`implemented` closes nothing. The merge, Retrospective, and `concluded` stay
with `/planners close`, which runs only when the user asks for it. Review that
asks for more work returns the plan with `{cli} activate {NNN}`, run on the
feature branch, which logs `Reactivated`; mark it implemented again when the
follow-up is pushed.

When the plan is closed (`/planners close`) and its branch is merged, remove the
worktree: `git worktree remove .worktrees/<NNN>-<slug>`. Worktrees share the
main repo's `.git/hooks/` — a pre-commit hook installed from inside the worktree
(`uv run pre-commit install`) embeds the worktree's `.venv` python as its
`INSTALL_PYTHON`, so once the worktree is removed the hook fails on every later
commit. `/planners close` re-installs it from the main checkout
(`uv sync && uv run pre-commit install`) as part of cleanup.

## Implementing one nested subplan

`implement 012d` starts subplan `d` of umbrella `012` on its own. The umbrella is
already `active`, so there is nothing to activate on the mainline and no branch
to create.

1. **Check the umbrella.** Read `.planners/plans/012-*/plan.md` and the subplan,
   `subplans/d-*.md`. If the umbrella is not `active`, implement the umbrella
   first (the steps above). Work in the umbrella's worktree, on its branch.
2. **Check what it needs.** `{cli} subplans 012` prints each subplan's `needs`.
   A subplan whose needs are not `done` waits, unless the user says otherwise.
3. **Mark it active, and commit that.**

   ```bash
   {cli} subplans 012 --set d=active
   git add .planners/plans/012-<slug>/ && git commit -m "plan [activate]: 012d - <step>"
   ```

   `--set` changes the subplan's frontmatter and regenerates the umbrella's
   table in the same step, so the two cannot be updated apart. Never edit the
   table's Status column by hand.
4. **Re-read the subplan against the branch as it stands.** Subplans are written
   together, before any of them runs, so the later ones go stale as the earlier
   ones land: names that have changed, numbers that have moved, work that is no
   longer needed. Read the umbrella's Log for what earlier subplans handed
   forward. Log the corrections in the subplan's Log. Do not rewrite the spec.
5. **Do the work**, committing in logical chunks. A subplan with a `branch` of
   its own works on that sub-branch, in its own worktree, and merges back into
   the umbrella's branch with `--no-ff`.
6. **Close it when its own work is finished**, not when the effort is: append
   its Log entry with `{cli} log 012d -` (the note on stdin), then
   `{cli} subplans 012 --set d=done`. The command stamps the entry from the
   clock, as it does every Log entry, and the headings the `add` skill suggests
   go inside it as nested lines. Mark it done only when
   its checks ran and passed. A step waiting on a person is `blocked`, with what
   it waits on in the table's Note column. A step that lands through a PR of its
   own (its `pr:` is set) is marked `{cli} implemented 012d` when that PR is
   ready for review, which writes its status and Log entry, regenerates the
   umbrella's table, and takes that PR out of draft; it is set `done` once the
   PR merges.

## An orchestrated run

Used **only when the user asks for subagents or a workflow**. One `implement` of
the umbrella works through the subplans in dependency order and fans the
independent ones out.

### Order and phases

- **Scout first, then fan out.** Read the umbrella and every subplan, then group
  the subplans into phases from the execution order (`{cli} subplans {NNN}`
  prints it when the subplans declare `needs:`). Subplans with no dependency
  between them run in parallel. Read each phase's results before launching the
  next.
- **Mark the subplan active first.** Before a phase is launched, set its
  subplans to `active` and commit that change. A run whose first phase is a
  spike otherwise has nothing to commit, so the branch stays level with the
  base, the draft PR cannot open, and the plan files say nothing is in progress
  while agents are at work.
- **Re-read each subplan before starting it**, as step 4 above describes.
- **Lay the groundwork before the fan-out.** Land what the parallel steps share
  before launching them: the scaffold, and an empty entry for each step in any
  file they would all edit. Each agent then fills in its own entry, and the
  shared file stays the orchestrator's.

### Two ways to run in parallel

Pick per phase, and say which in the brief.

| Way | Git | Fits |
|---|---|---|
| One worktree | Agents write files and never touch git. The orchestrator commits each agent's output as its own logical chunk | Short steps whose files do not overlap |
| A worktree per agent | Each agent has its own worktree, environment, and sub-branch, and commits for itself with the checks green at every commit. The orchestrator merges with `--no-ff` and resolves the conflicts | Long steps where the history of each matters, or where files overlap |

In neither way does an agent push, merge, or touch a branch that is not its own.
Two writers in one worktree share one git index, so one's commit can carry the
other's staged changes. With a worktree per agent, expect conflicts at the
merge, and have each agent mark anything temporary it added to keep its own
tree working.

### Briefing the agents

- **One shared brief.** Write the rules every agent in a fan-out follows once,
  to a file each agent reads first: where to work, what it must not touch, the
  repo's standing rules (no git, no recursive deletes, how to run the
  interpreter), and the shape of the report. Each agent's own prompt is then its
  task and its scratch directory. A brief for agents that measure says how many
  others share the machine, so timings are repeated. The report lists every
  point where what the agent found contradicts the plan.
- **Disjoint file ownership.** Every agent's brief names the paths it may touch.
  Work that would overlap is sequenced, or the orchestrator stages it outside
  the tree and places it once the owning agent has finished.
- **Name the model for every agent.** Subagents inherit the session's model
  unless told otherwise, which is rarely what a fan-out wants. Steps that turn
  on judgment (a spike, a review) get the stronger model, and mechanical ones
  the cheaper.
- **Name the directory.** A shell keeps the directory the last command left it
  in. A command that writes, and a check whose answer depends on where it runs,
  both name their directory. A shell left in a subdirectory writes generated
  files there, and a check run from a stale directory reports on the wrong tree.
- **Findings come back in the report.** An agent returns what it found as its
  final message, and keeps scripts and raw output in its scratch directory. The
  brief does not ask it to write a report file. A harness may refuse that to a
  subagent, and each agent then works around the refusal in its own way.
- **Spikes stay in scratch.** An investigative step writes nothing to the repo.
  Its findings come back through the agent's report and land in the subplan's
  Log.

### While the agents run, and after

- **The orchestrator keeps its own lane.** While agents run, work on files none
  of them owns, and read the code the plan describes. That reading is where a
  plan's own errors show up.
- **Read the evidence, not the summary.** Open what an agent produced (the
  output, the raw numbers) before using a claim. Agents report conclusions their
  own evidence does not support: a benchmark that timed a warm cache against a
  cold one, a saving counted twice. A claim that does not survive is logged as
  untested, not dropped.
- **Audit each agent's side effects.** After every hand-back, check the tree
  with `git status`, any place outside the repo the agent was allowed to write,
  and any process or port it started. Briefs are not always obeyed, and an
  agent's own account of what it touched is not a check.
- **Check the seam.** After parallel work is merged, run the checks on the
  combined tree, from more than one working directory. One step can quietly
  break what another landed, e.g. one renames a setting that the other's code
  still reads, while each branch's own tests stay green.
- **Hand work forward in writing.** What one subplan leaves for a later one is
  listed in the umbrella's Log as well as its own, so the later subplan's
  re-read finds it.

### What gets recorded

- **Truthful status.** A subplan is marked done only when its checks ran and
  passed. "Not run" and "not verified" are recorded in those words. So is who
  ran a check: a result the orchestrator re-ran is recorded differently from one
  a subagent only reported. A run that a broken script made meaningless is
  recorded as void, not deleted. A check the user waives is recorded as waived,
  and by whom.
- **Evidence names its commit.** A measurement records the commit it was taken
  at, and whether the source was fetched first. A checkout that is behind its
  remote gives a true result about stale code.
- **Scratch is not a record.** It may survive the session or it may not, so
  nothing depends on it. The Log entry for a spike carries the steps to repeat
  it, not only its result. A probe script worth running again is committed to
  the plan directory as a sidecar file. A tool the work depends on is installed
  where the next session will find it. A plan never points at a scratch path.
  When an earlier session's scratch does survive, a later one copies from it and
  builds in its own, since the old outputs are what the earlier results were
  measured on.
- **Questions are held.** Collect open questions as the run goes and ask them
  together at the end. Write them to the plan's `## Handoff` section as they
  arise, not only into the final message, so an interrupted run does not lose
  them. A step that needs a human (a decision, a manual check, access only they
  have) is marked `blocked`, and the run carries on with whatever does not
  depend on it.
- **Measure again before asking.** A question put to the user carries a number
  measured against the branch as it stands, not one copied from an earlier Log
  entry. A stale figure asks the user to decide on a problem that may no longer
  exist.
