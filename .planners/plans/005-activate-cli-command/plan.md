---
id: 5
slug: activate-cli-command
status: done
branch: feature/activate-cli-command
created: 2026-09-08T13:44:58-07:00
concluded: 2026-09-08T18:53:29-07:00
pr: https://github.com/gitronald/planners/pull/16
---

# Give activate a CLI command

## Plan

`activate` is the only lifecycle mutation still done by hand. `add` and
`finalize` are CLI commands; activation is prose in two skills telling the agent
to edit YAML frontmatter and hand-write a commit. Plan 003 shipped a mainline
guard on `add`/`finalize` and could not cover activation for exactly that reason
— there is no code to put the guard in. The guard gap is the symptom; this is the
cause.

The package already takes the opposite position everywhere else. From `add.md`:

> Do not compute the next number, run `date`, or edit the index yourself; the CLI
> handles all of it.

Activation contradicts that in the same breath: `implement.md` step 3 and
`update.md` step 2 both instruct a hand-edit of `status:` and `branch:`.

### The hand-edit is already producing drift

Not hypothetical. The `plan [activate]` commits in this repo's own history do not
agree on their subject:

```
plan [activate]: 000 - handle blocked pr-comment in close gate   <- lowercased title
plan [activate]: 001 - permission automation levels              <- lowercased title
plan [activate]: 003 - base-branch-guard                         <- slug
```

`add` never drifts this way because a format string owns it. Hand-editing
frontmatter is also the vector for the `completed:`/`concluded:` key drift and
the fabricated timestamps the convention rule spends paragraphs warning about.

### The two documented activate paths disagree

`implement.md` step 3 says to activate **on the base, before the branch exists**.
`update.md`'s activate row says to fill `branch` *"if on a non-main branch"* —
which presumes you are already standing on the feature branch, the position
`implement.md` exists to prevent and that plan 003 now refuses for `add`.

Both readings are documented, so an agent picking either is following the
instructions. A single command settles which one is real.

### Why a command rather than a pre-commit check

The alternative is extending the installed hook to reject a staged diff that
flips a plan to `active` while HEAD is off the mainline. That catches the
hand-written path too, which a command does not.

It is still the wrong first move: hook registration is per-clone, silently absent
in a fresh clone, and dead entirely when `core.hooksPath` is set. That is the
failure plan 004 exists to fix, and building a second thing on top of it before
it is fixed inherits the whole problem. A CLI guard travels with the installed
package and works in a fresh clone with no registration step.

If the hook version is still wanted afterwards, it layers onto 004's drift check
rather than competing with it.

### Scope: activate only, not a general status command

Only `draft -> active` belongs on the mainline. `log` and `close` updates happen
on the feature branch *legitimately* — that is where the work is — so a general
`planners status <NNN> <state>` command would need per-transition guard policy
and would be a much larger surface. Keep this to activation, where the mainline
rule actually applies.

### Steps

1. **Add `planners activate <NNN>`.** Resolve the plan directory from the number,
   accepting a subplan letter (`005a`). The mutate-preserving-body machinery
   already exists and is what `finalize` uses: `PlanMetadata.from_file` ->
   mutate -> `render_frontmatter()` + the original body via `split_frontmatter`.
   Shape it on `add`: guard, mutate, refresh index, commit.
2. **Apply the 003 guard**, sharing `_guard_base_branch` and `--allow-branch`
   verbatim rather than reimplementing the policy. Guard only the committing
   path, as `add` does — `--no-commit` writes without one.
3. **Fill `branch` by default.** `--branch <name>` when given, otherwise derive
   `feature/<slug>`, which is currently prose in `implement.md`. An
   already-populated `branch` is left alone.
4. **Settle the commit subject in code.** Pick one of the two forms in the
   history above and let a format string own it, the way `plan [add]` already
   does. The slug is the better choice — it is what `add` uses, it is stable, and
   it cannot drift from a retitled plan.
5. **Define the legal transitions.** `draft -> active` is the normal path.
   `inactive -> active` is legitimate (the rule says a parked plan may be
   revisited). `done`/`retired` must refuse — they are closed. Decide whether
   `active -> active` is a no-op or an error.
6. **Collapse the prose.** `implement.md` step 3 becomes one command instead of a
   hand-edit recipe, and `update.md`'s activate row points at it — which also
   removes the "if on a non-main branch" contradiction above.

