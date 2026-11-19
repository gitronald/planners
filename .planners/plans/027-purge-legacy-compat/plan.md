---
id: 27
slug: purge-legacy-compat
status: active
branch: feature/purge-legacy-compat
created: 2026-11-18T17:25:36-08:00
concluded:
pr: https://github.com/gitronald/planners/pull/77
---

# Remove the legacy layout and pre-pkgskills compatibility

## Plan

### Background

planners still carries support for states no consumer is in: the old
`docs/plans/{NNN}-{slug}.md` + `TODO.md` layout, the `completed` frontmatter key that
`concluded` replaced in 0.2.0, and install files written before planners adopted
pkgskills. Nobody asked for this compatibility, and some of it does harm. The full
rule's `**/docs/plans/**` glob loads the convention into any repo that happens to
have a `docs/plans/` directory, including repos that do not use planners.

### Decisions

1. **No layout but `.planners/`.** The tool, the rules, the skills, and the docs
   describe one layout. A repo with no `.planners/plans/` has no plans, and planners
   says nothing about other directories
2. **No upgrade path from before pkgskills.** An install written before pkgskills
   (the HTML-comment stamp, or a `plan-files.md` rule) is treated as a file planners
   did not write: `install --check` reports it, and `--force` replaces it. Upgrades
   between pkgskills-stamped releases are unchanged
3. **History stays.** CHANGELOG entries and earlier plans are records and are not
   edited. This plan's own CHANGELOG entry describes the removals under `Removed`

### Changes

Legacy layout:
- `planners/prompts/rules/planners.md`: drop `**/docs/plans/**` from `paths`, the
  "or the legacy `docs/plans/`" clause, the "Migration in progress" callout, and the
  `docs/plans/...` example path (use `.planners/plans/...`)
- `planners/review.py`: `_check_layout` drops the legacy branch and keeps only the
  missing-plans-directory error. The `ReviewError` docstring stops naming the layout
- `planners/prompts/skills/review/SKILL.md`: drop the legacy-layout refusal sentence
- `planners/cli.py`: the `_repo_root_of` docstring stops naming `docs/plans/`
- `README.md`: drop the "(or the legacy `docs/plans/`)" clause
- `scripts/install.sh`: deleted (see below)
- Tests: `test_validate_ignores_a_legacy_layout_plan`, `test_legacy_layout_is_refused`,
  and `test_cli_refuses_the_legacy_layout` go. `SCOPE` in `tests/test_host.py` loses
  the second glob. Keep a test that a repo with no `.planners/plans/` gets the
  missing-directory error, adding one if none exists

`completed` key:
- The rule's "Field name" callout goes
- `test_old_completed_key_parses_empty_and_fails_validate` goes. An unknown key is
  already covered by the schema's own handling, so nothing replaces it

Pre-pkgskills install:
- `planners/host.py`: drop `PRE_ADOPTION_STAMP`, `legacy_stamps=`, and
  `previous_names=("plan-files",)` with their comments, and any import they leave
  unused
- `README.md`: the Upgrading paragraph stops mentioning the removal of an old
  `plan-files.md`, and the Convention rule section drops the `plan-files.md` sentence
- `tests/test_host.py`: the `OLD_STAMPS` fixtures and the tests built on them go,
  unless one of them tests a pkgskills-stamp case that still holds. Each removal is
  checked for what it covered

Rollout script:
- `scripts/install.sh` is deleted. It installed planners across many repos during the
  first rollout and has no callers. `planners install` does what it did, and its text
  still names `plan-files` and a `docs/plans/` migration. If `scripts/` is then empty,
  the directory goes too

Small leftovers:
- The rule's "(which replaces the retired `/plan-*` skills)" aside goes
- The "legacy abandoned" comment in `tests/test_cli.py` becomes "a status outside
  the enum"; the case stays

CHANGELOG: one `Removed` section under `[Unreleased]` covering the four removals.

### Order

1. Legacy layout, with its tests
2. `completed` callout and test
3. Pre-pkgskills install path, with its tests and README text
4. `scripts/install.sh`
5. Small leftovers and the CHANGELOG
6. A final grep for `legacy`, `docs/plans`, `TODO.md`, `plan-files`, `completed`,
   `PRE_ADOPTION`, and `install.sh` outside CHANGELOG and `.planners/plans/`, then the
   full suite and the three checks

Each step is its own commit.

### Out of scope

- Rewriting CHANGELOG history or earlier plans
- pkgskills' own `legacy_stamps` and `previous_names` features, which stay in that
  library

## Log

- **2026-11-18T17:26:12-08:00** — Activated.
  - Branch: `feature/purge-legacy-compat`
  - Base: `dev` at `94b357d`
  - Worktree: `.worktrees/027-purge-legacy-compat`
  - PR: pending
