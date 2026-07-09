---
name: implement
description: Start implementing a plan — activate it on the base, branch from that commit, begin coding, and open a draft PR.
---

# implement — start work on a plan

Flip the plan to `active` on the base and commit it there, branch (and worktree)
from that activation commit, start building, and open a draft PR. Parse the plan
number (e.g. `021`) or path from the request; if ambiguous, glob
`.planners/plans/{NNN}-*/plan.md`.

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
git rev-list --left-right --count HEAD...@{upstream}
```

- The activation commit (step 3) lands on the **base**, so be on the base branch
  in the main checkout — usually `dev`. If the current branch is not `dev`, ask
  whether to base it on the current branch or `dev`, then check that branch out.
- Behind upstream → pull the base first so the activation commit sits on top of
  the latest; ahead → note the unpushed commits.
- The activation commit stages only the plan file and the index, so unrelated
  uncommitted changes in the checkout are left untouched.

### 3. Activate the plan on the base

Do this **on the base branch, before creating the branch**, so the activation is
recorded on the mainline regardless of whether the feature branch ever lands.

- Determine the branch name: the plan's `branch:` field if set, otherwise derive
  `feature/<slug>`.
- Edit the plan frontmatter: set `status: active` and fill `branch:`.
- Refresh the index so the row moves draft → active:
  ```bash
  {cli} index .
  ```
- Commit the plan file and index on the base, then push:
  ```bash
  git add .planners/plans/{NNN}-<slug>/plan.md .planners/README.md
  git commit -m "plan [activate]: {NNN} - {title lowercase}"
  git push
  ```

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
git worktree add .worktrees/<branch-suffix> -b <branch> <base>
cd .worktrees/<branch-suffix>
git push -u origin <branch>
```

`<branch-suffix>` is the branch's final path component (e.g. `003-<slug>` for
`plan/003-<slug>`); `<base>` is the branch chosen in step 2. **Run the remaining
steps from inside the worktree.** To work in the main checkout instead, use
`git checkout -b <branch>` here and skip the worktree.

### 5. Implement

Work inside the worktree. Follow the plan's implementation order; commit in
logical chunks and push as you go.

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

Record the PR URL in the plan's `pr:` field and commit it. Keep pushing as you
work so the draft PR stays current; it stays a draft until `/planners close`.

When the plan is closed (`/planners close`) and its branch is merged, remove the
worktree: `git worktree remove .worktrees/<branch-suffix>`. Worktrees share the
main repo's `.git/hooks/` — a pre-commit hook installed from inside the worktree
(`uv run pre-commit install`) embeds the worktree's `.venv` python as its
`INSTALL_PYTHON`, so once the worktree is removed the hook fails on every later
commit. `/planners close` re-installs it from the main checkout
(`uv sync && uv run pre-commit install`) as part of cleanup.
