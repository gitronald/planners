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

## Steps

### 1. Read the plan and gather context

Read the plan's `# Title`, `status`, `branch`, and existing Log/Retrospective.
Run `git log --oneline` for recent commits and `git diff --stat HEAD`; if there
are uncommitted changes, stop and tell the user.

**An umbrella does not close over unfinished subplans.** For a plan with nested
subplans, run:

```bash
{cli} subplans {NNN} --require-closed
```

It exits non-zero and lists every subplan that is `draft`, `active`, or
`blocked`, and any row where the umbrella's table disagrees with the subplan
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

Do not call `gh pr merge` until this gate has run and every finding is fixed or
recorded as a conscious no-op. Running the review and resolving its findings is
what gates the merge; **posting the review to the PR is best-effort** — a blocked
post never stalls the close.

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
- `gh pr ready <number>` — also a self-authored write, so the classifier can
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
  usually filled already; check it, and fill it only when it is not.
- Set `status: done`.
- `{cli} index .` and commit the regenerated `.planners/README.md`.

### 6. Commit, merge, clean up

The commands run in two places, and each block names its own. In the
**worktree**, on the feature branch:

```bash
git add .planners/plans/{NNN}-<slug>/plan.md .planners/README.md && git commit -m "plan [close]: {NNN} - <slug>"
git push
gh pr merge --merge
[ -x .planners/hooks/pre-worktree-remove ] && .planners/hooks/pre-worktree-remove
```

The last line releases whatever the repo has to release before the worktree
goes. It is the counterpart of the setup step in `implement`, and the repo
defines it the same way.

Then in the **main checkout**, which is where the base is checked out (a
worktree cannot check the base out a second time, and cannot remove itself):

```bash
git checkout "$({cli} base)" && git pull         # a no-op checkout when already on it
git worktree remove .worktrees/<branch-suffix>   # if the work ran on a worktree
git push origin --delete <branch>
git merge-base --is-ancestor <branch> "$({cli} base)" && git branch -d <branch>
```

**Deleting the branch.** `git branch -d` tests the branch against its upstream
or the current HEAD, not against the base, so it can refuse a branch that is
merged: when the main checkout is on some other branch, or the upstream is
already deleted. `git merge-base --is-ancestor <branch> <base>` is the test that
matters, and it exits zero when the base contains the branch. When it passes and
`-d` still refuses, check the base out and run `-d` again. Do not reach for
`-D`: if the ancestor test fails, the branch holds commits the base does not,
and that is the thing to report.

Removing the worktree deletes its `.venv`, but worktrees share the main repo's
`.git/hooks/` — a pre-commit hook installed from inside the worktree keeps its
`INSTALL_PYTHON` pointed at that deleted venv, and every later commit in the
repo fails. Check for this and re-install from the main checkout:

```bash
grep -q '\.worktrees/' .git/hooks/pre-commit 2>/dev/null \
  && uv sync && uv run pre-commit install
```

Never delete a mainline branch (`{cli} base --all` prints them) — only the
feature branch just merged. Report: review run, plan closed, PR merged, branch
and worktree cleaned up (hook re-pointed if needed).
