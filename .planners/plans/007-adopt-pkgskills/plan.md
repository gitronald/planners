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
docstrings. Adopting it deletes roughly half this package's source, all of it the
generic half, and leaves the plan-lifecycle logic untouched.

### Dependency

Depend on the **published distribution** — `pkgskills>=0.2.0` from PyPI, resolved
normally. Not a path dependency, not an editable install against a local
checkout, not a git URL. `0.2.0` is the only release and carries the full feature
set; the upstream dev cycle is at `0.2.1a0` with nothing behind it but a
prerelease bump and a back-merge. Runtime cost is one transitive dependency
(`typer`), which this package already requires, and `requires-python` matches.

### What moves

| Today | After |
|---|---|
| `planners/skill.py`, `planners/rule.py` | `Skill(...)` / `Rule(...)` on a `Host` |
| `planners/permissions.py` | `Host.permissions` — the ladder's rule *data* stays as declaration, the merge/render/settings-path code goes |
| `planners/proc.py` | `pkgskills.proc` (exported; code-identical today) |
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
   `permissions` ladder).
2. Mount `register(app, HOST)` and delete the four superseded CLI commands.
3. Move pre-commit and `.gitattributes` wiring behind `after_install` /
   `extra_checks`; delete the generic half of `install.py`.
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

The stamp changes format (it gains `via pkgskills X` and the stub gains
`metadata.pkgskills-version`), so **every already-installed holder and rule
reports drift once** and needs `install --force`. That is a one-time, visible,
self-healing event the drift check is built to surface — but it lands on every
consuming repo, so it belongs in the changelog as a note, not buried.

### Out of scope

Any change to plan-file semantics, frontmatter, the index format, or the
lifecycle commands. This is an infrastructure swap; a consumer's `.planners/`
directory and every plan in it must be unaffected.
