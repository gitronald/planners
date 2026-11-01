---
id: 21
slug: package-simplification
status: draft
branch:
created: 2026-10-31T19:48:11-07:00
concluded:
pr:
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
