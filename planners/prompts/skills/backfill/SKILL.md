---
name: backfill
description: Fill missing plan frontmatter (branch, concluded, pr) from git history and PRs; auto-retire stale inactive plans.
metadata:
  version: "1.0.0"
---

# backfill — fill missing frontmatter from history

Fill in missing `branch`, `concluded`, and `pr` fields across plan files by
cross-referencing git history and GitHub PRs, and auto-retire stale `inactive`
plans. Plan state lives only in frontmatter — there is no checklist file to
reconcile.

## What to fill

The planners rule defines each `status` and the empty-vs-`null` convention.
For the closed states (`done`/`retired`), fill `concluded` and use explicit
`null` for a genuinely-absent `branch`/`pr`; for `inactive`, keep those fields
empty (pending). Closure is always `retired` — there is no separate failed
status.

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

Read each plan's directory name and its frontmatter (status, branch, created,
concluded, pr), marking empty fields. Delegate bulk reads to an Explore subagent
if there are many.

### 3. Match plans to PRs (in the main context)

Do the matching yourself — do not delegate it. Match by function/module names
and action verbs in commit messages vs. plan descriptions. Use
`git merge-base --is-ancestor <commit> <merge>` to confirm ancestry when unsure.
For `concluded`, prefer the last implementation commit over version-bump or
merge commits. `validate` fails a `concluded` earlier than `created`, so when that
commit is older than the plan, use `created` instead. Build a full assignment table
before editing.

### 4. Apply edits

Edit only the frontmatter fields (`branch`, `concluded`, `pr`, and `status` for
auto-retire flips), with the empty-vs-`null` convention above and never the
string `none`. Split large batches across edit subagents, giving each the
explicit values to write.

### 5. Refresh the index and validate

```bash
{cli} index .
{cli} validate .planners/plans
```

Fix any violations the validator reports, then commit.
