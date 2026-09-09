---
id: 4
slug: index-merge-semantics
status: active
branch: feature/index-merge-semantics
created: 2026-09-08T10:57:28-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/18
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

## Log

### 2026-09-08 — step 1 prototyped; the three-part design is replaced by one part

Step 1 asked which hook stage could put a regenerated index into the merge commit. The
answer is **none**, and chasing it surfaced a driver the plan never considered that makes
the hook unnecessary. Scratch repos under a temp dir; two branches that both add plans,
which is the collision the survey counted.

**Finding 1 — a merge-time hook cannot affect the merge commit.** `pre-merge-commit`
*does* clear the bar step 1 was unsure about: a hook that regenerates and then
`git add`s the index reports `Passed`, because pre-commit's "files were modified by this
hook" check compares the **unstaged** diff, which staging leaves empty. But the merge
commit still shipped the un-regenerated index — git writes the merge tree from the index
it already held, so the corrected file was left *staged and uncommitted* after a merge
that reported success. `prepare-commit-msg` behaves identically. This is git's documented
"the hook cannot affect the outcome of the merge," now measured rather than assumed. So
`pre-merge-commit` has no advantage over `post-merge`; both leave a repair to be
committed afterwards, and the ritual step 1 hoped to avoid is unavoidable at any stage.

**Finding 2 — `merge=union` is built in, so two of the three parts disappear.** The plan
reached for `merge=ours` and then spent its length on the consequence: git will not take
a driver *definition* from a repository, so a per-clone `git config merge.ours.driver
true` is required, is silently absent in a fresh clone, and needs a drift detector to be
visible at all. `union` is a **low-level built-in** — it needs no definition, so a bare
`.gitattributes` line is self-sufficient in every clone including a fresh one. Measured
on the two-branch case: no conflict, clean tree, and a merge commit whose index was
byte-identical to a fresh render, with no hook and **no `git config` at all**.

**Finding 3 — union's failure mode is visible and non-destructive, unlike `ours`.** With
the harder collision — the feature branch *closes* a plan (its row is rewritten and
re-sorts) while the base *adds* one — union keeps both versions of the changed row, so
plan 001 appears twice, once `draft` and once `done`. That is wrong, but it is
**stale-and-loud**: no row is lost, the table still renders, and `planners index .`
repairs it. `merge=ours` fails the opposite way — it silently **drops** the incoming
branch's rows, which is the same "looks like success" failure the plan already rejects
for a regenerating merge driver, and it costs a per-clone config to get.

**Revised design.** One committed part, no per-clone git state:

| Part | Kind | Status |
|---|---|---|
| `.gitattributes`: `.planners/README.md merge=union` | committed repo content | keep |
| `git config merge.ours.driver true` | per-clone `.git/config` | **dropped** — union needs none |
| a merge-stage hook that regenerates the index | committed config + per-clone registration | **dropped** — cannot reach the merge commit (finding 1) |

Steps 2 and 3 shrink accordingly: `install` writes and `install --check` reports one
line in `.gitattributes`. Step 4 grows in importance — with the hook gone, a stale-index
check is the only thing that catches union's duplicate row, so it moves from optional to
the repair mechanism.

