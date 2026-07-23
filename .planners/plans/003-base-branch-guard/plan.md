---
id: 3
slug: base-branch-guard
status: draft
branch:
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
