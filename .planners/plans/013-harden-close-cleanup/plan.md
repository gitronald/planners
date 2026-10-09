---
id: 13
slug: harden-close-cleanup
status: draft
branch:
created: 2026-10-09T15:26:29-07:00
concluded:
pr:
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
- Update the generated rule's close summary to match.

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
