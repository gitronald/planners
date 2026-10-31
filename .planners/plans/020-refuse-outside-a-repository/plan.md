---
id: 20
slug: refuse-outside-a-repository
status: done
branch: feature/refuse-outside-a-repository
created: 2026-10-31T15:20:15-07:00
concluded: 2026-10-31T15:35:12-07:00
pr: https://github.com/gitronald/planners/pull/60
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
- **2026-10-31T15:24:37-07:00** — PR opened: https://github.com/gitronald/planners/pull/60
- **2026-10-31T15:24:53-07:00** — Implemented decisions 1 to 7. All 661 tests pass at 94% coverage, with ruff and pyrefly clean.
  - Departures from the spec: step 2 did not touch tests one by one. An autouse fixture in `tests/conftest.py` makes each test's temp directory a real repository, so the real guard runs in all of them. `@pytest.mark.no_repo` opts out, and `tests/test_base.py` and `tests/test_proc.py` use it at module level because they build their own repositories.
  - A test that kept passing for the wrong reason: the add-commit-failure test described a directory with no repository, then passed with the fixture because git had no identity. It now sets `user.useConfigOnly` and says that is what fails, so it no longer depends on git inventing an identity.
  - `resolve_command` carries an inline pyrefly ignore, because `typing.override` needs Python 3.12 and the package supports 3.11.
  - A test lists every command as guarded, path-checked, or exempt. A new command is guarded by default, and this test makes its author say which it is.
  - Verified as real processes beyond the test runner: from a bare directory under a temporary directory whose parent holds a stray empty `.git`, each of `install --global`, `--check`, `--force`, `add`, and `index .` exits 1 and leaves the directory empty, and `skill` and `add --help` exit 0.
  - Checked the one other caller found that shells out to `planners`: it runs with its working directory set to a repository clone, so the guard does not affect it. That is from reading its code, not from running it.
  - Not verified: the guard against released `pkgskills` other than the version this repository locks.
- **2026-10-31T15:24:55-07:00** — Implemented: 4 commits ahead of `dev`.
- **2026-10-31T15:38:11-07:00** — Final log. Review ran at medium level through the code-review skill and is posted on the PR. CI passed on Python 3.11 to 3.14 at the head it reviewed, and all 666 tests pass with ruff and pyrefly clean.
  - Review follow-up: 5 findings survived verification, out of 13 raised, and all are fixed.
    - A `--help` used as an option value or after `--` skipped the guard, so `add foo --title --help --no-commit` wrote a plan outside a repository. The guard now runs when the subcommand is invoked, after its arguments are parsed, so a real help request has already exited and no token check is needed. This departs from decision 1, which placed the refusal in `resolve_command` itself. Regression test added.
    - Every git failure read as no repository, with advice to run `git init`. A missing git now gets its own message, a file named as the repository says so, and any other refusal quotes git, including the `safe.directory` advice for a repository it does not trust. Regression tests added, with the ownership case simulated through git's own test switch.
    - The `box` fixture's install tests passed only because their parent temp directory was a repository. They now use a real repository of their own.
    - The `_repo` helpers' flag is renamed `committed` in four test modules, since it no longer says whether a repository exists. The `tests/conftest.py` docstring is updated.
    - Conscious no-ops: a deleted working directory's traceback and `add` from a subdirectory writing under it, both unchanged from the base branch. The `finish` fallback to the current directory stays, as a guard against git failing between the two calls. The per-test `git init` costs about 2 seconds at most across the suite and cannot reuse `init_git`, whose identity would break the missing-identity test.
  - Decided at the review gate: `index` keeps the requirement. It used to run with no git on PATH and in a repository git refuses, and it now exits 1 and says why, since it regenerates a tracked file.
  - Not verified: the ownership case with a real second user. Not changed: `pkgskills check`, which skips this guard and can still report the line as `missing` outside a repository, without writing anything. No release is cut here, so installed copies do not have the guard yet.

## Retrospective

- The question started as how a library should treat lines outside a repository, and the
  fix moved here once a survey found this package was the only host affected. Running its
  own commands outside a repository then showed `add` and `index` misbehaving too, which no
  library change would have reached. Check who is affected before designing for hosts in
  general.
- Asking git rather than looking for `.git` was the decision that mattered most. It refuses
  the stray empty `.git` that a filesystem walk accepts, the likely route to the stray files
  this plan started from, though what created them was never established.
- Deciding help from the raw arguments was a shortcut that left a real bypass, and the first
  design missed it because `add --help` passed. Doing the check after parsing removed the
  token test and the shell-completion case together.
- Making every test's temp directory a repository kept 121 tests running against the real
  guard, but some kept passing for new reasons. One failure test passed only because git had
  no identity, and the install tests passed through their parent directory. When a fixture
  changes what a whole suite stands on, passing does not show that each test still means
  what it says.
