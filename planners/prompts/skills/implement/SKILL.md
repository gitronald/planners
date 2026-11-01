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
`{cli} permissions --apply` writes an allow-rule profile (default `assist`) that
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

Each step (`base`, `activate`, `ignore`, `push-base`, `branch`, `worktree`,
`setup`, `push`, `pr`) reads its result first and prints one line, `done`,
`ran`, or `skipped`, with what it settled. `setup` runs
`.planners/hooks/post-worktree` when the repo has one, else copies `.claude/`
and runs `uv sync`.

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
Fan them out to subagents only when the user asks for subagents or a workflow.

**When the user asks for subagents or a workflow**, on any plan, run
`{cli} doc orchestrated-run` and follow it before launching an agent.

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

The worktree stays until the plan closes: `{cli} finish`, run by `/planners
close`, removes it, deletes the branch, and re-points any hook installed from
inside it.

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
