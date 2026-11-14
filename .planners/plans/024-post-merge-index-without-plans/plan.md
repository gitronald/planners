---
id: 24
slug: post-merge-index-without-plans
status: implemented
branch: feature/024-post-merge-index-without-plans
created: 2026-11-12T22:10:19-08:00
concluded:
pr: https://github.com/gitronald/planners/pull/71
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

### Landing from a cloud session

The implementation was written in a sandboxed cloud session and is reauthored
here, batch by batch, under the gate. Its commits are a proposal and are not
merged or cherry-picked.

- Reauthored from `origin/ccr-08cc166f-iubhf8` @ `3522aab8` (8 commits, forked
  from `dev` @ `a5d1742`, no PR). The rest of that branch, a lifecycle bug sweep,
  lands through plan 025, stacked on this plan's branch.
- Gate: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pyrefly check`, `uv run planners validate .`
- Per-commit review: `../025-lifecycle-bug-sweep/review.md`

| # | Batch | Desktop subject | Mobile shas | Fixes / regenerations | Approval |
|---|---|---|---|---|---|
| 1 | `tests-init-git` | `update cli tests to share init_git and run as root` | 5cfa986c | Adds the `from tests.helpers import init_git` import itself, since on mobile that line came in with 53b56a7, which lands later here; Drops the module's own _init_git and the inline git init in test_add_commits_by_default_in_git_repo in favor of tests.helpers.init_git; Replaces the chmod 000 unreadable-root test with a regular-file root (NotADirectoryError), renamed test_git_turns_an_unusable_root_into_a_cli_error; No Co-Authored-By or Claude-Session trailers |  |
| 2 | `index-no-plans-dir` | `update index to write nothing without a plans directory` | 53b56a74 ff1b40a4 3522aab8 | Early return plus docstring in index() as on mobile. cols still defaults to "curated" at this point; Tests: the parametrized no-plans-dir test, the leaves-other-.planners-files test, the empty-plans-dir and removed-plans tests, the first-add test, and the post-merge hook test. Adds the HOOKS, commit_all, git, and git_out imports (init_git is already imported); CHANGELOG bullet under Unreleased/Fixed from ff1b40a, without the 'refused add or finalize' sentence that 3522aab appended, which goes in the add-letters batch; README command-reference line and the SKILL.md paragraph from ff1b40a; No trailers |  |

Dropped: `e7b7840c` (`plan [activate]`), `6afbdb69` (`plan [log]`), and
`7c8edf3a` (`plan [implemented]`). These are the lifecycle records the cloud
session wrote by hand on its own branch, with its own hashes and checks. The
lifecycle is rerun here with `planners start`, `log`, and `implemented`.

## Log

- **2026-11-14T10:32:17-08:00** — Activated.
  - Branch: `feature/024-post-merge-index-without-plans`
  - Base: `dev` at `fb82004`
  - Worktree: `.worktrees/024-post-merge-index-without-plans`
  - PR: pending
- **2026-11-14T10:37:29-08:00** — Reauthored from `origin/ccr-08cc166f-iubhf8` @ `3522aab8`, both batches retyped by hand and gated.
  - `1cdde87` update cli tests to share init_git and run as root <- `5cfa986c`
  - `acc8b1a` update index to write nothing without a plans directory <- `53b56a74`, `ff1b40a4` (the `3522aab8` edits to these files go to plan 025)
  - `git diff 5cfa986 HEAD -- planners tests CHANGELOG.md README.md` is empty: the code, tests, and docs match the mobile tree at that commit.
  - Gate at `acc8b1a`: pytest 795 passed (coverage 95%), ruff check and format, pyrefly 0 errors, planners validate ok. The root-only test failure the cloud session saw is fixed by `1cdde87`.
- **2026-11-14T10:37:34-08:00** — PR opened: https://github.com/gitronald/planners/pull/71
- **2026-11-14T11:57:51-08:00** — Implemented: 4 commits ahead of `dev`.
- **2026-11-14T11:58:04-08:00** — Review gate: `/code-review` (low) on #71 found nothing: the correctness finder returned no candidates and the gap sweep added none. No follow-up commits.