### Open decisions

- **Does `activate` also create the branch?** `implement.md` step 4 creates a
  worktree from the activation commit. Folding that in would make one command own
  the whole base-first sequence and remove the ordering hazard entirely — but it
  puts worktree policy inside the CLI, which has so far stayed out of branch
  management. Leaning no; the guard already enforces the ordering that matters.
- **Should it refuse when the working tree is dirty?** The activation commit is
  supposed to stage only the plan file and the index, which it can do precisely
  regardless of other changes. Probably a non-issue, but worth confirming rather
  than inheriting the skill's warning as folklore.

### Out of scope

- A general `planners status`/`set` command for every transition.
- Guarding `log`/`close` commits — they belong on the feature branch.
- The pre-commit staged-diff check; it follows plan 004, not this.

### Notes

- **Two premises above went stale before this plan started.** Written 2026-09-08
  13:44, ~30 minutes before plan 003 concluded, so it describes docs that 003's
  review gate then fixed. *The two documented activate paths disagree* is
  resolved: `update.md`'s activate row no longer says "if on a non-main branch" —
  it now requires the mainline and points at `base --all`, agreeing with
  `implement.md`. Step 4 (*settle the commit subject in code*) is also
  pre-settled: the slug form is now the stated convention in the rule, and the
  skills' hand-written subjects match it, so step 4 is implementing a decided
  format rather than choosing one. The `plan [activate]` history quoted above is
  still the accurate record of the drift that motivated it.
- Depends on nothing in 004, and shares `_guard_base_branch` with 003. Can land
  independently of both.
- This does not make hand-editing impossible, the same way `add` does not. It
  closes the normal path, which is proportionate: the failure 003 documented was
  a session following the documented flow in the wrong order, not one
  deliberately bypassing the tool.

## Log

### 2026-09-08 — implemented on `feature/activate-cli-command` (PR #16)

All six steps landed in two commits: the command plus tests, then the prose that
pointed at the hand-edit it replaces.

**Steps 1–3.** `planners activate <NNN>` resolves a plan by number through a new
`_resolve_plan` helper, matching on the parsed `(number, letter)` pair rather than a
string prefix — so `5` and `005` are the same plan and `5` never matches `050-`.
Subplan letters (`005a`) resolve to their own directory, distinct from the umbrella.
The mutation is `PlanMetadata.from_file` -> mutate -> `render_frontmatter()` + the
original body via `split_frontmatter`, the shape `finalize` already uses, so the plan
text is preserved verbatim. `_guard_base_branch` and `--allow-branch` are shared with
`add` unchanged; only the committing path is guarded, matching `add`'s treatment of
`--no-commit`. A `prefix` property was added to `PlanMetadata` rather than
duplicating `add`'s inline `f"{id:03d}{sub}"`.

**Step 4 settled as the slug form**, owned by a format string, as the plan's own
Notes had already pre-settled.

**Step 5 — transitions.** `draft -> active` and `inactive -> active` are allowed;
`done`/`retired` refuse with a message naming the reopen path. `active -> active`
resolved as an **idempotent no-op**, not an error: re-activating destroys nothing
(unlike `add`, which refuses in order to protect a body), and the no-op keeps the
command safe inside a pipeline that retries. It also avoids attempting an empty
commit, which git would reject with a confusing message. When `branch:` is empty on
an already-active plan, it is still filled — the no-op fires only when nothing
would change.

### Resolved: both open decisions

- **Activate does not create the branch.** Kept as the plan leaned. The guard
  already enforces the ordering that matters, and worktree policy stays out of the
  CLI.
- **No dirty-tree refusal.** Confirmed rather than inherited as folklore: the commit
  stages the plan file and the index by explicit path, so unrelated uncommitted
  changes are untouched. A test asserts `git status --porcelain` is empty after a
  clean-repo activation.

### Verification

20 new tests (16 in `test_cli.py`, 4 in `test_base.py`); 348 pass, up from 328.
`ruff check`, `ruff format --check`, and `pyrefly check` clean.

Both guard-adjacent tests were **mutation-checked**, per plan 003's retrospective —
coverage reported its guard tests as exercising the code while they asserted nothing
about it:

