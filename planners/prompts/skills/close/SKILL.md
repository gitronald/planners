---
name: close
description: Close a finished plan — review gate, final log, retrospective, frontmatter, merge, and cleanup.
metadata:
  version: "1.0.0"
---

# close — finish a plan end to end

Run a final review, document what happened, set the closing frontmatter, refresh
the index, then merge the PR branch and clean up. Parse the plan number or path
from the request.

The default close merges through the plan's PR. Two phrases in the request
change the steps, and each is read literally rather than reinterpreted:

- **"no PR"** (or "merge locally", "just merge into dev") selects the **no-PR
  path**: the branch is merged into the base with a local `git merge --no-ff`,
  the PR steps are skipped, and `pr: null` is recorded. *Merging the existing
  PR* is not a no-PR close, however similar the outcome. See *The no-PR path*
  for the steps and for the rule when a PR already exists.
- **"minimal review"** selects the **minimal review gate** in step 2: the
  project checks and a diff skim, with nothing posted. It replaces the
  review → post → fix → verify loop, not the gate itself; a close never merges
  unreviewed.

Both can be combined ("no PR, minimal review, just merge into dev"). When the
request is silent, run the default.

## Steps

### 1. Read the plan and gather context

Read the plan's `# Title`, `status`, `branch`, and existing Log/Retrospective.
The status is normally `implemented`, set by `{cli} implemented` when the work
was pushed and the PR left draft. An `active` plan is accepted too: it skipped
that step, and the gate below takes its PR out of draft. Any other status is not
ready to close; stop and say which it is.
Run `git log --oneline` for recent commits and `git diff --stat HEAD`; if there
are uncommitted changes, stop and tell the user.

**An umbrella does not close over unfinished subplans.** For a plan with nested
subplans, run:

```bash
{cli} subplans {NNN} --require-closed
```

It exits non-zero and lists every subplan that is `draft`, `active`,
`implemented`, or `blocked`, and any row where the umbrella's table disagrees with the subplan
frontmatter. Refuse to close while it fails. Each listed subplan is finished, or
moved:

- **Finished** — its checks ran and passed, its Log entry is written, and
  `{cli} subplans {NNN} --set <letter>=done` records it.
- **Moved** — a step that waits on people (a decision, a manual check, someone
  else's input) often outlasts the code and is carried to a follow-up plan. Its
  subplan closes as `retired` with `moved_to`:
  `{cli} retire {NNN}<letter> --into <follow-up NNN>`. The follow-up plan is
  added on the mainline and merged into the feature branch first, or `--into`
  does not find it; `{cli} skill update` gives the order. A step that was partly
  done closes as `done`, with what moved named in the table's Note column. The
  subplan's Log maps each open item to its place in the follow-up. The follow-up
  plan lists what it inherits, and sorts the inherited "not verified" items into
  those it will check and those it leaves open.

### 2. Review gate (review → fix → verify) — MANDATORY, BEFORE MERGE

Do not merge — `gh pr merge` or a local `git merge` alike — until this gate has
run and every finding is fixed or recorded as a conscious no-op. Running the
review and resolving its findings is what gates the merge; **posting the review
to the PR is best-effort** — a blocked post never stalls the close.

**Minimal review.** When the user asked for a minimal review, the gate is:

1. the full check gate below (lint, format check, type check, tests), run until
   clean;
2. a skim of the branch's diff against the base (`git diff <base>...HEAD`) for
   anything the checks cannot see: a leftover debug line, a path or name that
   is machine-specific, a plan file edit that was not meant to ship.

Nothing is posted and no review skill runs. Fix what the skim finds the same
way the full gate does, and say in the final log entry that the review was
minimal, and at whose request. The user chooses the lighter gate; it is never
the default, and a session does not downgrade to it on its own.

```bash
gh pr list --head "$(git branch --show-current)" --state open --json number --jq '.[0].number'
```

- Review the PR diff with the project's review skill (`/code-review`, or
  `/review PR <number>`).
