---
id: 3
slug: base-branch-guard
status: done
branch: feature/base-branch-guard
created: 2026-07-23T12:04:08-07:00
concluded: 2026-09-08T14:11:42-07:00
pr: https://github.com/gitronald/planners/pull/12
---

# Guard add/activate against running on a non-base branch

## Plan

The `plan [add]` and `plan [activate]` commits are supposed to land on the base
branch (e.g. `dev`) *before* the feature branch or worktree is created, so the
mainline records the plan regardless of whether the branch ever lands (implement
skill, step 3). Nothing enforces this: `planners add` commits on whatever branch
HEAD is on, and the base-first sequencing lives only in the skill instructions.

### Observed failure

In a consuming repo (`owner/repo`), an implementing session created the
worktree/branch first, then ran add + activate inside it. Both commits landed
only on the feature branch; the base never recorded the plan:

```
# on feature/<slug> (worktree)
800650a plan [update]: 002 - add pr url
e4eb3e5 plan [log]: 002 - template-upgrade
2afcd81 <implementation commits...>
d947aeb plan [activate]: 002 - template-upgrade
dde4e89 plan [add]: 002 - template-upgrade
e37b1d6 <base HEAD - dev still points here>
```

Impact was masked because the repo merges PRs with `--no-ff`, so the commits
reached the base at merge time — but an abandoned branch would have left no
mainline trace of the plan, and a squash-merge repo would lose the commit
subjects entirely.

### Sketch

- Detect the repo's base branch (`dev` if it exists, else the default branch;
  possibly configurable).
- `planners add` (and the activate path): when HEAD is not the base, warn — or
  refuse with a clear message — before committing; provide an explicit override
  flag for legitimate on-branch use.
- Consider a `planners validate` check: an `active` plan whose add/activate
  commits are unreachable from the base is flagged.
- Tighten the add/implement skill text to make the ordering failure loud
  (check `git branch --show-current` before scaffolding).

### Resolved design

The sketch left four choices open. Settled before implementation:

**Refuse, don't warn.** `add` and `finalize` exit non-zero when HEAD is on a
non-mainline branch, with `--allow-branch` as the explicit override. A warning
would reproduce the observed failure: the base-first ordering was already written
in the implement skill, and the session ignored it — another line on stderr is
just as ignorable. Refusing is the only thing that enforces.

**Accept a set of mainline branches, not one base.** The guard accepts HEAD on
`dev` (when that branch exists) *or* the repo's default branch, and refuses only
outside that set. Comparing against a single base would block a plan added on
`main` in a repo that also has `dev` — a commit that reaches the mainline
perfectly well. The failure this plan is about is feature branches and worktrees,
so that is what it should catch. Fewer false blocks also removes most of the
motive for a configuration knob.

**No configuration knob.** An earlier draft had a per-clone `git config
planners.base` override. Dropped: per-clone git state is invisible to a fresh
clone and reports nothing when absent — the same invisibility that plan 004
exists to remove. Adding a second instance of the pattern here while 004 works to
delete the first is the wrong trade. A repo whose mainline is neither `dev` nor
the default branch uses `--allow-branch`.

**No `validate` check.** `validate` is pure frontmatter parsing today — no
subprocess, deterministic, offline — and it runs as a pre-commit hook in every
consumer. A reachability check would make it git-dependent, need a current base
ref, and fire on every commit made legitimately inside a feature branch. The
guard belongs where the failure happens (`add`/`finalize`). Revisit separately.

**Add a `planners base` command.** One detection implementation shared by the
guard and the skill prose, instead of `implement.md` re-describing "usually `dev`"
in text that can drift from the code.

#### What detection can and cannot know

`planners base` reports what git's refs currently say the mainline branches are.
It is a heuristic over present state, not a record of where plans were actually
committed. Resolution order:

1. local branch `dev`, when it exists;
2. `refs/remotes/origin/HEAD` — the remote's default branch *as recorded at clone
   time*;
