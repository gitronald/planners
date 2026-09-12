---
id: 7
slug: adopt-pkgskills
status: draft
branch:
created: 2026-09-11T17:50:47-07:00
concluded:
pr:
---

# Adopt pkgskills for prompt packaging and install

## Plan

`pkgskills` generalizes the prompt-packaging and install machinery this package
grew: shipping prompts as package data, printing them on demand through a `skill`
command, and materializing version-stamped stubs where the harness reads them.
That machinery was extracted from here, and the two have not diverged —
`planners/proc.py` and `pkgskills/proc.py` are code-identical, differing only in
docstrings. Adopting it deletes roughly a third of this package's source — the skill,
rule, and permissions modules, the generic half of `install.py`, and the four
CLI commands that front them — and leaves the plan-lifecycle logic untouched.

### Dependency

Depend on the **published distribution** — `pkgskills>=0.3.0` from PyPI, resolved
normally. Not a path dependency, not an editable install against a local
checkout, not a git URL. `0.3.0` is the floor because it closes the three gaps a
review of this plan found in `0.2.0` (upstream plan 007): a same-dist
pre-adoption stamp now gets an honest `foreign` reason, `InstallReport` carries
`force`, and a bare `skill` on a dispatcher host lists its bodies. The upstream
dev cycle is at `0.3.1a0` with nothing behind it but the prerelease bump. Runtime cost is one transitive dependency
(`typer`), which this package already requires, and `requires-python` matches.

### What moves

| Today | After |
|---|---|
| `planners/skill.py`, `planners/rule.py` | `Skill(...)` / `Rule(...)` on a `Host` |
| `planners/permissions.py` | `Host.permissions` — the ladder's rule *data* stays as declaration, the merge/render/settings-path code goes |
| `planners/proc.py` | **stays** — see the decision below; `pkgskills.proc` is code-identical but is not imported |
| `planners/install.py` — stamping, mode resolution, holder rendering, artifact path/write/check, drift + foreign detection, stale removal | `pkgskills.artifacts` |
| `planners/cli.py` — the `skill`, `rule`, `install`, and `permissions` commands | `register(app, HOST)` |

The prompt files themselves do not move. `pkgskills` reads only the last two
components of a source path and supports a flat `skills/<name>.md`, which is
already this package's layout, so `planners/prompts/` stays exactly as it is.

### What stays

Everything about plans, plus the repo-wiring half of `install.py`:

- pre-commit config wiring, hook registration, and `core.hooksPath` detection
- the `.gitattributes merge=union` line for the generated index
- the `post-merge` index-regeneration hook
- supersession of the legacy hand-maintained convention file

These are per-clone state `pkgskills` cannot see, and they keep working through
the two hooks the library provides for exactly this: `Host.after_install` for the
write side, and `Host.extra_checks` for the `install --check` table, so the
shared table keeps reporting hook status rather than this package re-implementing
its own `install` command around it.

`base.py`, `index.py`, `metadata.py`, and the `add` / `finalize` / `activate` /
`index` / `validate` / `schema` / `base` commands are untouched.

### Install flags that do not survive

`pkgskills`' `install` takes `--local/--global`, `--check`, and `--force`, and
`after_install` receives an `InstallReport` (host, mode, root, written, removed,
shadowed, force). Three of today's flags have no way through:

- `--full` (`uv add --dev pre-commit`, then register the hook)
- `--no-activate` (write the hook config, skip `pre-commit install`)
- `--no-rule` (skip writing or checking the convention rule)

