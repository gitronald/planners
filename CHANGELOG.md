# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
