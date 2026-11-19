---
id: 28
slug: review-rounds-and-lifecycle-paperwork
status: implemented
branch: feature/028-review-rounds-and-lifecycle-paperwork
created: 2026-11-19T14:30:37-08:00
concluded:
pr: https://github.com/gitronald/planners/pull/79
---

# Treat review follow-ups as one round and cut lifecycle paperwork

## Plan

### Background

A survey of the plans, branch histories, and session records in a set of repos that
use planners looked for places where the lifecycle produces commits and command
runs that carry no information. Four came up often enough to fix, and one
misreading came up often enough to word against.

- **Every review item is its own round trip.** A plan is marked `implemented`, the
  reviewer asks for a small change, and the session runs `activate`, makes the
  change, logs it, and runs `implemented` again: three plan commits for one edit.
  A reviewer reading a rendered page or a table asks for many small changes in a
  row, so one sitting produces a long run of these. The time a plan spends
  reactivated is typically about a minute, because the change is made first and the
  three commands follow it. The PR is ready the whole time: `activate` does not
  return it to draft. The text asks for this. The `implement` skill ends "mark it
  implemented again when the follow-up is pushed", and neither it, the rule, nor
  the `update` skill says how much work a reactivation is for.
- **A Log entry is its own commit.** `plan [log]` is the commonest plan commit by a
  wide margin, and a large share of the commits on a typical feature branch. Most
  entries describe a change committed a moment earlier. `log --no-commit` exists,
  and no skill says when to use it.
- **The index repair after a merge is committed by hand.** The `post-merge` hook
  regenerates the index and leaves it uncommitted, and the session then writes a
  commit that holds nothing else. A branch that merges its base several times
  collects one of these per merge.
- **`start` runs three or four times for one plan.** Each push is its own stop: one
  for the base, one for the new branch, then a run after the first commit to open
  the PR, and often a run between them that only confirms a push.
- **Review placed before `implemented`.** Sessions have written next steps that put
  a review of the PR first and `implemented` after it, which leaves the PR in
  draft through its own review. The order is stated in three skills. What is not
  stated is the difference between a check of your own work, which does come
  first, and the review, which `implemented` asks for.

### Decisions

1. **A reactivation covers a review round, not a review item.** The first change
   asked for on an `implemented` plan returns it to `active`, once. It stays
   `active` through every follow-up of that round. `implemented` runs again when
   the reviewer says the round is over, and not at all when what they ask for next
   is the close, which already accepts an `active` plan. The alternative, leaving
   the plan `implemented` and only logging each follow-up, was considered: it is
   cheaper still, and it leaves the status saying "waiting on review" while the
   work is being changed
2. **`activate` says so when it returns a plan from `implemented`.** One more line
   of output, no refusal, no flag. A warning in `implemented` (reactivated minutes
   ago) was considered and dropped: by then the paperwork is written
3. **A Log entry rides with the change it describes.** When an entry records a
   change that is being committed, it is written with `log --no-commit` and
   committed with that change. `log` on its own stays for an entry with no change
   beside it: a decision, an answer, a result. This is wording only
4. **The hook amends the index repair into the merge commit.** After a clean merge
   the regenerated index goes into the merge commit the merge has just made, when
   that commit is on no remote branch. Otherwise it is left uncommitted, as now. A
   commit made by the hook was considered: it removes the typing and keeps the
   commit. A merge driver was considered: it runs before the plan files it would
   read have been merged
5. **`start` stops once for its pushes.** One run does every local step and ends at
   a single stop that names both pushes, the base first. The base's push still
   comes before the branch's, so the activation is on the remote's mainline whether
   or not the branch lands. The stop still exits 1: it is where an `&&` chain
   should end
6. **A self-check comes before `implemented`, the review after.** One paragraph in
   the `implement` skill

### Changes

Review rounds (decisions 1 and 2):
- `planners/prompts/skills/implement/SKILL.md`: the last paragraph of step 5.
  Review that asks for more work returns the plan to `active` once for the round;
  it stays there through the follow-ups; `implemented` again when the reviewer says
  the round is done, or straight to the close
- `planners/prompts/rules/planners.md`: the sentence on review feedback in
  *Frontmatter* says the same in a clause
- `planners/prompts/skills/update/SKILL.md`: the reactivate row's triggers and the
  **Reactivate** paragraph. "more changes" on a plan that is already `active` is
  not a reactivation
- `planners/cli.py`, `activate`: after the commit of a return from `implemented`,
  print the hint. The return from a block prints what it prints now
