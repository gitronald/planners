---
id: 30
slug: review-leftovers
status: active
branch: feature/030-review-leftovers
created: 2026-11-20T12:20:14-08:00
concluded:
pr:
---

# Fix the leftovers from the codebase review

## Plan

### Goal

Plan 029 closed with three items that no plan owned. This plan takes them:

1. `finish` tells a repo with no remote to push.
2. `finalize` can number two plans staged in the same second in reverse order.
3. The review's repeated-work findings, O1 to O4. Plan 029 assessed these and left
   them. The owner chose to act on O1 and O3. O2 and O4 stay as plan 029 decided, for
   the reasons it gives.

The review report is plan 029's sidecar
[`review.md`](../029-codebase-review-and-cleanup/review.md). Line numbers here are for
`dev` at `898117c`.

### 1. `finish` asks a repo with no remote to push

`_check_merged` (`planners/cli.py:1931`) has two wordings for a branch that is not merged
yet on the no-PR path. `local_only` (a `single-branch` remote) prints the merge alone.
Every other case prints `{merge} && git push` (`:1975`). With no remote,
`_remote_or_local` falls back to the local base (`:1886`), so the check itself is right.
Only the message is wrong: it asks for a push that fails because there is nowhere to
push.

- Change: when origin is `none` (`remote_mod.classify(root).kind`), print the merge
  alone, as for `single-branch`. Classify the remote once in `finish` (`:2058` already
  does) and pass what `_check_merged` needs. Do not call `classify` a second time.
  `_print_merge` (`:2010`, behind `--print-merge`) already prints the merge alone, so
  leave it as it is.
- Test: a no-PR `finish` in a repo with no remote, on an unmerged branch, stops with the
  merge command and no `git push`. The existing wordings for `bare` or `github` and for
  `single-branch` are unchanged.

### 2. `finalize` orders same-second plans by chance

`_collect_staged` (`planners/cli.py:675`) sorts by `created`, then by the staging
directory's name. `created` has whole-second precision. The directory name is
`{secrets.token_hex(4)}-{slug}` (`:1030`), so for two plans staged in the same second
the tie-break follows a random token, not the order of staging. Plan 029 saw two
deferred plans numbered in the reverse of the order they were staged in.

- Change: name the staging directory so that sorting by name follows the order of
  staging. Lead with a zero-padded `time.time_ns()`, keep the random token for
  uniqueness, and keep the slug: `{ns:019d}-{token}-{slug}`. The tie-break by name then
  follows staging order. Directories staged before this change (`<token>-<slug>`) still
  sort, by token as now. Do not add a frontmatter key: the seven-key schema is fixed.
- Check that nothing parses the staging directory name back into a slug. `finalize`
  reads the slug from frontmatter (`:1134`), but confirm by grep. Update the `add`
  skill's `.planners/staging/<token>-<slug>/` line and the `--defer` help if they
  describe the name.
- Test: two `add --defer` calls in the same clock second (freeze `_now()` the way the
  existing tests do) finalize in the order they were staged, whatever their tokens.

### 3. O1: one mainline detection per activation

A first activation that commits runs `base_mod.detect` from `_guard_base_branch`
(`:535`), from `_activation_entry` (`:1481`), and from `_current_branch` (`:1499`). Each
call is up to six git processes (`planners/base.py`), and the last caller needs only
the branch name.

- Change: detect once before the commit and pass the `Mainline` to the guard and to the
  activation entry. After the commit, read only the current branch (`git branch
  --show-current` through `proc`, or the existing helper if one is there), not a full
  `detect`.
- Keep: detached and unborn HEAD handling, and the `--allow-branch` path. Do not reuse a
  detection across a commit, a hook, a checkout, or a fetch.
- Test: count `detect` calls on a first activation (monkeypatch a counting wrapper) and
  assert one. The existing activation tests must still pass unchanged.

### 4. O3: cache review's repeated git reads

`_Git` (`planners/review.py:338`) caches trees, tags, and whether `origin` exists. Its
`show` (`:392`) and `log` (`:397`) are not cached, so one gather of the existing
multi-reference fixture repeats the same `git log` three times and the same `git show`
twice.

- Change: cache `show` by `(revision, path)` and `log` by the full argument tuple,
  failures included, on the `_Git` instance, which lives for one gather.
- Keep: the keys must include the revision, every history argument (`--since`), and
  every pathspec. No cache outlives the command.
- Test: on the fixture with several references to one file, count subprocess calls (or
  calls to the uncached method) and assert that each distinct query runs once.

### O2 and O4: not changed

These keep plan 029's decision. O2 would couple the index helpers for a parse of about
thirty files. O4 was measured to save well under a second, at the cost of a marker on
every CLI test module.

### Order of work

One commit per item, each with its test, in this order: 1, 2, 3, 4, then the CHANGELOG
`[Unreleased]` entries (`Fixed` for 1 and 2, `Changed` for 3 and 4).

Checks:
`uv run ruff check . && uv run ruff format --check . && uv run pyrefly check && uv run pytest`.

### Out of scope

- O2 and O4.
- Any other wording in `finish` or the `close` skill. Plan 029 already gave the no-PR
  table per remote kind.

## Log

- **2026-11-20T12:20:51-08:00** — Activated.
  - Branch: `feature/030-review-leftovers`
  - Base: `dev` at `58cec7f`
  - Worktree: `.worktrees/030-review-leftovers`
  - PR: pending
- **2026-11-20T12:21:02-08:00** — Choices for this run, made by the owner: change O1 and O3, and leave O2 and O4 as plan 029 decided. Run as a full pipeline: a worker implements the plan, the review gate is the repo's `/code-review` at medium, and the close merges through the PR.