- **2026-11-18T17:29:21-08:00** — PR opened: https://github.com/gitronald/planners/pull/77
- **2026-11-18T17:29:31-08:00** — Implemented: 6 commits ahead of `dev`.
- **2026-11-18T17:29:43-08:00** — All six steps done, one commit each: legacy layout (0aef2c4), completed note (dc5c864), pre-pkgskills install path (c9f80ca), scripts/install.sh (6211344), leftovers and CHANGELOG (f080d07).
  - Departures from the spec: `test_anything_else_is_refused_until_forced` keeps its another-dist and no-stamp cases and gains a `pre-pkgskills` case with the old stamp verbatim, which locks in decision 2. Its three variants of the old stamp (ascii-hyphen, prose-after, bad-mode) went with the regex they tested. The two legacy-layout review tests were replaced by tests of the no-plans-directory error, which had none. The README's upgrade note now says "any release since 0.7.0" instead of "any earlier release"
  - Kept: the test that upgrades the pre-split unscoped rule, a pkgskills-stamp upgrade that still holds. `pre-commit.legacy` in finish.py is pre-commit's own backup name, not planners history
  - Surprise: with `previous_names` gone, install ignores an old `plan-files.md` entirely, so it is not reported either. The CHANGELOG says it is left in place to delete by hand
  - Verified at f080d07: full suite 818 passed, coverage 95.14%; ruff check, ruff format --check, and pyrefly clean; the rendered rule's `paths` lists only the `.planners/` glob; a final grep finds no remaining references outside CHANGELOG and earlier plans
  - Not verified: an install over a real pre-pkgskills file (none exist to test against)
  - This entry was written after `implemented`: the first attempt was refused because the path check read a glob as a local path
- **2026-11-18T17:45:44-08:00** — Reactivated: back to active after review.
- **2026-11-18T17:46:51-08:00** — Review of the implementation found three gaps; two are fixed and one is left open.
  - Fixed (3906c21): deleting the legacy-layout validate test left the `.planners` parent check in `_repo_root_of` with no test. With that condition removed the whole suite still passed. A test now validates a plan under `archive/plans/` beside an index that does not list it, and it fails when the condition is removed
  - Fixed (4596843): decision 2 was tested only on the holder and only for a plain `install`. A test now plants the pre-pkgskills stamp on the holder and the rule and checks that `install --check` reads both as `foreign` with one `overwrite:` hint, and that `--force` replaces both
  - Fixed (58e0868): the README's `--force` sentence names the stamp of a release before 0.7.0 as a fourth case
  - Decision 2 as written does not hold for an old `plan-files.md`: a probe in a scratch repo showed it is not reported by `install --check` and survives `--force`, since install no longer knows the name. The spec text stays as the record. The behavior stands as the CHANGELOG describes it (left in place to delete by hand), and no test locks it in
  - Open, not changed: the guards for the `abandoned` status are the same kind of history as the `completed` test this plan removed. They are three tests in `tests/test_conventions.py`, a case in `tests/test_metadata.py`, and the relabelled case in `tests/test_cli.py`, which now duplicates the `bogus` case above it. The spec said that case stays, so removing them is a decision for the owner or a follow-up
  - Correction to the entry above: six steps, five commits. Step 6 was verification and made no commit
  - The earlier "not verified" item is now covered by a synthetic file carrying the old stamp verbatim, in the probe and in the new test. No real pre-pkgskills install was found to test against: none of the repos checked on the development machine carries the old stamp or a `plan-files.md` rule
  - Verified at 58e0868: full suite 820 passed, coverage 95.14%; ruff check, ruff format --check, and pyrefly clean
- **2026-11-18T17:47:11-08:00** — Implemented: 13 commits ahead of `dev`.
- **2026-11-18T18:33:24-08:00** — Reactivated: back to active after review.
- **2026-11-18T18:34:08-08:00** — Removed the guards against the `abandoned` status (efd28dd), settling the open item in the entry above. The owner confirmed the status is dead and asked for the removal, which reverses the spec's "the case stays".
  - `tests/test_conventions.py`: the two tests that searched the package source and the skill bodies for the word are gone. The enum test keeps its seven members and their order, drops the `abandoned` assertion, and is renamed `test_status_enum_has_exactly_seven_members`
  - `tests/test_metadata.py`: the unknown-status case uses `bogus` in place of `abandoned`, so a value outside the enum is still covered beside the wrong-case `Active`
  - `tests/test_cli.py`: the relabelled case is removed, since it duplicated the `bogus` case above it
  - Evidence the status is dead: the `Status` enum has no such member, the package source does not contain the word, and no plan in this repo or in the other repos checked on the development machine carries it. The `update` skill still maps a request to "abandon" a plan onto `retire`, which is current behavior and stays
  - Verified at efd28dd: full suite 817 passed, coverage 95.14%; ruff check, ruff format --check, and pyrefly clean. The word no longer appears outside CHANGELOG and earlier plans
