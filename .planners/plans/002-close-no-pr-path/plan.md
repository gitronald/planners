---
id: 2
slug: close-no-pr-path
status: done
branch: feature/close-no-pr-path
created: 2026-07-13T17:27:27-07:00
concluded: 2026-10-07T02:16:25-07:00
pr: https://github.com/gitronald/planners/pull/33
---

# Support a no-PR close path in the close skill

## Plan

### Motivation

A user closed a plan with "no PR, minimal review, just merge into dev" — but
the branch already had an open PR (recorded in the plan's frontmatter), so the
close was reinterpreted as "merge through the existing PR, skip the ceremony."
The result was fine, but the instruction and the action diverged: "no PR"
should not silently become "merge the PR."

### Goal

Give the close skill an explicit no-PR path and a rule for conflicts:

1. **No-PR close mode** — when the user asks to close without a PR, merge the
   branch locally (`git merge --no-ff` into the base branch, honoring the
   merge-commit subject conventions), set `pr: null` in frontmatter, and skip
   the PR review/ready/merge steps. Review gate still runs (possibly a
   lighter "minimal review" variant — see below).
2. **Conflict rule** — if a no-PR close is requested but an open PR already
   exists for the branch, STOP and ask: merge via the existing PR, or close
   it unmerged and merge locally. Never reinterpret silently.
3. **Minimal-review variant** — a sanctioned lighter gate (project checks +
   diff skim, no posted review comment) the user can invoke by saying
   "minimal review," instead of the full review→post→fix→verify loop.

### Scope

- Update the `close` skill instructions (and `pipeline`, which embeds close).
- Frontmatter semantics already support it: merged-without-PR is the
  documented `pr: null` case.
- `activate` reports the base's unpushed commits (see the addition of
  2026-09-29 below), with the matching sentence in the `implement` skill.

### Note (2026-09-08): the local merge no longer collides on the index

Plan 004 marks `.planners/README.md` as `merge=union` in `.gitattributes`, and
that attribute applies to exactly the merge this plan performs — a local
`git merge --no-ff` into the base. So the no-PR path does **not** need to handle
an index conflict, and it is the path where 004's fix works best: GitHub's
server-side merge ignores the attribute, but nothing here goes through GitHub.

Two consequences for the steps above. The local merge can leave a plan's row
duplicated when both branches rewrote it (union keeps both), so a no-PR close
should run `planners index .` after merging and commit the result — the same
repair any local merge needs. And `planners validate` now fails on an index that
disagrees with the frontmatter, so the review gate does not have to check for
this by eye; a stale index blocks the commit on its own.

### Addition (2026-09-29): `activate` reports the base's unpushed commits

Handed on from plan 008, which left it as an open question. It is a separate
change from the no-PR path and shares only the release it lands in.

**The problem.** The `implement` skill pushes the base right after `activate`,
and that push publishes every unpushed commit on the base along with the
activation. The skill says to push when every one of them is the plan's own and
to confirm otherwise. That sorting is done by eye, by whoever is following the
skill, and prose can be skipped.

**What is not being built.** The confirmation does not move into `activate`.

- `activate` does not push. Everything it does is local and can be undone, and
  the push is a separate command in the skill.
- A CLI run by a harness cannot hold a confirmation. A prompt either hangs or is
  answered with a flag, which is the prose problem again.
- Pushes already have an enforcement point. `git push` is granted at the
  `confirm` permission level, so at the default level the harness asks before
  any push. The skill's sentence only carries weight where pushes were
  pre-authorized.

**What is being built.** `activate` counts and sorts, and the skill reads the
result. After its commit, `activate` prints one line:

    committed the activation on dev
    dev is 6 ahead of origin/dev (as last fetched): 6 are plan 008's own, 0 are other

When there are others, it lists them, one per line, as `git log --oneline` would.

- **A commit is the plan's own** when every path it touches is under that plan's
  directory (`.planners/plans/<NNN>-<slug>/`, nested subplans included) or is
  the index (`.planners/README.md`).
- **The count is against the local remote-tracking ref.** `activate` does not
  fetch, so the line says "as last fetched". A checkout that is behind its
  remote gives a true count of a stale comparison.
- **It goes quiet when there is nothing to compare against**: no upstream for
  the base, or no remote. This is the same stance as the mainline guard, which
  never blocks a repo it cannot reason about.
- **It never refuses.** The report is information. `--no-commit` prints nothing,
  since it commits nothing.

The `implement` skill's step 3 then changes from a rule to sort by to a fact to
read: push when `activate` reported no other commits, and show its list and
confirm when it reported some.

**Evidence.** In both runs where this came up during plan 008, every unpushed
commit was the plan's own: three on one base, and six on another after a plan
was split into nested subplans. That is the usual case for a plan that was
edited or split before it was activated, so a confirmation on every push would
mostly be noise. The case worth catching is unrelated work that rides along.

