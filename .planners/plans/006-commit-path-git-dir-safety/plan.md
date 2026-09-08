---
id: 6
slug: commit-path-git-dir-safety
status: active
branch: feature/commit-path-git-dir-safety
created: 2026-09-08T15:37:36-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/13
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

## Log

### 2026-09-08 — implemented on `feature/commit-path-git-dir-safety` (PR #13)

All five steps landed in one commit; the shared helper made them a single change
rather than five parallel edits.

**Step 1 — new module `planners/proc.py`.** `utils.py` was not a candidate: its
docstring promises "nothing here touches the filesystem, git, or the clock", and
this is the git-invocation primitive. So a third module both `base` and `cli`
import, exposing `LOCATION_ENV`, `pinned_env()`, and
`run(root, argv, *, capture_output=False)`. `run` deliberately keeps neither
`check=True` nor `shell=True`: every caller already has its own idiom for a
non-zero exit (absence for detection, a typer error for the commit path, `False`
for the best-effort hook helpers), and for the `rev-parse --verify -q` forms a
non-zero exit just means "no such ref".

`LOCATION_ENV` is the same five variables 003 stripped. `GIT_CONFIG_GLOBAL`,
`GIT_CONFIG_SYSTEM`, and `GIT_CEILING_DIRECTORIES` are pointedly *not* in it —
they change what git reads, not which repository it acts on, and the suite's
`_isolate_git_env` fixture depends on them surviving. Stripping them would have
silently un-insulated every test, so `test_proc.py` asserts they pass through.

**Steps 2-3 — `cli._git(root, args)` and `_git_status_porcelain`.** `_git` gained
the `root` parameter the plan predicted; all four call sites (two in `add`, two in
`finalize`) already had `root` in scope. Both runners now go through `proc.run`.
One behavioral consequence worth naming: `_git` no longer passes `check=True`, so
it inspects `returncode` instead of catching `CalledProcessError`. Same message,
same exit code.

**Step 4 — the regression test.** `tests/test_base.py`, in the *environment
independence* section next to 003's detection-side test:
`test_add_commits_into_the_repo_it_ran_in_despite_an_ambient_git_dir`. HEAD is on
`dev` in both repos so the guard legitimately clears the run — the point is that
the commit is redirected *after* the guard passes.

A trap found while writing it: the assertions themselves were being redirected.
`git log` with `cwd=repo` under an exported `GIT_DIR` reports the *other* repo's
history, so a naive check can pass for the wrong reason (003's existing test reads
`other`'s log with `GIT_DIR` still pointing at `other`, which happens to be
correct). Added a `_unredirected()` helper that drops `GIT_DIR` from its own
environment rather than reusing `proc.run` — an assertion must not depend on the
code under test — and routed both tests through it.

Verified the test bites by temporarily sabotaging `pinned_env()` to return
`dict(os.environ)`: `add` reported `[dev f127011] plan [add]: 000 - my-plan` while
`repo`'s log still held only `init`. That is the reported bug reproduced inside
the suite.

**Step 5 — `install.py` done in the same pass.** All four shell-outs
(`_effective_hooks_dir`, `core_hookspath_set`, `_run_precommit_install`,
`ensure_precommit_dependency`) now use `proc.run`. Two are advisory as the plan
said, but `_run_precommit_install` is not purely advisory on reflection:
`pre-commit install` *writes* into git's hooks directory, so it inherits the same
hazard one level down and would install the hook into the wrong repo. The `uv`
commands go through the same helper for that reason.

Five tests in `test_install.py` patched `install_mod.subprocess.run`; they now
patch `install_mod.proc.run`. Same reach — `install_mod.subprocess` *was* the
stdlib module, so those patches were already global for the test's duration.

**Result.** 329 tests pass (6 new), `ruff format`, `ruff check`, and
`pyrefly check` clean, `planners validate` clean. `subprocess` is now imported in
exactly one place in the package.

### Resolved: the open decision

Answered as the plan leaned — **an ambient `GIT_DIR` is never honored**, and the
reasoning is now stated in `proc.py`'s module docstring rather than left implicit:
plan files are written relative to the working directory, so honoring `GIT_DIR`
puts the files in one repo and the commit in another. That is not a capability
being removed; it is the bug. The target repository is named by `root` and only by
`root`.

### Incidental finding, not fixed here

This checkout has **no git hooks installed at all** (`.git/hooks/` holds only
`.sample` files), so the `planners validate` pre-commit gate the rule describes is
not firing for any commit in this repo. Every check above was run by hand. Out of
scope for this plan — flagged for a follow-up, since a gate nobody notices is
absent is the same failure mode this plan is about.
