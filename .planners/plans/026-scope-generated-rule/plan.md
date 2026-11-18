---
id: 26
slug: scope-generated-rule
status: active
branch: feature/026-scope-generated-rule
created: 2026-11-18T13:38:44-08:00
concluded:
pr: https://github.com/gitronald/planners/pull/75
---

# Scope the generated rule to plan files and keep a short always-on part

## Plan

### Goal

`planners install` writes the plan-file convention as one user-level Claude Code rule
with no `paths` frontmatter, so its 340 lines load into every session in every
repository, whatever the session is doing (issue 74). Split it in two: the full
convention, scoped so it loads when a session touches a plan file, and a short always-on
rule holding what a session has to apply before it has opened one.

### How a scoped rule loads

From the Claude Code memory documentation and fresh-session probes on Claude Code
2.1.327, recorded in the issue:

- `paths` is the only frontmatter key the harness reads, and the block is removed
  before the rule enters context. pkgskills already writes its stamp into that block,
  under `metadata`, and lifts a source's own block verbatim, so a `paths` key in the
  source reaches the installed file with no library change
- A scoped rule loads on a Read, Write, or Edit of a matching file, and on a Bash
  command that counts as a read of one file. Running `planners` does not load it
- Patterns match files under the session's primary working directory only, and a
  double-star pattern naming a dot directory matches inside it

### Decisions

1. **`planners.md` keeps the full convention and gains `paths`**: `**/.planners/**` and
   the legacy `**/docs/plans/**`. Its opening sentence stops calling itself the always-on
   summary
2. **A second rule, `planners-core.md`, is always-on.** It is short (a screen, not a
   page) and holds only what a session applies unprompted or before any plan file is
   open:
   - where plans live, that the lifecycle goes through the skill and the CLI and never
     by hand (no hand-edited index, no typed timestamp or plan number), and that
     `planners skill <subcommand>` is printed before a step is described or run
   - that the full convention is the scoped rule, when it loads, and that
     `planners rule planners` prints it for a session that needs it sooner (a plan read
     in another repository or a sibling worktree, a question about plans with no file
     open)
   - the mainline guard for `plan [add]` and `plan [activate]`, and that
     `--allow-branch` is not a way past it
   - tool-written commit subjects (`plan [<verb>]: NNN - <slug>`): not hand-written,
     not imitated, not flagged
   - no personal or local specifics in a plan or its Log, with the public and private
     enforcement
   - never overwrite plan content, Handoff excepted
   - batch creation through `add --defer` and `finalize`
   - the legacy `docs/plans/` layout stays until a repo is migrated
3. **The split is by duplication, not by moving text.** The scoped rule stays complete
   on its own, so a session that has it loaded needs nothing from the core rule, and the
   core rule repeats the few lines above in short form. The cost is a second place to
   keep those lines true; a test pins that every `{cli}` command the core rule names
   exists
4. **No migration code.** Both files carry the pkgskills stamp, so an upgrade rewrites
   `planners.md` in place and writes the new file, and `install --check` reports the
   old unscoped file as drifted and the new one as missing until `install` runs

### Files

- `planners/prompts/rules/planners.md`: frontmatter, opening sentence
- `planners/prompts/rules/planners-core.md`: new
- `planners/host.py`: a second `Rule`
- `tests/test_host.py`: both rules install in both modes; the scoped one carries
  `paths` beside the stamp and the core one carries none; `rule --list` names both;
  `install --check` after an upgrade from a stamped unscoped file
- `README.md` (the install step and the Convention rule section), `CHANGELOG.md`, and
  the two skills that say "the planners rule" where a reader may not have it loaded

### Verification

- The four checks: ruff lint, ruff format, pyrefly, pytest
- A real install from the branch build into a scratch home, then fresh sessions in a
  scratch repository: with no tool use the core rule is in context and the full one is
  not; after a read of a plan file both are. Record the Claude Code version
- The character count of the always-on part before and after

### Out of scope

- Shortening the convention itself
- Any change to pkgskills

## Log

- **2026-11-18T13:39:03-08:00** — Activated.
  - Branch: `feature/026-scope-generated-rule`
  - Base: `dev` at `28c986d`
  - Worktree: `.worktrees/026-scope-generated-rule`
  - PR: pending
- **2026-11-18T13:41:15-08:00** — PR opened: https://github.com/gitronald/planners/pull/75
- **2026-11-18T13:42:30-08:00** — Implemented the split and verified loading in real sessions.
  - What was done: `planners.md` carries `paths` frontmatter and a new sentence saying when it loads; `planners-core.md` is the always-on part; `host.py` declares the second rule; three skills say how to print the full rule where they cite it; README and changelog updated
  - Departures from the spec: no new test pins the commands the core rule names, since the existing prompt-commands test already covers every rule source. A consequence the plan did not name: with two rules, a bare `rule` command exits 1 and lists the names, so two existing tests now pass the name, and the changelog says so
  - Checks at eddb28f: ruff lint and format clean, pyrefly 0 errors, 830 tests passed at 95.10 percent coverage
  - Loading test (Claude Code 2.1.327): both rules rendered from the branch build into a scratch home, copied with a token line each into the user-level rules directory, and fresh haiku sessions run in a scratch repository. No tool use: the core token only, in 3 of 4 runs (the fourth returned nothing, and a repeat of the same prompt returned the core token). Read of a file under `.planners/`: both tokens. Read of a file under the legacy `docs/plans/`: both. Read of a README: the core token only. The copies were removed afterwards
  - Measure: the installed always-on text goes from 21,216 characters (0.16.2's one rule) to 2,642 (the core rule, frontmatter included); the scoped rule is 21,493
  - Not tested: a per-repo (`--local`) install in a real session, and loading after compaction