**Drop all three.** None is referenced by the shipped prompts, the README, or the
docs — only `test_install.py` and `test_cli.py` cover them, and those tests go
with the flags. The hook is registered on every install (today's default) and
the rule is always written. A host-declared install option is an upstream
design question, deferred there until a second host needs it; do not add a
planners-local wrapper command to keep the flags alive.

`--force` keeps its second job. Today it also authorizes rewriting a differing
`.gitattributes` line; `InstallReport.force` (added in `0.3.0` for exactly
this) carries the user's consent into `after_install`, so `wire_gitattributes`
reads it from the report rather than from a CLI flag.

Two smaller behavior changes ride along:

- A bare `install` over a foreign target **refuses** with a pointer to
  `--force`; today's interactive overwrite prompt (`_confirm_force_overwrite`)
  goes away with it. That is the library's posture and it is the right one for
  a command prompts invoke.
- Bare `planners skill` still lists the seven bodies (`0.3.0` made that the
  dispatcher-host default), so nothing that relies on it changes.

### Decision: keep `planners/proc.py`

**Keep the local module. Do not import `pkgskills.proc`.** It is the one row in
the table above that does *not* move.

All seven `proc.run` call sites remain planners code after the refactor — four in
the pre-commit/hook wiring that stays behind `after_install`, and three in
lifecycle git (`cli.py` ×2, `base.py` ×1). No caller migrates upstream, so
nothing about this adoption forces the question; the only question is whether to
delete 76 zero-dependency lines in order to import an identical implementation
from a dependency. Three reasons not to:

- **Upstream has no internal consumer.** `pkgskills` runs no subprocesses of its
  own and says so in the module docstring; the only references are the
  re-export in `__init__.py` and its own `test_proc.py`. A module nothing in its
  home package calls is the most likely to be refactored or drift, because
  nothing there breaks when it does.
- **It is the commit-safety guard** (see plan 006). A future release trimming
  `LOCATION_ENV` or changing `pinned_env` would mean planners writing commits
  into the wrong repository, silently — the exact failure the module prevents.
  On a `>=0.2.0` range against a 0.x package, any minor bump can move it.
- **No cohesion.** "Which repository does this git command act on" is not a
  prompt-packaging concern; sharing the code would not make the concept shared.

The duplication is the accepted cost, and it is small: the two copies are
independent guards over independent subprocess calls and have no requirement to
agree, so divergence is not a defect. The guard's behavior must not change here
either way.

### Implementation order

1. Add the dependency; declare `HOST` (dist, cli, prompts package, the one
   dispatcher `Skill` over the seven lifecycle sources, the `Rule`, and the
   `permissions` ladder). Register it under the `pkgskills.hosts` entry-point
   group so `pkgskills hosts` discovers it.
2. Mount `register(app, HOST)` and delete the four superseded CLI commands.
3. Move pre-commit and `.gitattributes` wiring behind `after_install` /
   `extra_checks`, with the gitattributes rewrite gated on
   `InstallReport.force`; delete the generic half of `install.py` and the three
   dropped flags.
4. Delete `skill.py`, `rule.py`, `permissions.py`, and resolve the `proc.py`
   decision.
5. Prune the superseded tests; keep and re-point the ones covering what stays.
   Add `assert_spec_conformant(HOST)` and `assert_prompt_commands(HOST, app)`
   from `pkgskills.testing`, which check statically what was previously only
   caught by hand.
6. Reinstall and verify: `install --check` reports `ok` across holder, rule,
   gitattr, and hook, and the emitted stub and rule are byte-comparable to
   today's apart from the stamp.

### Compatibility

The stamp changes format: it gains `via pkgskills X`. The stub's frontmatter
does not change — today's holder declares no `metadata`, and a `0.3.0`
dispatcher stub declares none either (`0.2.0` would have added
`metadata.pkgskills-version`; `0.3.0` removed it). So the emitted files really
are byte-comparable apart from the stamp line.

Every already-installed holder and rule is nonetheless **classified `foreign`,
not `drifted`**: the old stamp lacks the `via pkgskills` token, so `pkgskills`
cannot verify it wrote the file, and reports `a planners stamp pkgskills did
not write; hand-edited, or from a release before planners adopted pkgskills`.
A bare `install` refuses on that; `install --force` replaces it. That is a
one-time, visible, self-healing event — but it lands on every consuming repo,
and the word is `foreign` rather than `drifted`, so the changelog note must say
exactly that and name `--force` as the remedy. The three dropped install flags
and the removed overwrite prompt go in the same note.

### Out of scope

Any change to plan-file semantics, frontmatter, the index format, or the
lifecycle commands. This is an infrastructure swap; a consumer's `.planners/`
directory and every plan in it must be unaffected.

## Log

- Reviewed against the `0.2.0` API and the `planners` source before
  activation. The review found two upstream gaps (a nonsensical `foreign`
  reason for a pre-adoption stamp, and no way for `after_install` to see
  `--force`) plus a bare-`skill` UX difference; all three shipped upstream as
  `pkgskills` `0.3.0` (upstream plan 007). Revised this plan to require
  `>=0.3.0`, to drop `--full` / `--no-activate` / `--no-rule` explicitly, to
  correct the compatibility story (`foreign`, no metadata change), to keep
  `proc.py` out of the moves table, and to add the entry-point registration.