- Neutering `_guard_base_branch` to return immediately fails
  `test_activate_refuses_on_a_feature_branch`. The mutated run prints
  `[feature/my-thing f47d103] plan [activate]: 005 - my-thing` — the activation
  commit landing on the feature branch, which is the exact failure this plan exists
  to prevent.
- Swapping the commit subject to the title form fails
  `test_activate_commits_by_default_with_slug_subject`, printing
  `plan [activate]: 005 - my thing` — the drift the plan documents in this repo's
  own history.

Both guard tests build a repo with a **born** HEAD before branching, so the
unborn-HEAD carve-out cannot short-circuit the guard the way it silently did for the
`finalize` tests 003 found.

### Step 6 — prose collapsed at every altitude

`implement.md` step 3 is now the command plus a `git push` instead of a four-bullet
hand-edit recipe. `update.md`'s activate entry was rewritten in **both** places it
appears: the prose section and the one-line action table at the top — 003's
retrospective noted that a doc restating itself at two altitudes has two sources, and
that a missed summary line left a generated file contradicting itself.

Three passages in the rule went stale the moment the command existed and were fixed:
the enforcement list (now names `activate`), the subject convention (`activate` is no
longer hand-written), and most importantly *"The activation commit is hand-written
`git commit`, so no CLI guard covers it"* — the sentence this plan's premise was built
on. `implement.md` step 2 carried the same claim and now reads as a convenience check
rather than the only protection.

### 2026-09-08 — review follow-up (close gate)

A four-dimension review of PR #16 raised 14 candidates; 11 verified as CONFIRMED, 3 as
PLAUSIBLE. Six were actioned in three commits, each with a paired regression test; the
rest are recorded below as conscious no-ops.

**The one real bug — the no-op masked a failed commit.** The idempotent
`already active; nothing to do` path decided from frontmatter alone, so it could not
tell *already committed* from *written by an earlier run that then failed to commit*.
Reproduced with a rejecting `pre-commit` hook: run one writes `status: active`, stages
the plan and the index, and exits 1; run two matches the no-op, prints `nothing to do`,
and exits 0 while the activation sits staged forever — a failure reported as success.
`add` does not have this hole, because it has no status to short-circuit on. The fix
adds `_is_unmodified(root, path)` and makes the no-op fire only when the file is also
clean against `HEAD`; when it is not, the command skips the (already correct) write and
finishes the commit, announcing `committing the pending activation`. Rather than a
second git query, `_git_status_porcelain` grew an optional pathspec argument — asking
about one file is what it was already shaped to do.

**Ordering: cheap validation now precedes the guard.** Two findings were the same
structural complaint. The guard ran first, so (a) re-running `activate` on an
already-active plan from the feature branch was *refused* — contradicting the
"safe inside a pipeline that retries" rationale this Log gives for the no-op — and
(b) activating a closed plan from a feature branch reported the branch, sending the
user to switch branches before learning the real blocker. Both fixed by resolving,
reading, and validating before the guard, and guarding immediately before the write.
`add` already had this shape: its `is_safe_slug` check precedes `_guard_base_branch`.
Nothing is weakened — a genuine no-op commits nothing for a branch to strand.

**Reuse the review caught that step 1 missed.** `ACTIVATABLE` was a third
classification of the status enum next to the existing `OPEN_STATUSES` and
`CLOSED_STATUSES`; the condition collapses exactly to `if meta.status in
CLOSED_STATUSES`, which is the set `validate()` already uses for this same question,
and the error message already said "it is closed". Related, and more pointed: this plan
added `PlanMetadata.prefix` *specifically* to stop duplicating the `f"{id:03d}{sub}"`
format, then left `index.py`'s `_num` — the one other place computing it on a
`PlanMetadata` — untouched. `_num` is now deleted.

**Docs.** The README was the altitude this plan forgot. Its Usage command list omitted
`activate` entirely, and its "Plan commits land on the mainline" blockquote still said
`add` and `finalize` refuse — the exact sentence updated in the rule file and
`implement.md`. A reader taking the README as the CLI reference would have concluded the
command did not exist and hand-edited the frontmatter, which is the whole failure this
plan exists to end. Both fixed; the changelog entry also now names subplan refs and the
retry behavior.

