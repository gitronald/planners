---
id: 22
slug: lifecycle-mechanizations
status: done
branch: feature/022-lifecycle-mechanizations
created: 2026-10-31T20:03:40-07:00
concluded: 2026-11-01T11:05:28-08:00
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
- **2026-11-01T10:53:54-08:00** — Implemented: 6 commits ahead of `dev`.
- **2026-11-01T10:59:03-08:00** — Reactivated: back to active after review.
- **2026-11-01T11:05:43-08:00** — Scope widened at the user's direction at the review gate: `activate` changed, which the plan's Out of scope excluded, because the review showed `block` could not be used cleanly without it. Commits since the last entry: `ef88873`, `0a441a0`, `6710ed4`.
  - `activate` returns a blocked plan without the mainline guard on the branch it records, after an earlier activation, and logs `Reactivated: back to active after a block.` Other blocked plans stay guarded, and the skill and rule now say to block on the feature branch. This revises the earlier entry's advice to block on the mainline.
  - Review follow-up, first pass at medium effort on the PR. Raised: a re-run of `block` committed an unrelated edit to a plan already blocked at HEAD; `add --needs` could complete a cycle; blocking on the mainline conflicted at merge (found with a scratch-repo probe). All three actioned, each with tests.
  - Review follow-up, second pass on the `activate` commit. Raised: the return printed the base-push report, listing branch commits as "other". Actioned, with a test.
  - Conscious no-ops: `_print_merge` and the stop message each spell out the `gh pr merge` argv, since sharing one changes the stop message's quoting; `block` and `implemented` each carry a resume check, and `implemented` keeps the weaker one, so an uncommitted edit to an `implemented` plan can still commit under its subject.
  - Rejected on review: the fork subject in `--print-merge` and its lack of a done check are both intended.
  - Checks at `6710ed4`: 778 tests passed, coverage 95.07%, ruff, ruff format, and pyrefly clean.
  - Not verified: `--print-merge` against a real fork PR.
- **2026-11-01T11:05:45-08:00** — Implemented: 12 commits ahead of `dev`.

## Retrospective

- The three items went as specified, and most of the work was in what `block` exposed. Mechanizing a by-hand step showed that its return path did not work for a plan with a live branch, a gap the prose had hidden.
- The Out of scope line held until the review showed the new command could not be used cleanly, and the user widened it at the gate. The spec above stays as written, and the Log records the change.
- A scratch-repo probe of the whole round trip found the merge conflict. The finders and the unit tests did not, since each step passed on its own. Probe a lifecycle command across a merge, not only at its own exit.
- Advice in a skill is a claim to test. The first text told sessions to block on the mainline, the one place that led to the conflict.
- `implemented` keeps the weaker resume check that the review fixed in `block`. It commits an unrelated edit to an `implemented` plan under its own subject when re-run, which is worth changing when that command is next touched.
- Applying scripted edits twice duplicated a sentence in the rule, and reading the full diff before the first commit caught it.

