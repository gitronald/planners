---
id: 3
slug: base-branch-guard
status: active
branch: feature/base-branch-guard
created: 2026-07-23T12:04:08-07:00
concluded:
pr:
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
