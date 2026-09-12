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
docstrings. Adopting it deletes close to half of this package's source — the
skill, rule, and permissions modules, nearly all of `install.py`, and the four
CLI commands that front them — and leaves the plan-lifecycle logic untouched.

### Dependency

Depend on the **published distribution** — `pkgskills>=0.4.0` from PyPI, resolved
normally. Not a path dependency, not an editable install against a local
checkout, not a git URL. Two upstream releases came out of reviewing this plan,
and `0.4.0` is the floor because both are needed:

- `0.3.0` (upstream plan 007) closed three adoption gaps: a same-dist
  pre-adoption stamp gets an honest `foreign` reason, `InstallReport` carries
  `force`, and a bare `skill` on a dispatcher host lists its bodies.
- `0.4.0` (upstream plan 008) moved the repo-wiring machinery up:
  `pkgskills.precommit` (`Hook`, `wire`, `checks`, `add_dependency`), `Line`
  on `Host.lines` for one owned line in a file the host does not own, and
  `previous_names` on `Rule` / `Skill` / `Agent`.

The upstream dev cycle is at `0.4.1a0`, carrying the prerelease bump and a
`Line` hardening commit (normalized line text, `..` paths rejected). Runtime cost is one transitive dependency
(`typer`), which this package already requires, and `requires-python` matches.

### What moves

| Today | After |
|---|---|
| `planners/skill.py`, `planners/rule.py` | `Skill(...)` / `Rule(...)` on a `Host` |
| `planners/permissions.py` | `Host.permissions` — the ladder's rule *data* stays as declaration, the merge/render/settings-path code goes |
| `planners/proc.py` | **stays** — see the decision below; `pkgskills.proc` is code-identical but is not imported |
| `planners/install.py` — stamping, mode resolution, holder rendering, artifact path/write/check, drift + foreign detection, stale removal | `pkgskills.artifacts` |
| `planners/install.py` — pre-commit config wiring, `pre-commit install`, `core.hooksPath` detection, hook status rows, `uv add --dev pre-commit` | `pkgskills.precommit`: two `Hook` declarations, `wire(report, HOOKS)` in `after_install`, `checks(...)` in `extra_checks`, `add_dependency` |
| `planners/install.py` — the `.gitattributes merge=union` line and its four-status check | `Line(".gitattributes", "<index path>", "merge=union")` on `Host.lines` |
| `planners/install.py` — `superseded_legacy_rule` | `previous_names=("plan-files",)` on the `Rule` |
| `planners/cli.py` — the `skill`, `rule`, `install`, and `permissions` commands | `register(app, HOST)` |

The prompt files themselves do not move. `pkgskills` reads only the last two
components of a source path and supports a flat `skills/<name>.md`, which is
already this package's layout, so `planners/prompts/` stays exactly as it is.

### What stays

Everything about plans, plus the *declarations* of the repo wiring, which is
per-clone state the library cannot know about but can now act on:

- two `Hook`s — `planners-validate` at `pre-commit` and `planners-index` at
  `post-merge` — passed to `precommit.wire` from `after_install` and to
  `precommit.checks` from `extra_checks`, so the shared `install --check`
  table keeps reporting hook status as non-gating rows
- one `Line` for the generated index's `merge=union` attribute
- the legacy convention-file name, as the rule's `previous_names`

That is a few dozen lines in the `HOST` declaration and one small hook
function. `install.py` itself goes away.

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

`--force` keeps its second job with no host code. Today it also authorizes
rewriting a differing `.gitattributes` line; a `Line` is rewritten when drifted
only under `--force`, which is the same contract, enforced by the library.
`--full`'s dependency step survives as `precommit.add_dependency`, which the
library keeps opt-in and separate from `wire`; with no flag to trigger it, the
README tells a consumer to run `uv add --dev pre-commit` once instead.

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

Four of the seven `proc.run` call sites — the pre-commit/hook wiring — leave
with `install.py`; `pkgskills.precommit` runs those through its own
`pkgskills.proc.run`. Three remain in lifecycle git (`cli.py` ×2, `base.py` ×1),
and those are the question: whether to delete 76 zero-dependency lines in order
to import an identical implementation from a dependency. Two reasons not to:

- **It is the commit-safety guard** (see plan 006). A future release trimming
  `LOCATION_ENV` or changing `pinned_env` would mean planners writing commits
  into the wrong repository, silently — the exact failure the module prevents.
  On a `>=0.4.0` range against a 0.x package, any minor bump can move it.
  (An earlier draft added that upstream had no internal consumer of its copy;
  `0.4.0` gave it one in `precommit`, so that argument is gone — but a consumer
  wiring hooks exercises the guard differently from one committing plans, and
  does not protect the commit path.)
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
3. Declare the two `Hook`s, the `Line`, and the rule's `previous_names`; set
   `after_install` to call `precommit.wire` and `extra_checks` to return
   `precommit.checks`; delete `install.py` and the three dropped flags.
4. Delete `skill.py`, `rule.py`, `permissions.py`, and resolve the `proc.py`
   decision.
5. Prune the superseded tests; keep and re-point the ones covering what stays.
   Add `assert_spec_conformant(HOST)` and `assert_prompt_commands(HOST, app)`
   from `pkgskills.testing`, which check statically what was previously only
   caught by hand.
6. Reinstall and verify: `install --check` reports `ok` for the holder, the
   rule, and the `.gitattributes` line, `active` for both hooks, and the
   emitted stub and rule are byte-comparable to today's apart from the stamp.

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

The existing `.pre-commit-config.yaml` entries and `.gitattributes` line need
nothing: `precommit.wire` judges presence by the `- id:` line and resyncs an
entry only on a genuine mode switch, and a `Line` whose key already carries the
value reports `ok`. A consumer that customized its hook entry keeps it.

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
- `pkgskills` `0.4.0` shipped upstream plan 008 (`precommit`, `Line`,
  `previous_names`). Revised this plan to require `>=0.4.0`, to move the hook
  wiring, the gitattributes line, and the legacy-rule supersession into the
  moves table, to shrink "what stays" to declarations, to delete `install.py`
  outright, and to drop the "no upstream consumer" argument from the `proc.py`
  decision now that `precommit` consumes the upstream copy.
