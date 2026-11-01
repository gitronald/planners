---
id: 22
slug: lifecycle-mechanizations
status: active
branch: feature/022-lifecycle-mechanizations
created: 2026-10-31T20:03:40-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/66
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
- **2026-11-01T10:46:44-08:00** — Activated.
  - Branch: `feature/022-lifecycle-mechanizations`
  - Base: `dev` at `726fb65`
  - Worktree: `.worktrees/022-lifecycle-mechanizations`
  - PR: pending
- **2026-11-01T10:53:46-08:00** — PR opened: https://github.com/gitronald/planners/pull/66
- **2026-11-01T10:53:48-08:00** — Implemented the three items, one commit each plus a docs commit: `2997b33` (`block`), `9885496` (`finish --print-merge`), `728a090` (`add --needs`), `c123f58` (rule, README, changelog).
  - Checks at `c123f58`: 769 tests passed, coverage 95.03%, ruff, ruff format, and pyrefly clean. `dev` had not moved, so no merge was needed.
  - `block` has no mainline guard, as the spec names none. It commits where it runs, like `log` and `retire`. `activate` returns a blocked plan only on the mainline, so a plan blocked on its feature branch reads `active` on the mainline and cannot return without `--allow-branch`. The by-hand flow had the same trap. The skill and the rule say to block on the mainline, and a test records the behavior.
  - `--print-merge` reads the PR number from the plan's URL and makes no network call, taking "without fetching" literally. So it does not check the PR's state, and a fork PR's subject lacks the `<owner>/` that `finish`'s stop message gets from `gh`. The `close` skill says to add it.
  - `finish`'s stop message still double-quotes its subject while `--print-merge` uses `shlex.join`. Changing the stop message is out of scope here, so a branch name holding `$(...)` stays unsafe to paste from that message.
  - `--needs` refuses a malformed letter, the subplan's own letter, and a repeat. It warns, without refusing, on a letter with no subplan yet, since the `add` skill's order allows naming one later.
  - `pr_number` moved to `utils.py`, so `index.py` and `finish` share one parser.
