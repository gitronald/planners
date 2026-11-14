---
id: 24
slug: post-merge-index-without-plans
status: active
branch: ccr-08cc166f-iubhf8
created: 2026-11-12T22:10:19-08:00
concluded:
pr:
---

# Keep the post-merge index hook from creating .planners/ in a repo with no plans

## Plan

### Problem

The `planners-index` post-merge hook (`HOOKS` in `planners/host.py`, also
shipped in the repotemplates pre-commit config) runs `planners index .` after
every clean merge, with `always_run: true`. `index` writes through
`_refresh_index`, which calls `mkdir(parents=True)` on `.planners/` and writes a
`README.md` with only the table header. So in a repo that carries the hooks but
has no plans yet, any `git pull` that merges, or any local merge, leaves an
untracked `.planners/README.md` behind.

Reproduced with planners 0.16.0 in a fresh `git init` repo: `planners index .`
prints `updated .planners/README.md`, and `git status` shows `?? .planners/`
containing an empty `# Plans` table. It was first seen when a template-synced
repo with no plans was pulled after a merge: the clone turned up dirty in the
next health check, with nothing to commit.

### Fix

- `planners index` exits 0 without writing when `.planners/plans/` does not
  exist, and says so (`no .planners/plans/; nothing to index`). An index for a
  repo with no plans has no rows to render, so writing one helps nothing.
- The paths that create a plan (`add`, `finalize`, `add --defer`, and the
  nested and lettered forms) keep calling `_refresh_index` directly, so the
  first plan still writes the index in the same commit as before.
- A repo that has `.planners/plans/` with no plan directories in it (every plan
  retired and removed, say) still gets its index regenerated: the check is on
  the directory, not the plan count.

### Tests

- `index` in a repo without `.planners/` writes nothing and exits 0.
- `index` in a repo with `.planners/plans/` and no plans writes the empty
  table (current behavior).
- The first `add` in a fresh repo still writes `.planners/README.md` and
  commits it.
- The post-merge hook path (`planners index .`) on a plan-less repo leaves
  `git status` clean.

### Out of scope

- The `validate` hook, which already matches only plan files.
- Changing what the template ships: the hook entry stays `planners index .`.

## Log

- **2026-11-14T07:52:08+00:00** — Activated.
  - Branch: `ccr-08cc166f-iubhf8`
  - Base: `ccr-08cc166f-iubhf8` at `a5d1742`
  - Worktree: none (main checkout)
  - PR: pending
