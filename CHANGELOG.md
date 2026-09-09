# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `dependabot.yml` now sets `target-branch: dev` for both ecosystems, so
  dependency-update PRs open against the active branch instead of `main`. They
  previously targeted the default branch, so each batch had to be retargeted by
  hand before it could merge into `dev`, and Dependabot resolved manifests
  against `main` rather than the tree the updates would merge into. Because
  Dependabot reads its config from the default branch, this takes effect once
  the change reaches `main`.

### Added

- `install` now gives the generated plan index its merge semantics: a
  `.planners/README.md merge=union` line in the repo's `.gitattributes`. A local
  merge whose two sides both added or closed plans used to conflict on the index
  and leave every repo to invent its own fix. `union` is a built-in git driver,
  so the one committed line is the whole fix — nothing to configure per clone,
  and it works in a fresh clone that has never run `install`. Other attribute
  lines are preserved; a line that names the index but says something else (such
  as a hand-rolled `merge=ours` stopgap) is reported rather than clobbered, and
  `install --force` rewrites it. Note that GitHub's server-side merge does not
  apply the attribute, so a PR can still report a conflict on the index; merging
  the base in locally now resolves it without hand-editing a generated file.
- `install --check` reports the attribute as a `gitattr:` line and gates on it,
  alongside `holder:` and `rule:`. It also prints a `hook:` line saying whether
  the `planners-validate` git hook is actually registered **in this clone** —
  per-clone state a fresh clone silently lacks, so a hook that never fires used
  to be indistinguishable from one that fires and finds nothing wrong. That line
  is reported, never gated: a consumer without `pre-commit` is correctly
  installed, just unguarded.
- `validate` now fails when the tracked index disagrees with the plan
  frontmatter it is generated from, naming `planners index .` as the fix. It
  works when handed individual plan files, which is how the pre-commit hook
  calls it. This is also the repair signal for the one thing `union` gets wrong:
  when both branches rewrote the *same* row, it keeps both, listing a plan
  twice. A repo with no index yet is not failed for its absence, and a legacy
  `docs/plans/` layout is left alone.

## [0.5.2] - 2026-09-08

### Added

- `activate` command — `planners activate 005` flips a plan to `active`, fills
  `branch:` (`feature/<slug>` by default, `--branch` to choose), refreshes the
  index, and commits `plan [activate]: 005 - <slug>`. Activation was the last
  lifecycle mutation still done by hand-editing frontmatter, which is why the
  mainline guard shipped in 0.5.0 could not cover it; it now carries the same
  guard and the same `--allow-branch` escape hatch as `add`. Closed plans
  (`done`/`retired`) are refused; a parked `inactive` plan may be reactivated.
  Takes a subplan reference (`005a`) as well as a plan number, and re-running it
  is a no-op unless an earlier run wrote the plan but failed to commit.

## [0.5.1] - 2026-09-08

### Fixed

- The publish workflow rejected the release wheel and never uploaded `0.5.0` to
  PyPI. `hatchling` is unpinned and now emits `Metadata-Version: 2.5`, which the
  twine bundled in `pypa/gh-action-pypi-publish` v1.14.0 (twine 6.1.0, packaging
  25.0) refuses. The action is pinned to v1.14.2 (twine 7.0.0, packaging 26.2),
  which accepts it. The break was latent since the backend started emitting 2.5 —
  it would have hit whichever tag came next, not something 0.5.0 introduced.

## [0.5.0] - 2026-09-08

### Added

- `base` command printing the repo's mainline branch — the branches a plan commit
  belongs on. `--all` lists every one in resolution order; it exits non-zero when
  no mainline resolves, so a script can branch on it.
- `add` and `finalize` now refuse to commit when `HEAD` is off the mainline,
  so a plan is recorded there even if the feature branch never merges. The
  accepted set is `dev` (when that branch exists) plus the repo's default branch.
  `--allow-branch` overrides the refusal for a repo whose mainline is not
  detectable by name.

### Changed

- The convention rule and the `add`/`implement` skills now state that plan
  commits land on the mainline before the branch or worktree is created, and
  point at `base --all` instead of assuming `dev`.
- Plan commit subjects are documented as naming the **slug**, not the title, so
  the hand-written `activate`/`close`/`retire` subjects match what `add` and
  `finalize` write. The convention is stated once in the rule.
- `close` returns to the mainline via `base` rather than a hardcoded `git
  checkout dev`, and its cleanup warning covers every mainline branch.
- The convention rule documents the subplan-only `sub:` key and its position in
  the frontmatter (directly after `slug`).

### Fixed

- The `add` skill's own title placeholders were Title Case while the same file
  required sentence case; its `## Umbrella + subplans` and `## Batch / deferred
  creation` sections also sat between steps 1 and 2, so the remaining steps read
  as part of batching. Steps 1–3 are now contiguous.
- The `implement` skill's worktree example named a `plan/<NNN>-<slug>` branch
  while the same skill derives `feature/<slug>`.
- `add` and `finalize` could commit a plan into a **different repository** than
  the one they ran in. An ambient `GIT_DIR` — which git exports to every hook it
  runs, so a hook or wrapper inherits it without anyone setting it — outranks the
  working directory, so the `plan [add]` commit landed in another repo's history
  while the plan files stayed uncommitted here. Every git shell-out is now pinned
  to an explicit repo root with the location variables stripped, including the
  hook-detection helpers and `pre-commit install`.

## [0.4.0] - 2026-07-09

### Added

- `permissions` command that maps an automation level (`none`, `assist`,
  `confirm`, `full`, with numeric aliases `0`-`3`) to the Bash allow-rules in
  `settings.json`, pre-authorizing the shell commands each level unlocks so the
  lifecycle skills prompt less. Grants are additive and never downgrade an
  existing `deny`/`ask` rule, and are mode-aware for global vs. local installs.
- `validate` check that flags malformed PR URLs in plan frontmatter.

### Changed

- The close-gate check now aligns with CI and points at the `permissions`
  command for reducing prompts.

### Fixed

- `permissions` apply is now a no-op when there is nothing to add.
- Fixed the pipeline review-gate note prose wrap.

## [0.3.1] - 2026-06-28

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
