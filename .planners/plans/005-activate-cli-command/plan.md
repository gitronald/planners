---
id: 5
slug: activate-cli-command
status: draft
branch:
created: 2026-09-08T13:44:58-07:00
concluded:
pr:
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