- The `close` skill's review gate is unchanged: its fixes are part of the close

Log entries (decision 3):
- `implement` step 3: a paragraph on `log --no-commit` with the change
- `update`, **Log**: the same, with the two-command form
- `pipeline`: the worker brief's line on logging says the same in a clause

Index after a merge (decision 4):
- `planners/cli.py`, `index`: an `--after-merge` option, which the hook passes.
  After regenerating, when the index changed, `HEAD` is a merge commit, no
  remote-tracking branch contains it, and no other operation is in progress, the
  index is amended into `HEAD` with the message kept. The amend skips the commit
  hooks, as the merge that made the commit did. In every other case the change is
  left uncommitted and the output says why
- `planners/host.py`: the hook's args gain `--after-merge`; the comment above it
  is rewritten. `install` rewires an existing config
- The rule's *Storage layout* paragraph, the `index` skill's merge cases, the
  `update` skill's Log paragraph, and the `log` command's docstring describe the
  new behavior and keep the uncommitted case
- A fast-forward makes no merge commit, and a tip that validated upstream has a
  current index, so nothing changes there

`start` (decision 5):
- `planners/start.py`: `check_base_pushed` gains a way to report a pending push of
  the plan's own commits without stopping, and a function builds the combined stop
- `planners/cli.py`, `_start`: when the base is ahead by the plan's own commits
  only, go on to the branch, the worktree, and the setup, then stop once with both
  pushes on one line (`git push origin <base> && git push -u origin <branch>`).
  When the base is level, the stop names the branch's push alone, as now
- Kept as they are: the earlier stop when the base carries commits that are not
  the plan's own, which someone has to confirm; the base with no upstream, which
  joins the combined stop with `-u`; a `single-branch` remote and a repo with no
  remote; the re-run from the branch that opens the PR
- `implement` step 2: the stops list, and a line that the run after the pushes is
  not needed: the next `start` is the one after the first commit
- The `start` docstring

Self-check (decision 6):
- `implement` step 5: before `implemented`, read your own diff and run the checks.
  The review (the repo's review skill, the reviewer's reading) comes after it:
  `implemented` is what asks for one, and the close's gate runs it

Docs: `CHANGELOG.md` under `[Unreleased]`; `README.md` where it describes the hook.

### Tests

- `activate` on an `implemented` plan prints the hint; on a `blocked` plan and on a
  first activation it does not
- `index --after-merge`: a merge of two branches that each changed a plan's row
  ends with a clean tree and one row per plan in the merge commit; the same merge
  whose commit is already on a remote branch is left uncommitted; a fast-forward
  changes nothing; a plain `index` never amends; a non-merge `HEAD` is never
  amended
- `start`: a first run on a base ahead by the plan's own commit creates the branch
  and worktree and stops once, naming both pushes; a base carrying another commit
  stops before the branch exists; a level base stops for the branch alone; the run
  after both pushes reports them done
- The hook definition passes `--after-merge`, and an install rewires an existing
  config that lacks it
- The full gate: `uv run ruff check . && uv run ruff format --check . &&
  uv run pyrefly check && uv run pytest`

### Order

1. The wording for decisions 1, 3, and 6 (no code)
2. The `activate` hint with its tests
3. `index --after-merge`, the hook args, and their tests
4. The `start` stop with its tests, and the `implement` skill's step 2
5. CHANGELOG, README, the full gate

### Out of scope

- What a resuming session loads. The rule was scoped to plan files in 0.17.0, and
  what remains is smaller than the four costs above
- Returning the PR to draft on a reactivation
- A status for "under review, being changed"
- Rewriting the Logs of plans that cycled. They are history

## Log

- **2026-11-19T14:31:19-08:00** — Activated.
  - Branch: `feature/028-review-rounds-and-lifecycle-paperwork`
  - Base: `dev` at `ec10f2a`
  - Worktree: `.worktrees/028-review-rounds-and-lifecycle-paperwork`
  - PR: pending