**Tests: 5 added (348 -> 353), and one strengthened.**
`test_activate_no_commit_is_unguarded` asserted only that the write happened, never that
the commit did not — the test named for the guarantee was the one that would not catch
its loss. All five new tests were **mutation-checked** against the specific regression
each exists to catch: reverting the no-op to frontmatter-only, moving the guard ahead of
the no-op check, moving the closed-status check after the guard, narrowing the no-op to
`already_active` alone, and moving `activate`'s `if no_commit: return` below the commit.
Each failed exactly its own test and no other. The last of these caught a *mutation* bug
first: `add` and `activate` share a byte-identical `if no_commit: return` / refresh tail,
so the first attempt silently mutated `add` and every activate test passed — a reminder
that a mutation check needs its own anchor, not just a plausible-looking pattern.

**Conscious no-ops.**
- *Drifted frontmatter slug drives the branch and commit subject* (CONFIRMED, narrow).
  A plan whose hand-edited `slug:` disagrees with its directory activates cleanly and
  commits a subject naming the wrong slug. Reaching it needs the hand-edit this plan's
  own Notes accept as always possible, `planners validate` flags it, and the shipped
  hook would usually reject the commit. Calling `validate()` on the `from_file` path is
  a decision about every command, not this one — it belongs in its own plan.
- *Extract the shared refresh/add/commit tail* (PLAUSIBLE). Real for `add` and
  `activate`, but the third site the finder named, `finalize`, genuinely differs
  (unconditional refresh, a looped path list, singular/plural subjects, a self-check).
  A helper spanning all three would be a leaky abstraction; a two-site helper is not
  worth the indirection.
- *No test pinning update.md's table row to its prose section* (PLAUSIBLE). The two
  agree today, and `tests/test_conventions.py` shows the repo has precedent for
  grep-based doc guards — but writing one is its own piece of work, not a fix to this
  diff.
- Rejected by verification and not actioned: `_DRAFT_PLAN`/git-helper duplication across
  the two test modules (the repo already defines per-module helpers by convention, both
  modules having their own `_init_git` before this PR); the untested `except PlanError`
  branch (untested repo-wide, not introduced here); `test_cli.py`'s `_init_git` lacking
  `--initial-branch` (the autouse `_isolate_git_env` fixture makes it deterministically
  `master`, which `base.py` recognizes, so the guard genuinely passes rather than going
  inert); the multi-letter-`sub` boundary (`validate()` forbids it and `next_sub` never
  emits one); and the missing-plans-directory path (`_plan_files` already returns `[]`,
  covered elsewhere).

## Retrospective

- **The plan's premise held and its scope was right.** All six steps landed as written,
  both open decisions resolved the way the plan leaned, and nothing forced a redesign.
  Keeping it to activation — rather than a general `planners status <NNN> <state>` — is
  what made that possible: `log` and `close` legitimately commit on the feature branch,
  so a general command would have needed per-transition guard policy and a much larger
  surface for the same benefit.
- **Idempotence is a claim about the world, not about a record.** The one real bug came
  from deciding "nothing to do" from the plan's frontmatter when the thing being
  asserted was about git. `status: active` proves an earlier run *wrote*; it says
  nothing about whether that run *committed*. Any future short-circuit in this package
  should ask the same question: is the state I am reading the state I am promising?
- **A command replacing prose has to be named everywhere the prose was.** The plan
  budgeted a whole step for collapsing the docs and still missed the README — including
  the one sentence there that this PR's rule-file edit was specifically fixing
  elsewhere. The rule, `implement.md`, and `update.md` were updated because the plan
  named them; the README was not on the list, so it was not checked. A "collapse the
  prose" step should start from a grep for the claim, not from a list of files.
- **Mutation-checking earned its keep twice.** Once as intended — five new tests, five
  isolated failures — and once by accident: the first attempt at one mutation silently
  patched `add`'s byte-identical `if no_commit: return` tail instead of `activate`'s,
  and every activate test passed. A mutation that changes nothing looks exactly like a
  test suite that caught nothing. Assert the anchor is unique before trusting a green
  or red result.
- **Two of the six review fixes were things this plan explicitly set out to do.**
  Step 1 added `PlanMetadata.prefix` *to avoid duplicating* the id format, then left
  `index.py`'s `_num` in place; the closed-status check invented a third status set
  beside two that already existed. Both are the same miss — implementing a step without
  first grepping for what already does that job. Worth doing before writing the helper,
  not after the review asks.
