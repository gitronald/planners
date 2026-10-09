---
id: 13
slug: harden-close-cleanup
status: active
branch: feature/harden-close-cleanup
created: 2026-10-09T15:26:29-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/38
---

# Run the close cleanup without handing it to the user

## Plan

**Context.** `/planners close` ends with routine steps: remove the worktree,
merge the PR, pull the base, delete the branch on the remote and locally, and
re-point the pre-commit hook. None of them needs a decision. Yet a close can
end by handing these steps to the user as commands to paste. That happened
when plan 012 closed, for two reasons:

- The session had run `cd` into the worktree in its persistent shell. The
  harness then reported the worktree as the session's working directory. The
  session took that as an isolation block without testing it, and stopped
  short of the main checkout. A single read-only command run from the main
  checkout later showed it was reachable the whole time.
- The skill's step 6 does not say who runs the main-checkout block, or how a
  session gets there. It also contradicts the worktree rule: its worktree
  block runs `gh pr merge` *before* the worktree is removed. On gh 2.102.0,
  `--delete-branch` then deletes the worktree silently, and a chained
  `git worktree remove` fails.

The goal: after the review gate passes, a close carries itself through to a
clean mainline. It stops and asks only when there is a real issue to look
into.

### Scope

**1. A `planners finish <NNN>` command for step 6.**

It is run from the main checkout once the closing plan commit is pushed. In
order, it:

1. Resolves the plan's branch and, from `git worktree list`, its worktree
   (if any).
2. Checks the worktree: no uncommitted changes, and nothing ahead of its
   upstream. If either is true, it stops and names what is left.
3. Runs `.planners/hooks/pre-worktree-remove` if it is executable, then
   `git worktree remove`.
