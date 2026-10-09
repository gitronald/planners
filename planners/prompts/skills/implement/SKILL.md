---
name: implement
description: Start implementing a plan — activate it on the base, branch from that commit, begin coding, open a draft PR, and mark it implemented when the work is pushed.
metadata:
  version: "1.0.0"
---

# implement — start work on a plan

Flip the plan to `active` on the base and commit it there, branch (and worktree)
from that activation commit, start building, open a draft PR, and mark the plan
`implemented` once the work is pushed. Parse the plan
number (e.g. `021`) or path from the request; if ambiguous, glob
`.planners/plans/{NNN}-*/plan.md`.

A reference with a letter (e.g. `012d`) that matches no plan directory names a
**nested subplan**: a file under the umbrella's `subplans/`. It has nothing to
activate on the mainline and no branch to create, so skip the steps below and
follow *Implementing one nested subplan*.

The worktree, commit, and push steps below each shell out to git; if they prompt
for permission on every command, `{cli} permissions` writes an allow-rule profile
(default `assist`) that pre-authorizes the reversible ones — see *Automation
levels* in the planners rule.

## Steps

### 1. Read the plan

Read the plan file for its `# Title`, current `status`, `branch`, and the full
spec. If `status` is `done` or `retired`, stop and tell the user — it is closed.

### 2. Check git state and choose the base

```bash
git status
git branch --show-current
{cli} base --all
git rev-list --left-right --count HEAD...@{upstream}
```

- The activation commit (step 3) lands on the **base**, so be on the base branch
  in the main checkout. `{cli} base --all` prints the branches this repo counts
  as mainline (`dev` when it exists, plus the default branch) — the same
  detection `{cli} add` enforces, so trust it over the `dev` convention. If the
  current branch is not one of them, ask whether to base the work on the current
  branch or on the first mainline branch, then check that branch out.
- **Do not create the branch or worktree first.** Running add/activate from
  inside a feature branch puts both commits only on that branch, so the mainline
  never records the plan if the branch does not land. `{cli} add` and
  `{cli} activate` both refuse outright in that position, so this check is what
  keeps you from hitting a refusal in step 3 rather than the only thing
  protecting it.
- If `{cli} base` exits non-zero, the repo's mainline could not be detected
  (no `dev`, no `refs/remotes/origin/HEAD`, no `main`/`master`). Ask the user
  which branch is the base rather than guessing — and note that
  `git remote set-head origin --auto` records the remote's default branch if
  that is what is missing.
- Behind upstream → pull the base first so the activation commit sits on top of
  the latest, and so the report in step 3 compares against a current upstream.
- **The base may live in a worktree of its own**, not in the main checkout. When
  the main checkout is on some other branch, find the base with
  `git worktree list` and run step 3 from that worktree, rather than checking
  the base out a second time (git refuses a branch that is already checked out).
- The activation commit stages only the plan file and the index, so unrelated
  uncommitted changes in the checkout are left untouched.

### 3. Activate the plan on the base

Do this **on the base branch, before creating the branch**, so the activation is
recorded on the mainline regardless of whether the feature branch ever lands.

```bash
{cli} activate {NNN}
git push
```

**Read `activate`'s report before the push.** `git push` publishes every
unpushed commit on the base along with the activation, so after its commit
`activate` counts them and sorts them, against the upstream as last fetched:

    committed the activation on dev
    dev is 6 ahead of origin/dev (as last fetched): 6 are plan 008's own, 0 are other

A commit is the plan's own when every path it touches is under the plan's
directory (nested subplans included) or is the index. When the report says
`0 are other`, push: a plan that was edited or split before activation arrives
with several of its own, and that is the usual case. When it says more, the
commits follow, one per line, as `git log --oneline` prints them; show that
list and confirm before pushing. The report is withheld when the base has no
upstream to compare against — no remote, or a base created without `-u` —
and silence is not a count of zero: when no report prints, check
`git status -sb` (or `git log --oneline @{upstream}..`) before pushing, and set
the upstream first when there is none.

`activate` prints two lines before the report, and they name different
branches: the branch it **recorded** in the frontmatter, where the work will
go, and the branch it **committed on**, which is the base.

One command sets `status: active`, fills `branch:` (the plan's own field if set,
otherwise `feature/<slug>`; `--branch <name>` to choose), appends the activation
entry to the plan's Log (branch, base and commit, worktree, PR), refreshes the
index, and commits as `plan [activate]: {NNN} - <slug>`. The entry records the
worktree step 4 creates, `.worktrees/<branch-suffix>`; pass `--worktree <path>`
(repo-relative) or `--no-worktree` when the work will be somewhere else. It carries the same mainline guard as
`{cli} add` and refuses here if you are already on a feature branch — which is the
check step 2 exists to pass, now enforced rather than remembered.

Do not edit the frontmatter, run `{cli} index`, or write the commit yourself; the
CLI handles all of it. `--no-commit` writes the file only, and is unguarded because
it strands nothing.

### 4. Create the worktree and branch from the activation commit