**Work.** One helper that lists the commits ahead of the upstream with the
paths each touches, the output line, and tests for: none ahead, all the plan's
own, some other, no upstream, and `--no-commit`.

## Log

- **2026-10-06T19:58:49-07:00** — Implemented both halves on
  `feature/close-no-pr-path` (PR #33, draft).

  **`activate` report** (`e2d8bb8`). New module `planners/ahead.py`: `count`
  resolves the upstream with `rev-parse @{upstream}` (quiet when there is
  none), reads `git log --name-only` for the commits ahead, and sorts each as
  the plan's own when every path it touches is under the plan's directory or
  is the index. `report` renders the one summary line and, when there are
  others, one `git log --oneline`-style line per commit. `activate` prints it
  after "committed the activation on …"; `--no-commit` prints nothing. One
  decision beyond the spec: a commit that touches no paths (a merge commit, an
  empty commit) counts as *other*, since a merge of unrelated work is exactly
  the ride-along worth confirming. Tests in `tests/test_ahead.py` cover
  parsing, ownership edge cases (a sibling plan sharing the number prefix,
  the index alone, no paths), and the five run cases the spec named: in
  sync, all own, some other, no upstream, `--no-commit`.

  **Skills** (`7987ac3`). `implement` step 3 now reads the report instead of
  sorting by eye. `close` gains an opening that reads "no PR" and "minimal
  review" literally, a *Minimal review* block in the review gate, and a
  *The no-PR path* section: the PR-exists check comes first and stops to ask
  (merge via the PR, or close it unmerged and merge locally), then a local
  `git merge --no-ff` with a `merge: <branch>` subject, `{cli} index .` after
  the merge as the union-merge repair, and `pr: null`. `pipeline` names how a
  no-PR request meets its always-opened draft PR. The rule file's skill list
  carries a one-line pointer. CHANGELOG `[Unreleased]` has both entries.

  Checks run locally at `7987ac3`: ruff check, ruff format --check, pyrefly,
  pytest (372 passed, 95% coverage), `planners validate .`.

- **2026-10-07T02:16:25-07:00** — Review gate at close (`/code-review`, medium;
  posted to PR #33). Checks clean before and after: ruff, ruff format, pyrefly,
  pytest (374 passed, 95% coverage), `planners validate .`.

  **Review follow-up** (`f2d0446`). Raised and actioned, each with a test:
  `git log --name-only` C-quotes non-ASCII paths, so a plan's own commit
  touching one read as *other* — the log now runs with `core.quotepath=off`;
  default rename detection lists only a move's destination, so a `git mv` from
  outside the plan into it read as the plan's own while its deletion outside
  shipped unconfirmed — now `--no-renames`. Without a test: `plan_dir` passed
  as posix (Windows only); one partition pass and a dead branch in
  `parse_log`; the test file's local git helper replaced by `helpers.git_out`.
  In the skills: the no-PR path now says the gate's PR steps (post, `gh pr
  ready`) are skipped; `gh pr close` moved from before step 1 to step 6 so a
  gate that blocks the close cannot leave the PR closed with a false comment;
  and `implement` no longer reads a withheld report as "nothing to push to",
  since a base with a remote but no tracking upstream is silent too. Conscious
  no-ops: the private `_git_out` twin in `base.py` (differs on strip; a
  refactor outside this plan), the draft-plan literal duplicated across three
  test files (pre-existing pattern), silence on any git failure (by design),
  and `git checkout "$(planners base)"` failing when the base lives in its own
  worktree (pre-existing in the default step 6). Then merged `origin/dev` in
  (plan 010 had landed) and regenerated the index: the union merge had kept
  both versions of this plan's row.

## Retrospective

- The spec's "no PR" conflict rule held up: the original misreading (merge the
  existing PR when asked for none) is now a question the skill must ask, and
  pipeline names where that question lands.
- The two real bugs the review found were both in how `git log --name-only`
  is read, not in the sorting logic — path quoting and rename detection. Any
  helper that parses porcelain-ish git output should start from `-c
  core.quotepath=off` and an explicit rename stance, and a test with a
  non-ASCII name costs one line.
- Writing the first version of the no-PR path as "steps 1–5 as written" hid a
  contradiction with the gate's PR steps; a path that removes a thing has to
  say which later steps touched it.
- Closing the PR before the gate was the same mistake the plan set out to fix,
  in miniature: an action taken before the decision it depends on. Irreversible
  or outward-facing steps belong after the gate.
- The index duplicated its row on the local merge from dev exactly as plan 004
  predicted; the post-merge hook repaired it and the only work left was the
  commit. The GitHub-side conflict on the same file is why the merge was done
  locally first.