3. fallback to a local `main`, then `master`;
4. nothing resolves -> report unknown and leave the guard inert.

The known weakness is (2): `git fetch` does not refresh `origin/HEAD`, so it is
unset in clones made by some tooling and goes stale if the remote renames its
default branch afterwards. `git remote set-head origin --auto` re-derives it in
one network call; `base` should say so when detection looks thin.

Deriving the base empirically instead — asking which branch contains the existing
`plan [add]:` commits — would genuinely report what was used, and was rejected on
two counts: it is circular for this guard (which exists *because* those commits
landed on the wrong branch, so a repo that already failed would learn the wrong
answer from its own history), and it costs a history walk on every `add`.

The design absorbs the weakness rather than denying it: an accepted set rather
than one branch, `--allow-branch` as the escape hatch, and inert-when-unresolvable
so the guard never blocks a repo it cannot reason about.

## Log

**2026-09-08** — Implemented on `feature/base-branch-guard` (PR #12).

- `planners/base.py` (new): `detect()` resolves the mainline set from git's refs
  and `guard_message()` renders the refusal. Read-only and best-effort — every
  git failure collapses to "absent", so detection degrades to `UNRESOLVED` rather
  than turning a missing binary or an odd repo into a command failure.
- `add` and `finalize` call the guard **before writing anything**. A refused
  `add` leaves no half-scaffolded plan directory (the ordering the unsafe-slug
  check already relied on), and a refused `finalize` leaves the batch staged and
  recoverable rather than half-moved out of staging.
- Only the committing paths are guarded. `--no-commit` and `--defer` write no
  commit, so no branch can strand one; guarding them would refuse work that is
  not at risk.
- `planners base` prints the mainline (`--all` for the set), exits non-zero when
  nothing resolves, and appends the `git remote set-head origin --auto` remedy to
  stderr when detection fell back past `origin/HEAD`. stdout stays clean so a
  script can consume it.
- Prose updated at the source rather than restated: the convention rule gained a
  *Plan commits belong on the mainline* section, and `add.md`/`implement.md` now
  run `base --all` instead of asserting "usually `dev`". `implement.md` step 2
  also says outright not to create the branch first, and flags that the
  activation commit is hand-written `git commit` with no CLI guard behind it —
  that check is the only thing protecting it.

### Verification

19 tests in `tests/test_base.py`, all against real git repos — the module's whole
job is reporting what git's refs say, so a mocked `subprocess` would only assert
that the code calls the commands it calls. Full suite 312 passed; ruff and
pyrefly clean.

Reproduced the failure this plan was written about in a scratch repo: branch
created first, then `add` — now refused, with the plan committed to `dev` on the
correct ordering. Confirmed detection resolves the shared refs correctly from
inside a linked worktree, which is the position the original failure happened in.

### Notes

- The guard caught itself during development: running `planners add` from this
  plan's own worktree was refused, which is the exact scenario in *Observed
  failure* above.
- `git init` leaves an unborn HEAD, so the first `add` in a fresh repo has no
  mainline to be off of. That case is inert by construction, not a refusal — and
  it is what keeps the pre-existing `add` tests (which `git init` and immediately
  add) green without an `--allow-branch`.
- Tripped the repo's `test_no_abandoned_anywhere_in_package_source` convention
  while writing docstrings. The word is banned because `retired` deliberately
  carries no failure connotation; rephrased to "never merged".
- Deliberately out of scope, per the resolved design: no `validate` reachability
  check and no configuration knob. The activation commit remains unguarded by
  code — prose is the only lever, since `activate` has no CLI command.

### Review follow-up

`/code-review` at level `high` on PR #12: four finder passes, then adversarial
verification per file. 19 candidates, 16 confirmed, 1 rejected. Everything
actionable was fixed before merge.

**Two real defects, both in code this plan added.**

The guard *failed open* under an ambient `GIT_DIR`. `_git_out` passed `cwd=root`
but inherited the git-location environment variables, which outrank `cwd`.
Reproduced end to end: with `GIT_DIR` pointing elsewhere, `add` run in a repo
sitting on a feature branch reported `on_mainline=True`, passed, and committed
the plan **into the unrelated repo**, leaving the real one with orphaned untracked
files. `cwd=root` does not save you — `_is_repo` still succeeds, just against the
wrong repository. Fixed by stripping those variables for the duration of
detection.

A dangling `origin/HEAD` was trusted without checking the ref existed, so
detection reported a confident (`thin=False`) answer naming a branch that cannot
be checked out — a refusal whose advice fails with `pathspec did not match`. The
fallback path already required `_has_branch`; the `origin/HEAD` path did not.
Fixed by verifying the remote-tracking ref, falling back and reporting `thin`
when it is absent.

**A test-integrity finding worth more than either.** No test anywhere covered
`finalize` committing on a mainline branch. Both `finalize` commit-mode tests in
`test_cli.py` init a repo with no commit, so HEAD is unborn and the guard
short-circuits before `on_mainline` is ever consulted — proven by mutation:
patching `on_mainline` to return `False` unconditionally left them green.
`test_base.py` covered only the refusal path. The unborn-HEAD carve-out that keeps
fresh repos working is the same thing that made those tests vacuous.

**Docs contradictions the diff created.** The generated rule's own Skills summary
still read "check git status, create branch, activate, start coding" — branch
before activation, in the same file as the new section forbidding exactly that.
`update.md`'s activate action still assumed the session was already on a feature
branch. Both rewritten.

Also folded in: one shared `THIN_NOTE` (the two copies had already drifted),
`UNRESOLVED.thin` corrected to `False`, and a tautological containment check
removed. Rejected one finding — "abandoned" in this plan's *Observed failure* is
pre-existing text, and the convention test scans only `planners/` package source.

`base.py` coverage 96% -> 99%. Gate green: ruff, ruff format --check, pyrefly,
323 tests.

### Known gap, not fixed here

`cli._git` — the runner that makes the actual commit — has the same `GIT_DIR`
exposure and does not even pass `cwd`. So once the guard allows a commit,
`planners add` under an ambient `GIT_DIR` can still write it into another
repository. That is pre-existing on `dev` and outside this plan's scope. The
detection fix makes the *guard* accurate; it does not make the *commit*
location-safe. Worth its own plan.

## Retrospective

- The design survived review; the implementation did not. Every confirmed defect
  was in how the module talked to git, not in the accepted-set/inert-when-
  unresolvable policy settled up front. Deciding the policy before writing code
  was worth it — and did nothing to protect the plumbing underneath it.
- A guard has an asymmetric failure mode that ordinary code does not, and I did
  not design for it. Failing *closed* is a nuisance; failing *open* is silent and
  leaves the user believing they are protected. `cwd=root` reads as obviously
  sufficient and is not. Anything that shells out to git for a security or
  correctness decision should pin the environment, not just the directory.
- The carve-out that makes a feature usable can be the thing that makes its tests
  vacuous. Unborn-HEAD inertness is correct behavior *and* the reason three
  pre-existing tests never reached the guard. Worth asking, of any new
  short-circuit: which existing tests now stop early because of it?
- Mutation was the only technique that produced this. Coverage reported those
  tests as exercising the code; they did. Breaking `on_mainline` on purpose and
  watching them stay green is what showed they asserted nothing about it.
- Prose fixes at the source still missed a spot. I updated `implement.md` and the
  rule's body but not the rule's own one-line Skills summary, leaving a generated
  always-on file contradicting itself. When a doc restates itself at two
  altitudes, both are the source.
- Dogfooding caught a real thing early: the guard refused my own `add` from
  inside this plan's worktree. Cheap signal, worth reaching for sooner.
