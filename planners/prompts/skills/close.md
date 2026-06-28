---
name: close
description: Close a finished plan — review gate, final log, retrospective, frontmatter, merge, and cleanup.
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

### 2. Review gate (review → fix → verify) — MANDATORY, BEFORE MERGE

Do not call `gh pr merge` until this gate has run, its review is posted to the
PR, and every finding is fixed or recorded as a conscious no-op.

```bash
gh pr list --head "$(git branch --show-current)" --state open --json number --jq '.[0].number'
```

- Review the PR diff with the project's review skill (`/code-review`, or
  `/review PR <number>`).
- Post it: `gh pr comment <number> --body-file <file>`.
- Fix actionable findings at the source, each with a paired regression test.
  Record intentional skips as conscious no-ops.
- Run the full check gate (`uv run pytest && uv run ruff check . && uv run pyrefly check`)
  until clean; commit fixes and push.
- `gh pr ready <number>`.

### 3. Final log entry

If commits (including review fixes) are not yet in `## Log`, append a dated
entry. If the gate produced fixes, include a **"Review follow-up"** sub-entry:
what was raised, what was actioned (with tests), what was a conscious no-op.

### 4. Retrospective

Append a concise `## Retrospective` (3–6 bullets): what went as planned vs.
changed, key decisions, and what would help next time. Insight, not a summary.

### 5. Closing frontmatter and index

- `concluded` = the last implementation commit's authored date
  (`git log --format="%aI" -1`), not now.
- `pr` = the PR URL (`gh pr list --head "$(git branch --show-current)" --state all --json url --jq '.[0].url'`);
  if merged with no dedicated PR, write `pr: null` — never the string `none`.
- Set `status: done`.
- `{cli} index .` and commit the regenerated `.planners/README.md`.

### 6. Commit, merge, clean up

```bash
git add .planners/plans/{NNN}-<slug>/plan.md .planners/README.md && git commit -m "plan [close]: {NNN} - {title lowercase}"
git push
gh pr merge --merge
git checkout dev && git pull                     # run cleanup from the main checkout
git worktree remove .worktrees/<branch-suffix>   # if the work ran on a worktree
git push origin --delete <branch>
git branch -d <branch>
```

Removing the worktree deletes its `.venv`, but worktrees share the main repo's
`.git/hooks/` — a pre-commit hook installed from inside the worktree keeps its
`INSTALL_PYTHON` pointed at that deleted venv, and every later commit in the
repo fails. Check for this and re-install from the main checkout:

```bash
grep -q '\.worktrees/' .git/hooks/pre-commit 2>/dev/null \
  && uv sync && uv run pre-commit install
```

Never delete `dev` or `main`. Report: review run, plan closed, PR merged, branch
and worktree cleaned up (hook re-pointed if needed).
