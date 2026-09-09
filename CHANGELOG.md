# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
