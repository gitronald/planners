---
id: 22
slug: lifecycle-mechanizations
status: draft
branch:
created: 2026-10-31T20:03:40-07:00
concluded:
pr:
---

# Mechanize the remaining by-hand lifecycle steps

## Plan

Plan 021's review pass (a Codex read-only review, triaged by the main session) found
three places where a skill still walks a session through a by-hand sequence that one
command or flag could own. Each adds behavior, so 021 held them back; this plan carries
them. Implement each with a test and a skill-text update that points at it.

1. **`planners block <NNN>`** for a top-level plan. The `update` skill today says: edit
   `status:`, run `planners index .`, and commit `plan [block]: <NNN> - <slug>`. The
   command sets `status: blocked` from `active` or `draft`, refreshes the index, and
   commits with that subject, reusing the plan-loading, index, and commit helpers in
   `cli.py`. The reason stays authored, in the plan's Handoff. Nested subplans already
   have `subplans --set <letter>=blocked` and are out of scope.
2. **`planners finish <NNN> --print-merge`**. The `close` skill has the session assemble
   the merge subject by hand (`merge: PR #<N> - <branch>`, cut with `...` past 60
   characters), while `finish.py` already formats it for the stop message. The flag
   prints the `gh pr merge` (or, with `--no-pr`, the local `git merge`) command and
   exits without fetching or changing anything; the session still runs the merge
   itself, so the automation level keeps governing it.
3. **`planners add ... --parent <N> --nested --needs <letter>`** (repeatable). The `add`
   skill says `needs:` "is added by hand" because `add` has no flag for it. The flag
   passes the letters through to the rendered subplan frontmatter, after `branch:`, and
   is absent when unspecified so existing scaffolds stay byte-identical.

### Wording carried from 021

**Done on `dev` ahead of this plan (see the Log), so nothing in this section remains.**

021's end-to-end read of the rendered text found these wording problems. They did not
justify a change of their own; they land here because this plan edits the same text. The
last one is a wrong statement about `finish`, and the others change no instruction.

- **`close` skill, the `gh pr ready` bullet.** It ends "stop before the merge (a draft
  can't be merged), or the user can mark it ready by hand", which reads as if stopping
  and the user's fix were alternatives. Make it say the session stops and the user can
  mark the PR ready.
- **Rule, *Generated Log entries*.** "`--worktree <path>` (repo-relative) or
  `--no-worktree` records a worktree other than" the default, but `--no-worktree` records
  the main checkout. Say so.
- **`orchestrated-run` doc, the opening.** It describes a run over an umbrella's subplans,
  while the `implement` skill sends any plan there. Add a line for a plan with no
  subplans.
- **`close` skill, *When `finish` stops*.** It says `finish` "leaves the state as it was",
  and its list of causes no longer names a branch that holds commits the base lacks. That
  stop comes after the worktree is removed and the base is checked out and pulled, so
  those steps stay done. Say that the steps before the stop stay done and the one it
  stopped on is left undone, and restore the missing cause, which `finish --help` still
  lists.

### Out of scope

- Any change to what the existing commands do without the new flag or command.
- Anything upstream. The two items 021 first recorded as upstream stayed in this package,
  and 021's Log settles both: the orchestration guidance became `planners doc
  orchestrated-run`, and the permission-profile explanation became a trim that points at
  `planners permissions --help`.

## Log

- **2026-11-01T10:43:54-08:00** — Fixed the four items under *Wording carried from 021* directly on `dev`, at the user's direction, ahead of this plan (`d05f48b`), so none remains for it. Items 1 to 3 are unchanged and still open.
  - The same wrong claim about a stop was also in the docstrings of `planners/finish.py`; those are corrected too.
  - Added tests in `2a4dd77`: a stop on an origin branch ahead of the base keeps the worktree removal and the pull, and a re-run stops at the same place; the `pre-worktree-remove` hook runs inside the worktree before removal, and a failing hook stops `finish` with everything untouched. That hook had no test before.
  - Checks: 734 tests passed, coverage 94.94%, ruff, ruff format, and pyrefly clean, run before these commits on the same tree.
  - Not released: the fixes are in `[Unreleased]`, so the published 0.15.0 still carries the old text.