- Post it: `gh pr comment <number> --body-file <file>`. Under Claude Code's
  auto-permission mode this self-authored external write is often **blocked by
  the classifier** (closing a plan doesn't obviously request posting a comment).
  If it's denied, don't retry or stall — surface the review inline and note it
  wasn't posted, then carry on. To post automatically, pre-authorize the command
  with a Bash allow-rule `Bash(gh pr comment:*)` (and optionally
  `Bash(gh pr ready:*)`): `{cli} permissions --level assist` writes the planners
  profile that includes them, or add the rule by hand via `/update-config`. It
  lives in the repo's `.claude/settings.local.json` (or `~/.claude/settings.json`
  for all repos); precedence is deny > allow > classifier. `gh pr merge` is
  irreversible, so by default it stays behind the classifier — the `full` level
  (`{cli} permissions --level full`) is the explicit opt-in to pre-authorize it.
- Fix actionable findings at the source, each with a paired regression test.
  Record intentional skips as conscious no-ops.
- Run the full check gate until clean, then commit fixes and push. **Mirror the
  repo's CI** so a green local run can't fail CI — for this repo that is
  `uv run ruff check . && uv run ruff format --check . && uv run pyrefly check &&
  uv run pytest` (the `ruff format --check` is easy to omit locally and is the
  usual reason CI fails a run that passed on the machine).