4. Merges the plan's PR with `gh pr merge <N> --merge --delete-branch
   --subject "merge: PR #<N> - <branch>"`, truncating the subject with
   `...` past 60 characters. Right after a push, GitHub can report a PR as
   not mergeable while it recomputes. The command polls
   `mergeable`/`mergeStateStatus` for a bounded time before reading that as
   a real conflict. A PR that is already `MERGED` skips this step.
5. Confirms `state == MERGED`, then runs `git fetch --prune` and pulls the
   base.
6. Deletes the branch on the remote if it is still there. It deletes the
   local branch only when `git merge-base --is-ancestor <branch> <base>`
   passes. It never uses `-D` and never touches a mainline branch.
7. Regenerates the index. If the `post-merge` hook left the index changed,
   it commits it.
8. Finds any `INSTALL_PYTHON` in `.git/hooks/*` that points under
   `.worktrees/`, and re-installs those hooks from the main checkout.
9. Prints one report of what it did, step by step.

`--no-pr` swaps step 4 for the local `git merge --no-ff` of the no-PR path,
plus a push. A plan with `pr: null` takes that path without the flag.

**2. Stop only on real issues.** These stop the command with exit 1, a
message, and the state left as it was:

- a dirty worktree, or unpushed commits;
- a PR that is still a draft, has failing checks, or still has conflicts
  after polling;
- a failed ancestor test, meaning the branch holds commits the base lacks;
- a refused `gh` or `git` call, such as a permission denial or a failed auth.

Everything else, it handles. A step that is already done (no worktree, PR
already merged, branch already gone) is a no-op, not an error, so a re-run
after a stop picks up where the last one ended.

**3. Skill changes (`close`, `pipeline`).**

- Step 6 becomes: in the worktree, commit and push the closing plan edit.
  Then run `planners finish <NNN>` from the main checkout. This removes the
  ordering contradiction.
- Add a rule to both skills: the session runs every cleanup step itself. A
  step goes to the user only after a call to it was actually refused, quoting
  the refusal. A session never hands a step off on the *assumption* of a
  block.
- Reach the worktree with subshells (`(cd .worktrees/<name> && ...)`) or
  pathspecs, not a bare `cd` in the persistent shell. The session's working
  directory should stay on the main checkout.
- Update the generated rule's close summary to match. The rule also gets
  the habit itself, so it holds in every repo and every session, not only
  inside the skills: routine close-out steps are the session's to run.
  Before a session reports that it is blocked, it tries the command.

**4. Tests.**

Scratch repos with a bare remote and a fake `gh` on `PATH`, as
`tests/test_cli_implemented.py` already does. Cover:

- the happy path with a worktree;
- no worktree;
- an already-merged PR;
- a polled "not mergeable yet" that clears;
- each real-issue stop;
- an idempotent re-run after a stop;
- `--no-pr`;
- the hook re-point.

### Open questions

1. Command name: `finish`, `cleanup`, or a `close --finish` flag? Default:
   `finish`, a lifecycle verb that sits beside `implemented`.
2. Should `finish` run `gh pr merge` itself, or expect the PR to be merged
   already? Default: run it. The command is reached only after the review
   gate. `planners permissions --level full` already names `gh pr merge` as
   the explicit opt-in, so under a lower level the call is refused and
   reported, which is a real-issue stop.
3. Should `finish` also write the plan's `pr` and `concluded` when they are
   missing? Default: no. Those belong to the closing commit, which is made
   before the merge.

### Out of scope

- Changes to the harness's worktree isolation, or to the user's own rule
  files. This plan only stops a session from *assuming* an isolation it has
  not tested.
- The review gate itself.

### Order

1. `planners finish`, with its stops and tests.
2. The `--no-pr` path and its tests.
3. The `close` and `pipeline` skill text, the rule, and the CHANGELOG.

## Log

- **2026-10-09T16:44:36-07:00** — Implemented on `feature/harden-close-cleanup`
  ([#38](https://github.com/gitronald/planners/pull/38)).
  - Activated on `dev` at `7f9cf7b` with the installed `planners` 0.10.0, which
    predates plan 012's activation and `PR opened` Log entries, so neither was
    written; this entry starts the Log.
  - `ab98f95` added `planners finish` (`planners/finish.py` + the command in
    `cli.py`) with the merge inside it and check/mergeability polling, and
    `8081434` its tests.
  - **Decision: the merge moved out of `finish`** (`dc76bc7`). Open question 2's
    default assumed a lower automation level would refuse `gh pr merge`. It
    does not: a permission rule sees only the command a session runs, and the
    global `assist` profile grants `Bash(planners:*)`, so a merge made inside
    `finish` would skip the `full`-level gate. pkgskills writes only `allow`
    rules, so `finish` cannot be put behind an `ask`. Asked the user, who chose:
    the session runs `gh pr merge` itself (gated as before), and `finish` is the
    cleanup after it. The same reasoning keeps `finish` from pushing code. Its
    one remote write deletes a branch the remote's base already contains, and a
    stale-index commit is left for the session to push.
  - What that changed against the spec: `finish` no longer merges, polls, or
    passes `--delete-branch`. A PR that is not merged is a stop that prints the
    exact `gh pr merge` command; on the no-PR path, a branch that the base's
    upstream lacks is a stop that prints the `git merge --no-ff ... && git push`
    command. The draft, failing-check, and conflict stops went with the merge,
    since `gh pr merge` reports them itself. The worktree check runs before
    anything is removed, so a stop leaves it in place.
  - `6e4cb28` rewrote `close` step 6 and its no-PR step 6: commit and push in
    the worktree through a subshell, then merge and `planners finish` from the
    main checkout. It added *Who runs the cleanup* (the session runs every step,
    hands one off only after a quoted refusal, and keeps its shell on the main
    checkout). `pipeline` step 6 and the rule's close summary match, and the
    rule carries the habit for every repo.
  - `e900ae7`: README command list and CHANGELOG.
  - Checks: `ruff check`, `ruff format --check`, `pyrefly check`, and `pytest`
    (489 passed, coverage 93.86%), all run in the worktree.
  - Tests cover: the happy path with and without a worktree, a second run as a
    no-op, an open PR and a closed PR, a stale index, a dirty worktree followed
    by a resumed run, unpushed commits, a branch the base lacks, a plan not
    closed, running from inside the worktree, the no-PR path (both `pr: null`
    and `--no-pr`), the hook re-point, merge-subject truncation, and the fork
    label.
  - Found along the way: the git rule's example truncated subject
    (`...-hook-fro...`) is 61 characters, one past its own limit. Left alone
    (the user's rule files are out of scope).

## Handoff

- **State.** All work is committed and pushed on `feature/harden-close-cleanup`;
  PR #38 is a draft. Not yet marked `implemented`.
- **Open questions** (numbered as in the spec):
  1. Name: `finish`. Settled 2026-10-09 (the default).
  2. Should `finish` merge? Answered 2026-10-09 by the user: no. The session
     merges, and `finish` cleans up after (see the Log).
  3. Should `finish` write `pr`/`concluded`? No (the default). Settled 2026-10-09.
- **Not verified.** `finish` has not run against a real GitHub PR. The tests use
  a fake `gh` and a bare local remote. The installed rule and skill stubs are
  not reinstalled, so they still carry the old close text until
  `planners install --force` runs on a release that includes this.
- **Next.** Review, then close this plan with the new step 6. That close is
  the first real run of `finish`.