- **2026-11-19T14:32:46-08:00** — PR opened: https://github.com/gitronald/planners/pull/79
- **2026-11-19T14:42:42-08:00** — Implemented decisions 1 to 6 in five commits. The full gate (ruff check, ruff format --check, pyrefly check, pytest: 835 passed, coverage 94.95%) ran clean on the tree of `567a5cf`.
  - Decision 4, departure in mechanism: the repair cannot be put into the merge commit with `git commit --amend`. Git runs `post-merge` before it clears the merge state, so `MERGE_HEAD` is still present, `--amend` refuses, and a plain commit would record a second merge. A test that lets git run the real hook caught it. The repair is written with plumbing instead (`read-tree` and `update-index` on a scratch index, `commit-tree`, `update-ref`), in the new `planners/aftermerge.py`. The outcome is the one decided: same parents, message, and author, with the regenerated index, and a clean tree when the merge returns. A `MERGE_HEAD` that names HEAD's own parents is the merge git has just committed and is allowed; any other is a merge still open and is not.
  - Decision 4, two additions. A signed merge commit is left alone, since the rewrite would drop the signature. And `install` does not rewire an entry that is already present (the wiring keys a hook on its id), which the plan assumed it did: `install` now gives an earlier release's exact `planners-index` entry the option, and `install --check` reports one without it as `outdated`, without gating. This repo's own config was updated by hand to the entry `install` writes.
  - Decision 5, two departures. A base with no upstream keeps its own early stop and does not join the combined one: pushing it publishes the whole branch, which is not the plan's own commits. And the single stop opened a gap the two stops did not have: a session can push the branch and leave the base. A re-run from the plan's branch now checks that the branch's fork point from the recorded base is on the base's upstream, and stops before the PR when it is not. The `push-base` line gained a `waiting` outcome.
  - Decision 3: the `pipeline` skill's work brief was left as it is. Its log line asks for a closing summary, which has no change beside it, and the worker reads the `implement` skill, which carries the new paragraph.
  - Ten `start` tests were rewritten for the new order (the first run now reaches the branch, the worktree, and the setup), and four were added for the stop's shapes. Nine tests cover `index --after-merge`, one of them through a real git hook, and three cover the entry upgrade.
  - Checked by hand and not kept as a test: the repair under the pre-commit framework's own `post-merge` shim, in a scratch repo. The tree was clean, the merge commit kept both parents, and the merge state was cleared.
  - Not verified: a signed merge commit (no key in the test environment), git versions other than the one here for when `MERGE_HEAD` is cleared, and Windows.
- **2026-11-19T14:43:00-08:00** — Implemented: 7 commits ahead of `dev`.
- **2026-11-19T15:00:55-08:00** — Review gate at the close: the repo's review skill ran on the PR at its medium level and the findings were posted there. Seven findings, four of them reproduced in scratch repos, all four in `planners/aftermerge.py`. Fixed in two commits; the full gate (ruff check, ruff format --check, pyrefly check, pytest: 843 passed, coverage 95.03%) ran clean on the tree of `60d0357`.
  - Review follow-up, actioned with tests. A merge commit at HEAD was taken for the merge git had just made, so a fast-forward or a squash onto an earlier unpushed merge commit rewrote that commit (the hook runs after both, and neither makes a commit). The repair now requires `MERGE_HEAD` to name HEAD's own non-first parents, which git still holds while `post-merge` runs for a real merge. Two tests let git run the hook after a fast-forward and after a squash, and a third covers `--no-ff` over a branch that could have fast-forwarded.
  - Review follow-up, actioned with tests. The rewritten message gained a blank line at its end (`log --format=%B` adds a newline); it is now read from the commit object, and a test compares the stored message before and after. Only `gpgsig` was guarded, though the rewrite drops every extra header: a commit with any header other than tree, parent, author, and committer is now left alone, which covers the `mergetag` of a signed tag and `encoding`. With the index untracked, HEAD was rewritten and the output said it was left uncommitted: the repair now refuses before the rewrite when the merge commit does not track the index.
  - Review follow-up, actioned without a new test. `check_activation_published` now calls `finish.is_ancestor`, which reports a git failure as one instead of as a base that is not pushed. The two outcomes it had are covered already; the third needs a damaged repo.
  - Conscious no-ops. The entry-upgrade pattern in `planners/host.py` is not tied to the hook id, and it takes a hand-duplicated entry under another id to reach. `_blocker` forks one `rev-parse` per state file, a few milliseconds once per merge whose index changed.
  - Departure from decision 4 that follows from the first fix: `index --after-merge` run by hand, outside the hook, never amends. The help text, the `index` skill, and the changelog say so.
  - Not verified: a commit with a real signature (the guard is tested with a crafted `gpgsig` header), a message with carriage returns or bytes that are not UTF-8, and Windows. A git that clears `MERGE_HEAD` before the hook now leaves the repair uncommitted, where before it was an unknown.