**Finding 4 — GitHub's server-side merge does NOT honor `merge=union`.** Measured, not
assumed: two throwaway PR pairs on this repo with *identical* index edits — both sides
appending a different row at the same spot — differing only in whether the branches
carried the attribute. Locally the control conflicted and the attribute pair merged
cleanly. On GitHub both reported `mergeable=CONFLICTING`, `mergeStateStatus=DIRTY`. The
attribute was present on the head, the base, and their merge base, so this is not a
question of which commit the attribute was read from; GitHub's merge does not consult it.
(Probe PRs #19/#20, since closed and their branches deleted.)

One hypothesis is not excluded: that GitHub reads `.gitattributes` from the repository's
**default branch**, which is `main`, where the attribute does not exist yet. It is a weak
hypothesis — a merge between two other branches reading attributes from a third would be
odd, and git's own semantics read them from the merge itself — but it resolves for free
once this lands on `main`, so **re-check then** before treating the PR path as settled.

**What that means for the fix's reach.** It is narrower than the plan assumed but not
diminished. `close` merges through `gh pr merge`, so a PR whose two sides both touched the
index still shows as conflicting on GitHub. What changes is the *resolution*: pulling the
base and merging locally now resolves the index automatically instead of requiring a
hand-edit of a generated file, and `validate` then tells you whether the union result
needs regenerating. Every purely local merge — syncing a long-lived branch, merging
without a PR (plan 002's path) — is fixed outright. The docs must say local merges, not
merges.

**Step 3's inherited follow-ups survive the shrink.** 005's staged-diff check and 006's
fresh-clone hook-registration finding were routed here because `install --check` is the
detector for per-clone state. Union removes the per-clone state *this* plan introduced;
it does not remove the pre-commit hook registration those two are about, so step 3 still
has that job.

### 2026-09-08 — steps 2-4 implemented on `feature/index-merge-semantics` (PR #18)

Three commits: the attribute in `install`, the stale-index gate in `validate`, then the
docs.

**Step 2 — `install` writes one line.** `wire_gitattributes` appends
`.planners/README.md merge=union`, preserving any other attributes the repo already has,
the way `wire_precommit` appends its hook block rather than parsing the file. A line that
*names* the index but grants something else — the `merge=ours` stopgap the Notes describe
— is reported and left alone; `install --force` rewrites that one line in place, which is
the migration path. `INDEX_PATH` moved from `cli.py` to `index.py` so the CLI (which
writes the file) and `install` (which names it in an attribute) share one spelling.

**Step 3 — `--check` grew two lines.** `gitattr:` reports the attribute and gates, like
`holder:` and `rule:`. `hook:` reports whether the validate git hook is registered *in
this clone* and deliberately does **not** gate: a consumer without `pre-commit` is
correctly installed, just unguarded, and failing them would be wrong. This is 006's
finding closed — the silence is now a printed line, and the holder stub tells every
`/planners` invocation to run `install --check` first, so it is seen. `report_hook` is a
read-only sibling of `activate_precommit`, which answers the same question by trying to
fix it; the two keep separate vocabularies rather than one overloaded status.

**Step 4 — decided yes, `validate` fails on a stale index.** With the merge hook dropped
this is the only thing that notices union's duplicate row, so it moved from optional to
load-bearing. It resolves a repo root from a plan file's `.planners/plans/<dir>/plan.md`
shape, which matters because pre-commit passes *filenames*, never a root — a check that
only fired for a directory argument would never fire where it counts. Two deliberate
narrowings: an **absent** index is not a violation (that is `install`/`add`'s business,
and failing on it would break a checkout that has not generated one yet — though it stays
a violation for `finalize`, which just wrote it), and a legacy `docs/plans/` layout is
left alone.

The fresh-render computation existed in two places already and now exists in one
(`_rendered_index`), used by `_refresh_index`, `_finalize_self_check`, and the new gate —
005's retrospective lesson (grep for what already does the job *before* writing the
helper) applied on the way in rather than after a review.

**Verification.** 23 new tests (376 total, up from 353); `ruff`, `ruff format`, and
`pyrefly` clean. Ten tests were **mutation-checked**, each failing only its own test:
union-vs-ours as the driver, whitespace normalization, the no-clobber rule, the
trailing-newline fix, `--check` gating on the attribute, `--check` *not* gating on the
hook, the stale-index gate, root-resolution from a single file, absence not counting as
stale, and the legacy-layout exclusion.

Two mutations were rejected and replaced rather than reported as passes. The `#`-comment
skip in `_index_attr_line` turned out to be **unreachable for correctness** — a comment's
first field always starts with `#`, so it can never equal the pattern — so breaking it
failed nothing; the guard stays (it is how you parse this format) but is now documented as
defensive, and the whitespace-normalization mutation took its place. The first
legacy-layout test was likewise not load-bearing: `docs/plans/` was excluded by the
missing-index filter, not by the path check, so the test was rebuilt as a repo
mid-migration — legacy plans *and* a `.planners` index — where only the path check saves
it.

**End to end, through the real `install`.** A fresh repo, `planners install`, one branch
closing a plan while the base adds one — the merge that used to conflict now reports
`Auto-merging` and succeeds with **no `git config` ever run**; `validate` then reports the
index stale, and one `planners index .` repairs it. The planners repo itself now carries
the attribute.
