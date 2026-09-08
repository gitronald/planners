---
id: 6
slug: commit-path-git-dir-safety
status: draft
branch:
created: 2026-09-08T15:37:36-07:00
concluded:
pr:
---

# Make the commit path independent of ambient git location vars

## Plan

`planners add` can commit a plan into a **different repository** than the one it
was run in. Found by the review gate on plan 003 (PR #12) and reproduced end to
end: with `GIT_DIR` exported, `add` run in repo B wrote its `plan [add]` commit
into repo A's history and left repo B with orphaned, untracked `.planners` files.

Plan 003 fixed only half of this. `planners/base.py::_git_out` now strips the git
location variables, so *detection* describes the directory it was pointed at —
the guard no longer clears a branch it never inspected. But `cli._git`, the
runner that makes the actual commit, still inherits them, and unlike `_git_out`
it does not even pass `cwd`: it relies on the process's working directory.

So the guard is now accurate and the commit is still not location-safe. A repo
that passes the guard legitimately — HEAD genuinely on the mainline — will still
have its commit redirected if `GIT_DIR` is set.

### Why this is reachable, not theoretical

Git exports `GIT_DIR` to every hook it runs. Anything invoking `planners` from a
hook, a wrapper script, or a shell where a previous command left the variable set
inherits it. Nothing warns; the commit simply lands somewhere else, and the files
the user was looking at stay uncommitted.

### Scope

`planners/cli.py` has two git runners, and neither is location-pinned:

| Runner | Passes `cwd`? | Strips location env? | Used by |
|---|---|---|---|
| `_git` | no | no | the `add` and `finalize` commit paths |
| `_git_status_porcelain` | yes | no | `finalize`'s self-check |

`install.py` has the same pattern in its hook-detection helpers
(`_effective_hooks_dir` and neighbours). Those are advisory — a wrong answer
produces a misleading message, not a misplaced commit — so they are lower
priority, but they should end up consistent.

### Steps

1. **Promote the env-stripping into one shared helper.** `base.py::_git_out`
   already builds the sanitized environment; a third copy of the logic would be
   the thing plan 003's review flagged about the drifted remedy note. Decide where
   it lives — a small internal module both `cli` and `base` import is probably
   cleaner than either importing the other.
2. **Pin `_git` to an explicit repo root**, passing `cwd` rather than inheriting
   the process directory, and strip the location variables. Check every call site:
   `_git` currently takes only `args`, so adding a root changes its signature.
3. **Do the same for `_git_status_porcelain`**, which already has `cwd` and needs
   only the environment.
4. **Regression test the real failure**: `add` run under an ambient `GIT_DIR`
   must commit into the repo it was run in, and must leave the unrelated repo
   untouched. Plan 003 added the detection-side version of this test in
   `tests/test_base.py`; this is its commit-side counterpart.
5. **Decide about `install.py`.** Same fix, advisory impact. Probably worth doing
   for consistency in the same pass, but it is separable.

### Open decision: is an ambient `GIT_DIR` ever legitimate here?

Stripping it unconditionally means someone deliberately running
`GIT_DIR=... planners add` to target another repo loses that ability. That seems
right — the plan files are written relative to `Path.cwd()`, so honoring `GIT_DIR`
was never coherent: the files land in one repo and the commit in another, which is
precisely the observed bug. Worth stating explicitly rather than assuming.

### Notes

- Split out of plan 003 rather than folded into PR #12: 003's scope was the
  branch guard, and this touches every git call the CLI makes. Recorded in that
  plan's Log under *Known gap, not fixed here*.
- The bug predates 003 — `_git` has always inherited the environment. 003 made it
  visible by adding a guard whose correctness depends on which repo git answers
  about.
