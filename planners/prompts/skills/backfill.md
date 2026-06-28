---
name: backfill
description: Fill missing plan frontmatter (branch, concluded, pr) from git history and PRs; auto-retire stale inactive plans.
---

# backfill — fill missing frontmatter from history

Fill in missing `branch`, `concluded`, and `pr` fields across plan files by
cross-referencing git history and GitHub PRs, and auto-retire stale `inactive`
plans. Plan state lives only in frontmatter — there is no checklist file to
reconcile.

## Status labels and order

`status` is one of, in the index's sort order:

1. `active` — in progress (open)
2. `draft` — proposed, not started (open)
3. `done` — finished (closed; fill `concluded` + `pr`)
4. `inactive` — parked, may resume (keep `concluded`/`branch`/`pr` empty)
5. `retired` — neutrally dead: superseded or no longer needed (closed; fill
   `concluded` = the date it was retired)

Closure is always `retired` — there is no separate failed status. Closed states
(`done`/`retired`) fill `concluded` and use explicit `null` for a
genuinely-absent `branch`/`pr`. `inactive` keeps those fields empty (pending).

## Auto-retire: inactive → retired (90-day rule)

For each `inactive` plan, compute `age = today - created`. If `age >= 90 days`,
switch to `status: retired` and set `concluded = created + 90 days` — the
deterministic threshold date, not "now", so re-runs are idempotent. Leave
`branch`/`pr` as `null` unless real values exist. If `age < 90 days`, leave it.

## Steps

### 1. Scan and gather

- Glob `.planners/plans/*/plan.md`.
- Gather context in one pass: `git log`, merged PRs, repo URL, and commit→PR
  ranges. Use `git log --no-merges <prev-merge>..<merge>` per PR to see the
  actual work; PR merge commits themselves show nothing useful with
  `--first-parent`.

### 2. Read frontmatter

Read each plan's frontmatter (filename, status, branch, created, concluded, pr),
marking empty fields. Delegate bulk reads to an Explore subagent if there are many.

### 3. Match plans to PRs (in the main context)

Do the matching yourself — do not delegate it. Match by function/module names
and action verbs in commit messages vs. plan descriptions. Use
`git merge-base --is-ancestor <commit> <merge>` to confirm ancestry when unsure.
For `concluded`, prefer the last implementation commit over version-bump or
merge commits. Build a full assignment table before editing.

### 4. Apply edits

Edit only the frontmatter fields (`branch`, `concluded`, `pr`, and `status` for
auto-retire flips). **Empty vs `null`:** empty = pending (open plans); explicit
`null` = closed and confirmed absent (only on `done`/`retired`). Never the
string `none`. Split large batches across edit subagents given explicit values.

### 5. Refresh the index and validate

```bash
{cli} index .
{cli} validate .planners/plans
```

Fix any violations the validator reports, then commit.