By default, do the plan's work in a dedicated **git worktree** under
`.worktrees/` (gitignored) so the main checkout stays on the base.

First make sure `.worktrees/` is ignored, so the worktree never shows up as
untracked in the parent tree:

```bash
grep -qxF '.worktrees/' .gitignore 2>/dev/null \
  || { echo '.worktrees/' >> .gitignore && git add .gitignore \
       && git commit -m "ignore .worktrees"; }
```

Then create the worktree on a new branch off the base — whose HEAD is now the
activation commit — and set upstream:

```bash
root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
git worktree add "$root/.worktrees/<branch-suffix>" -b <branch> <base>
cd "$root/.worktrees/<branch-suffix>"
git push -u origin <branch>
```

`<branch-suffix>` is the branch's final path component (e.g. `<slug>` for
`feature/<slug>`); `<base>` is the branch chosen in step 2. `$root` is the
**main repo root**, so `.worktrees/` lands there and not under the current
directory, which is a worktree itself when the base lives in one. **Run the
remaining steps from inside the worktree.** To work in the main checkout
instead, use `git checkout -b <branch>` here and skip the worktree.

**Set the worktree up.** A fresh worktree has the tracked files and nothing
else. What it still needs is per-repo knowledge, so the repo says it once:

```bash
[ -x "$root/.planners/hooks/post-worktree" ] && "$root/.planners/hooks/post-worktree"
```

Run it from inside the new worktree. It covers the environment sync and the
gitignored links and files a fresh worktree lacks. When the repo defines no
hook, do the setup the repo's own instructions describe, e.g. `uv sync` for a
uv project, which needs its own environment per worktree.

A dependency given as a **relative path** (`path = "../lib"`) resolves from the
main checkout and not from a worktree, which sits deeper. Check the project's
dependency table for one before syncing, and say so when it is there. A
**remote** given as a relative path (`git remote get-url origin`) fails the same
way: every `git push` from inside the worktree reports that the remote is not a
repository. Push from the main checkout instead, with
`git -C "$root" push -u origin <branch>`.

### 5. Implement

Work inside the worktree. Follow the plan's implementation order; commit in
logical chunks and push as you go.

For an umbrella with **nested subplans**, run `{cli} subplans {NNN}` first. It
lists each subplan with its status and the execution order, and fails when the
umbrella's table disagrees with the subplan frontmatter. Work through the
subplans in that order, each as *Implementing one nested subplan* describes.
Fan them out to subagents only when the user asks for subagents or a workflow;
*An orchestrated run* is the guidance for that.

### 6. Open a draft PR

The activation commit lives on the base, so the new branch starts even with it —
`gh pr create` has nothing to open until the branch is a commit ahead. After your
first implementation commit, open the draft PR.

Point the body at the plan with a markdown link so it resolves on GitHub — a bare
relative path renders as inert text in PR bodies. The link text stays the
repo-relative plan path (greppable and clickable in a local checkout); the href is
a blob URL pinned to the **base** branch, where the activation commit already
landed the plan file — so it is live the moment the PR opens and survives merge and
branch deletion. Derive `<owner>/<repo>` with `gh repo view --json nameWithOwner -q
.nameWithOwner`:

```bash
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh pr create --draft --base <base> \
  --title "<plan title>" \
  --body "Implements [.planners/plans/{NNN}-<slug>/plan.md](https://github.com/$repo/blob/<base>/.planners/plans/{NNN}-<slug>/plan.md)"
```

Record the PR URL with one command, which writes `pr:`, appends a `PR opened`
Log entry, refreshes the index, and commits as `plan [pr]: {NNN} - <slug>`:

```bash
{cli} set-pr {NNN} <url>
```

Keep pushing as you work so the draft PR stays current; it stays a draft until
the work is implemented.

### 7. Mark it implemented

Once the plan's work is finished, committed, and pushed, and its checks pass:

```bash
{cli} implemented {NNN}
git push
```

It flips `active` to `implemented`, appends an `Implemented: <n> commits ahead
of <base>` Log entry, refreshes the index, commits `plan [implemented]: {NNN} -
<slug>` on the feature branch, and takes the PR out of draft with `gh pr ready`.
It refuses while the branch has uncommitted changes or unpushed commits, and
says which, so the status always matches what the reviewer sees. Push its
commit so the PR shows it. A failing `gh pr ready` is reported as a warning
with the commit kept; run it by hand.

`implemented` closes nothing. The merge, Retrospective, and `concluded` stay
with `/planners close`, which runs only when the user asks for it. Review that
asks for more work returns the plan with `{cli} activate {NNN}`, run on the
feature branch, which logs `Reactivated`; mark it implemented again when the
follow-up is pushed.

When the plan is closed (`/planners close`) and its branch is merged, remove the
worktree: `git worktree remove .worktrees/<branch-suffix>`. Worktrees share the
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
   its Log entry, then `{cli} subplans 012 --set d=done`. The entry is dated like
   any other (`- **{timestamp}** — ...`), and the headings the `add` skill
   suggests go inside it. Mark it done only when
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
