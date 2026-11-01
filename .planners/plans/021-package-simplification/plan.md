---
id: 21
slug: package-simplification
status: active
branch: feature/021-package-simplification
created: 2026-10-31T19:48:11-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/64
---

# Simplify the package and its skill text

## Plan

### Goal

Cut redundancy from the package and from the bundled skill and rule text,
without changing what the commands do or what the skills tell a session to do.
Two kinds of cut are in scope:

1. **Code.** Duplicated helpers, parallel code paths that do one job, dead
   branches, and logic a session is told to do by hand that the CLI could do
   instead ("mechanize").
2. **Prompt text.** Material that `rules/planners.md` and the eight
   `skills/*/SKILL.md` bodies repeat between themselves, or that restates what
   the CLI already prints or enforces, so the installed text is shorter and
   reads once.

### Approach

1. **Review pass.** A Codex (`gpt-6-astra`) read-only pass over the whole
   package and prompt tree produces a numbered findings report with, for
   each: the file and lines, what is redundant or could be mechanized, the
   proposed change, and the risk. It changes nothing.
2. **Triage.** The main session reads every finding against the code and the
   installed text, accepts, rejects, or narrows each, and records the verdicts
   in this plan's Log.
3. **Implement.** The accepted findings land in logical commits on the plan's
   branch: code cuts with their tests, prompt cuts as text edits, and any new
   CLI mechanization with a test and a skill-text update that points at it.
4. **Verify.** `uv run pytest`, `ruff`, and `pyrefly` pass; `planners install
   --check` is clean in this repo after a reinstall; the rendered rule and
   skill text are re-read end to end once.

### Decisions

- Behavior is held fixed. A finding that would change a command's contract
  or a skill's instruction (not just its wording) is recorded as a follow-up,
  not implemented here.
- A finding that belongs to `pkgskills` (the prompt-packaging library) or to
  another shared convention is noted in the Log as upstream work and left
  out of this plan's diff.
- Codex drafts and reports; the main session verifies and commits.

### Out of scope

- New features or new subcommands.
- Changes to the plan-file schema or the index format.
- Rewording that changes meaning (plan 015 covered the language pass).

## Log

- **2026-10-31T19:48:33-07:00** — Activated.
  - Branch: `feature/021-package-simplification`
  - Base: `dev` at `ed9f15f`
  - Worktree: `.worktrees/021-package-simplification`
  - PR: pending
- **2026-10-31T20:03:04-07:00** — Codex (gpt-6-astra) ran a read-only review pass; the main session verified each finding against the source and the tests, then implemented the accepted ones.
  - Accepted and done: code (#14 `_commit` at finalize and activate, #15 `next_letter` delegates to `next_sub`, #16 `_collect_metas` strict mode, #17 `cli.main`, #18 note trimming in `log_entry`, #19 `is_safe_slug` whitelist only); rule cuts (#1 nested subplans, #2 index merge cases, #6 frontmatter template, generated entries, numbering, and the guard heuristic, #5 close-out ownership); skill cuts (#3 backfill glossary, #4 update's Handoff, #7 finish's step list and implement's cleanup paragraph, #8 start's step table, #9 conclude's dating rule, #12 review entries through `log`); and the #21 drift fix (`permissions` prints unless `--apply`).
  - Prompt text went from 1909 to 1794 lines; the always-on rule from 412 to 340. Tests 729 passed, coverage 94.88%, ruff and pyrefly clean, run by the main session (Codex's sandbox could not take uv's lock).
  - Deferred as follow-ups, since each adds behavior: #10 a `block` command for top-level plans, #11 a `finish --print-merge` that prints the merge command, #13 an `add --needs` flag for nested subplans.
  - Upstream, not implemented here: #20 the generic agent-orchestration guidance in the implement skill overlaps a global orchestration rule and belongs in a shared convention; #21 the permission-profile explanation belongs in pkgskills, which owns the command.
  - What the brief got right: numbered findings with file:line evidence and a category each made triage mechanical. What it got wrong: the read-only sandbox blocked uv, so every measurement in the report was derived from source, not run.
- **2026-10-31T20:03:13-07:00** — PR opened: https://github.com/gitronald/planners/pull/64
- **2026-10-31T20:03:22-07:00** — Implemented: 6 commits ahead of `dev`.
- **2026-11-01T09:58:11-08:00** — Reactivated: back to active after review.
- **2026-11-01T09:59:33-08:00** — Moved the orchestrated-run guidance out of the implement skill into a pkgskills Doc, printed by `planners doc orchestrated-run`, so a session loads it only when the user asks for subagents or a workflow. This replaces the upstream proposal for finding #20: a personal rule cannot carry guidance for a package other people install, and the text is about plan work far more than it duplicates any shared rule.
    - Why now: a transcript count on one machine found the section loaded in 161 sessions since it shipped, and at most 16 of them ran two or more working agents or workflows. It is about 7 kB, roughly 1,800 tokens by estimate.
    - Scope: an exception to this plan's 'no new subcommands' line, made at the user's direction. `doc` comes from pkgskills and adds no command code here beyond the declaration and the repository-guard exemption. The text moved unchanged apart from heading levels and one cross-reference; the implement skill gained a pointer that applies to any plan, not only an umbrella.
    - Checks: 731 tests passed, coverage 94.88%, ruff and pyrefly clean, and a built wheel carries the doc.