- `gh pr ready <number>` — usually done already by `{cli} implemented`; run it
  for a plan that skipped that step (still `active`), and it is harmless on a PR
  that is already ready. It is also a self-authored write, so the classifier can
  block it the same way. If it's denied, don't retry in a loop: report that the
  PR is still a draft and stop before the merge (a draft can't be merged). The
  same `Bash(gh pr ready:*)` allow-rule pre-authorizes it, or the user can mark
  it ready by hand.

### 3. Final log entry

If commits (including review fixes) are not yet in `## Log`, append a dated
entry. If the gate produced fixes, include a **"Review follow-up"** sub-entry:
what was raised, what was actioned (with tests), what was a conscious no-op.

### 4. Handoff and retrospective

If the plan has a `## Handoff` section, bring it current, rewriting it in place:
every open question is answered (with the answer and its date beside it) or
handed to another plan by name, and what is still not verified is said in those
words. A plan does not close with a question nobody owns.

Append a concise `## Retrospective` (3–6 bullets): what went as planned vs.
changed, key decisions, and what would help next time. Insight, not a summary.

### 5. Closing frontmatter and index

- `concluded` = the last implementation commit's authored date
  (`git log --format="%aI" -1`), not now.
- `pr` = the PR URL (`gh pr list --head "$(git branch --show-current)" --state all --json url --jq '.[0].url'`);
  if merged with no dedicated PR, write `pr: null` — never the string `none`.
  `implement` records it with `{cli} set-pr` when the PR opens, so it is
  usually filled already; check it, and fill it only when it is not. On the
  no-PR path it is `pr: null`, including when a PR was opened and then closed
  unmerged in favor of the local merge (see *The no-PR path*).
- Set `status: done`.
- `{cli} index .` and commit the regenerated `.planners/README.md`.

### 6. Commit, then finish from the main checkout

The session runs this step itself, start to finish. See *Who runs the
cleanup* below.

First commit and push the closing plan edit on the feature branch. Reach the
worktree with a subshell, so the session's shell stays on the main checkout:

```bash
(cd .worktrees/<branch-suffix> \
  && git add .planners/plans/{NNN}-<slug>/plan.md .planners/README.md \
  && git commit -m "plan [close]: {NNN} - <slug>" && git push)
```

Then, from the **main checkout**, merge the PR and finish:

```bash
gh pr merge <N> --merge --subject "merge: PR #<N> - <branch>"
{cli} finish {NNN}
```

The subject follows the repo's merge-subject convention, with the branch cut
with a trailing `...` past 60 characters. Leave out `--delete-branch`. On some
`gh` versions it removes the branch's worktree as well, and `finish` deletes the
branch itself. Right after a push, GitHub can report a PR as not mergeable while
it recomputes. Poll `gh pr view <N> --json mergeable,mergeStateStatus` until it
reads `MERGEABLE`, then merge.

The merge is the session's own command, not part of `finish`, so the
automation level still governs it. A permission rule sees only the command a
session runs, not what that command runs in turn. `gh pr merge` is
pre-authorized only at the `full` level (`{cli} permissions --level full`).
Below it, the merge goes to the permission prompt or the classifier.

`finish` does the rest in order, and prints a line for each step:

1. It fetches with `--prune` and confirms the PR reads `MERGED`. If it does not, it stops and prints the
   merge command.
2. It checks that the worktree has nothing uncommitted and no commit the merged
   base lacks (not its upstream, which GitHub may have deleted). It runs
   `.planners/hooks/pre-worktree-remove` when the repo defines one (the
   counterpart of the setup step in `implement`), then removes the worktree.
3. It checks the base out and fast-forwards it. The main checkout is never
   treated as a worktree; a branch checked out there is replaced by the base.
4. It deletes the branch on the remote, and then locally, each only when the
   base contains it. It never uses `-D` and never deletes a mainline branch.
5. It commits the plan index when the merge left it stale. It does not push;
   when it says it committed, run `git push`.
6. It re-installs any hook in `.git/hooks/` whose `INSTALL_PYTHON` points into
   `.worktrees/`. A hook installed from inside the worktree runs that worktree's
   `.venv`, and the generated script skips quietly once the venv is gone.

**When `finish` stops.** It exits 1 and leaves the state as it was when there is
something to look at: a branch that is not merged, a worktree with uncommitted
changes or commits the base lacks, a branch that holds such commits, an
uncommitted edit to the plan index, or a `git` or `gh` call that was refused. Deal with what it names, then run `{cli} finish {NNN}` again.
Each step that is already done is skipped, so the re-run picks up where the last
one ended.

Report: review run, plan closed, PR merged, and what `finish` printed.

### Who runs the cleanup

- **The session runs every cleanup step itself.** None of them needs a
  decision, and the review gate has already passed.
- **Hand a step to the user only after a call to it was refused**, and quote the
  refusal. Never hand one off because a block seems likely. A session that
  believes it cannot reach the main checkout tests that with one read-only
  command run there (`git status`) before it says so.
- **Keep the shell on the main checkout.** Reach the worktree with a subshell
  (`(cd .worktrees/<name> && ...)`) or a pathspec, not with a bare `cd` in the
  persistent shell. After a bare `cd`, the harness reports the worktree as the
  session's working directory, which reads like an isolation block and is not
  one.

## The no-PR path

Used only when the user asks for it (see the opening). Steps 1 through 5 run as
written, with step 2 at whichever gate the user chose, minus the gate's PR
steps: there is no PR to post the review to and none to mark ready, so the
full gate on this path is review -> fix -> verify with the review surfaced
inline, and `gh pr ready` is skipped. What changes is step 6, and one check
that comes before anything else.

**When a PR already exists, stop and ask.** Before any step, look:

```bash
gh pr list --head "$(git branch --show-current)" --state open --json number,url
```

If that returns a PR, the request and the state disagree: "no PR" was asked for,
and a PR is open. Do not pick for the user, and do not merge the PR as if that
were what "no PR" meant. Ask which they want, naming both:

- **merge via the existing PR** — the default close from step 2 on, with the
  PR URL kept in `pr:`; or
- **close the PR unmerged and merge locally** — the steps below, with
  `pr: null`; the PR itself is closed in step 6, once the gate has passed.

Either answer is fine; the point is that the instruction and the action match.
Ask before step 1, but do not close the PR yet: a gate that finds a blocker
can still end the close, and a PR closed early with a "merging locally"
comment would then say something false.

**Step 6 on the no-PR path.** Commit and push the closing plan edit on the
feature branch as in step 6. Then, when the user chose to close an existing PR
unmerged, close it now:

```bash
gh pr close <number> --comment "Closing unmerged; the branch is merged locally into $({cli} base)."
```

Then, from the **main checkout**, merge the branch, push, and finish:

```bash
git checkout "$({cli} base)" && git pull
git merge --no-ff <branch> -m "merge: <branch>"
git push
{cli} finish {NNN} --no-pr
```

For a merge made without a PR, the subject names the branch, cut with a
trailing `...` past 60 characters. The plan records `pr: null`, which takes the
no-PR path without the flag; the flag says so out loud. `finish` checks that the
base's upstream contains the branch, and stops with the merge command if it
does not. The rest is the same as step 6: the worktree, the branches, the index,
and the hooks.

The index is marked `merge=union`, so the local merge does not conflict on it.
Union can leave a plan's row duplicated when both branches rewrote it, though,
and `{cli} validate` fails on an index that disagrees with the frontmatter. The
repo's `post-merge` hook regenerates it after a clean merge, and `finish`
regenerates it again and commits it when it changed.

Report: review run (and at which gate), plan closed, branch merged locally with
no PR (or: existing PR closed unmerged, then merged locally), branch and
worktree cleaned up.
