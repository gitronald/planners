---
id: 4
slug: index-merge-semantics
status: active
branch: feature/index-merge-semantics
created: 2026-09-08T10:57:28-07:00
concluded:
pr:
---

# Own the generated plan index's merge semantics in install

## Plan

`planners index` writes `.planners/README.md`, and every consumer repo tracks it. A
generated file that is committed has merge semantics whether or not anyone chose them,
and planners currently ships none — so any merge that added plans on both sides of the
fork point conflicts on the index, and each repo is left to invent its own fix.

This is not rare. Surveying the merge history of 42 repos on planners, 23 merges across
8 of them had both parents modify `.planners/README.md` since their merge base; the
worst single repo accounted for 11. Any repo with a second long-lived branch, or with
feature branches created while the base branch keeps adding plans, hits it eventually.

### What the fix looks like

Three parts. Only the first is repo content; the other two are per-clone git state,
because git will not read them from a repository:

| Part | Kind |
|---|---|
| `.gitattributes`: `.planners/README.md merge=ours` | committed repo content |
| a pre-commit-managed hook that regenerates the index on merge | committed config **+** per-clone hook registration |
| `git config merge.ours.driver true` | per-clone `.git/config` |

Git will not take a merge-driver *definition* from the repository — by design, since a
driver is an arbitrary command a clone could otherwise ship. So the `merge=ours`
attribute is inert until someone runs the config command by hand. The failure is quiet
and safe (an unconfigured clone just gets the ordinary conflict back) but it is
invisible: nothing reports that the setup is missing.

That invisibility is exactly why this belongs in `install` rather than in each repo's
README. `install` already writes the rule and the skill holder, writes the
`.pre-commit-config.yaml` entry while preserving entries already there, activates the
git hook, and degrades gracefully when `core.hooksPath` makes `pre-commit install`
refuse; `install --check` already reports drift across all of it. **The drift check is
the feature** — it is what turns a silent misconfiguration into a loud one, and it can
only exist here. A repo that hand-rolls the three parts locally gets the fix but not the
detector, which is the state this plan replaces.

### Do not reintroduce the obvious fix

A merge driver that regenerates the index in place is wrong, and convincingly so. During
a merge the incoming side's plan files are not yet on disk, so it regenerates from half
the plans, reports a clean merge, and silently drops the other branch's rows — worse
than the conflict it replaces, because it looks like success. Verified in a scratch
repo. Regeneration has to happen once both sides' plan files are present.

### Steps

1. **Prototype the hook stage before committing to one.** `post-merge` is the safe
   choice and is known to work, but it runs after the merge commit already exists, so
   the corrected index arrives as an uncommitted change to be committed alongside — a
   ritual every merge then inherits. `pre-merge-commit` fires after the merge is
   resolved in the worktree and before the merge commit is written, which satisfies the
   both-sides-on-disk condition *and* puts the correct index in the merge commit itself.
   The unknown: pre-commit treats a hook that modifies files as a failed run, so confirm
   whether a regenerate-and-stage hook can pass cleanly at that stage. Fall back to
   `post-merge` if it cannot.
2. **Teach `install` to write all three parts**: the `.gitattributes` line (idempotent,
   preserving any other attributes already in the file, the way the pre-commit entry is
   already preserved on reinstall), the hook entry at whichever stage step 1 settles on,
   the merge-driver config, and registration of the extra hook type.
3. **Teach `install --check` to report each part as drift** — including the per-clone
   config and the hook registration, which are the parts a fresh clone silently lacks
   and the parts a committed file can never cover.
4. **Decide whether `validate` should also fail on an index that disagrees with the plan
   frontmatter.** That would make a stale index a pre-commit gate rather than only a
   merge-time repair, and would catch the case where someone edits plans without
   reindexing at all.

### Open decision: keep tracking the index at all

Every part above exists only because a generated file is tracked. Not tracking it
deletes the attribute, the driver config, the hook stage, and the drift check in one
move — the cheapest possible fix.

The reason to keep tracking it: `.planners/README.md` renders as a table when the
directory is browsed on a git host, so plans stay readable to someone who has not
installed the tool. That is the whole point of a committed index, and it is a real
thing to give up.

Settle this before step 2 — it decides whether any of the rest gets built.

**Resolved 2026-09-08: keep tracking it.** The host-rendered table is the point of a
committed index, and dropping it to avoid a merge conflict trades a visible feature for
an invisible one. All four steps stay in scope.

### Post-005 updates (2026-09-08)

Written ~8 hours before plan 005 concluded; four things moved under it.

- **This plan now gates two deferred follow-ups.** 005 parked its pre-commit
  staged-diff check on activation behind it ("it follows plan 004, not this"), and 006's
  post-close log routed its incidental finding — the `planners validate` hook silently
  absent in a fresh clone — to step 3 rather than a new plan. Step 3 is the home for
  both; neither is separately tracked.
- **Step 4 is reuse, not invention.** `_finalize_self_check` already compares the tracked
  index against a fresh render (`planners/cli.py:488-492`, "index is stale"). Making
  `validate` fail on a stale index is lifting that comparison, not writing one.
- **Step 3 has helpers now.** 005 added `_git_status_porcelain(root, pathspec)` and
  `_is_unmodified(root, path)`, which is the per-path cleanliness query a drift check for
  the index wants.
- **`activate` is a third index-committing site** (`planners/cli.py:1209`), alongside
  `add` and `finalize` — all three on the mainline, the side `merge=ours` keeps. It
  raises index churn on the base without changing the conflict shape the survey measured.

### Notes

- Found in a consumer repo whose two long-lived branches collided on the index twice.
  The arrangement above was worked out and committed there as a stopgap; it works, but
  the two per-clone commands live in that repo's README as setup instructions, which is
  the documentation-instead-of-tooling outcome this plan exists to remove.
- The plan-number race (two branches independently taking the same `NNN` from `planners
  add`) surfaced while testing this, but it is the batch-creation problem the
  `--defer` / `finalize` flow already addresses. Out of scope here.
