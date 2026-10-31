---
id: 20
slug: refuse-outside-a-repository
status: active
branch: feature/refuse-outside-a-repository
created: 2026-10-31T15:20:15-07:00
concluded:
pr:
---

# Refuse to run outside a git repository

## Plan

### Problem

Plans live in a repository, and most of what `planners` does ends in a git commit. Run
from a directory with no repository, its commands either leave files behind or fail in a
way that does not say why. Measured from a directory under a sandboxed `$HOME`:

| Command | Result |
|---|---|
| `add probe-plan` | Writes the plan and the index, then exits 1 when `git add` fails |
| `index .` | Creates `.planners/README.md` and exits 0 |
| `base --all` | Exits 1, suggesting `git remote set-head` or `--allow-branch` |
| `install --global` | Writes `.gitattributes` and `.pre-commit-config.yaml` there |
| `install --check`, after a global install done elsewhere | Exits 1 on the `.gitattributes` line |
| `install --force`, the repair that check prints | Writes the same two files, and the next check passes |

The last two compound. The skill stub tells a session to run `install --force` on any
check result other than `ok`, so a session in such a directory is told to fix a healthy
install, and doing so leaves two files git never reads there. The same pair was found in
a shared temporary directory on a development machine.

`pkgskills` writes the line and calls `after_install`, but the problem is narrower than
the library: `planners` is its only host declaring a `Line` or wiring pre-commit hooks,
and a library change would not reach `add` or `index`. So the fix goes here.

### Decisions

1. **One guard, in front of every command.** A `TyperGroup` subclass overrides
   `resolve_command` and refuses before the command runs. A group callback cannot do
   this: it runs before the subcommand's arguments are parsed and cannot see them, so
   `add --help` would be refused too. A command added later is guarded unless it is
   listed as exempt. `install` is mounted by `pkgskills`, so a check inside each command
   would not cover it.
2. **Ask git, not the filesystem.** The guard runs `git rev-parse --show-toplevel` through
   `planners.proc`, so an ambient `GIT_DIR` cannot answer for it. A stray empty `.git`
   passes a filesystem walk, but `git add` fails there, and the commands need a repository
   git accepts. A linked worktree passes. A bare repository does not.
3. **`--help` always works,** at the top level and on any command.
4. **What is exempt:** `skill`, `rule`, and `schema` only print. `validate` only reads, and
   it names its targets as paths. `permissions` manages Claude Code settings and has a
   `--global` form.
5. **`index`, `base`, and `remote` check the path they are given,** not the current
   directory, so `index some/repo` keeps working from elsewhere.
6. **`install` is refused in every form,** including `--global` and `--check`. The library
   writes the line under the root on any install, so nothing narrower stops the stray
   files. The cost is that a first `planners install` has to run inside a repository, and
   a directory with only `.claude/` needs `git init` first.
7. **The refusal says what to do and that there is nothing to repair:** it names the
   directory, says nothing was changed, and points at a repository or `git init`. A session
   following the stub's advice to run `install --force` needs to read this as a stop.

### Implementation order

1. The guard and its exemptions in `planners/cli.py`, with tests from a directory with no
   repository: each guarded command refuses and writes nothing, `--help` and the exempt
   commands still run, and a stray empty `.git` does not count. In a repository, from a
   subdirectory, and from a linked worktree, commands run.
2. Give the existing tests that run outside a repository a real one. The sandbox fixture's
   `.git` is an empty directory, which decision 2 refuses.
3. README, the bundled rule and skill text where they describe running outside a
   repository, and the changelog.

### Out of scope

- `pkgskills check`, which calls the library directly and skips this guard. It can still
  report the line as `missing` outside a repository, but it writes nothing.
- `permissions --apply` without `--global` writing a settings file in the current directory.
- Changing `pkgskills`. Its plan for this question closes in favor of this one.

## Log

- **2026-10-31T15:20:36-07:00** — Activated.
  - Branch: `feature/refuse-outside-a-repository`
  - Base: `dev` at `a86eb2e`
  - Worktree: `.worktrees/020-refuse-outside-a-repository`
  - PR: pending
