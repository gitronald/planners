---
name: update
description: Update a plan's lifecycle state — activate, log, or transition status. Maps "abandon" to retired.
metadata:
  version: "1.0.0"
---

# update — lifecycle transitions

Set a plan's `status` in frontmatter and refresh the index. There is no
checklist file to tick. Parse the plan number or path from the request, then
infer the action from the user's words or the plan's current state.

| Action | Triggers | Effect |
|--------|----------|--------|
| **activate** | "start", "activate", "begin" | `{cli} activate {NNN}` — on the mainline |
| **implemented** | "implemented", "ready for review", "work is done" | `{cli} implemented {NNN}` — on the feature branch |
| **reactivate** | "back to work", "more changes", "review asked for" | `{cli} activate {NNN}` on an `implemented` plan — on the feature branch |
| **log** | "log", "note", "update" | Append a dated entry to the `## Log` section |
| **close** | "close", "finish", "done", "complete" | Hand off to `/planners close` (review gate, merge, cleanup) |
| **block** | "block", "waiting on", "stuck on" | `status: blocked`; say what it waits on |
| **retire** | "abandon", "drop", "cancel", "retire", "supersede" | `{cli} retire {NNN}` |

An abandon, drop, or cancel request maps to `status: retired` (neutral terminal
closure) — there is no separate failed status.

## Steps

### 1. Find the plan

Glob `.planners/plans/{NNN}-*/plan.md`. Read its `# Title`, current frontmatter, and
whether a `## Log` section exists.

A reference with a letter that matches no plan directory (e.g. `012d`) names a
**nested subplan**, `subplans/d-*.md` inside umbrella `012`. Its status changes
go through `{cli} subplans`, not a hand edit:

```bash
{cli} subplans 012 --set d=active     # or blocked, done, ...
```

That changes the subplan's frontmatter, which is the status of record, and
regenerates the umbrella's table in the same step. Several `--set` options are
applied together or not at all, and a file with no frontmatter is refused
rather than given one. Its log entries go in the
subplan's own `## Log`. `retire`, `set-pr`, and `implemented` take the lettered
reference directly (`{cli} retire 012d --into 015`).

### 2. Apply the action

**Activate** — run `{cli} activate {NNN}` (`--branch <name>` to override the
derived `feature/<slug>`). It sets `status: active`, fills `branch` if empty,
appends the activation entry to the Log (branch, base and commit, worktree, PR;
`--worktree <path>` or `--no-worktree` when the work is not in
`.worktrees/<branch-suffix>`), refreshes the index, and commits
`plan [activate]: {NNN} - <slug>`. **It commits on
the mainline**, before the branch or worktree exists, and refuses if HEAD is
elsewhere — `{cli} base --all` prints the branches that qualify, so switch to one
first rather than reaching for `--allow-branch`. Do not hand-edit the frontmatter
for this; the CLI owns it. When `{cli} remote` says `single-branch`, do not
follow it with a routine `git push` of the base: that push publishes into the
live document, so show the ahead count and ask.

**Implemented** — once the work is finished, committed, and pushed, run
`{cli} implemented {NNN}` on the feature branch, then `git push`. It sets
`status: implemented`, appends `Implemented: <n> commits ahead of <base>` to the
Log, refreshes the index, commits `plan [implemented]: {NNN} - <slug>`, and
takes the PR out of draft. It refuses a plan that is not `active`, and a branch
with uncommitted or unpushed work, naming which, and runs only on the feature
branch, never the mainline. Off GitHub (`{cli} remote` is not `github`) a
branch with no upstream is not refused, since there is no PR to see it. It
closes nothing; that stays with `/planners close`.

**Reactivate** — when review asks for more work on an `implemented` plan, run
`{cli} activate {NNN}` on the feature branch. The return from `implemented` is
not guarded, and it logs a short `Reactivated` entry rather than a second
activation entry. A nested subplan returns with
`{cli} subplans {NNN} --set <letter>=active`.

**Log** — append under `## Log` (create it before `## Retrospective` or at the
end if absent), using a real timestamp from `date -Iseconds`:

```markdown
## Log

- **{timestamp}** — {note}
```

Commit `plan [log]: {NNN} - {brief summary}`.

**Block** — set `status: blocked` for work that is waiting on a person: a
decision, a manual check, access only they have. It is an open state, so
`concluded` stays empty.

- **A plan:** edit `status:` and run `{cli} index .`. Write what it waits on,
  and who, in the plan's `## Handoff` section. Commit
  `plan [block]: {NNN} - <slug>`. When the wait is over, `{cli} activate {NNN}`
  sets it back to `active`. It carries the mainline guard, as any activation of
  a blocked plan does, so run it on the mainline.
- **A nested subplan:** `{cli} subplans {NNN} --set <letter>=blocked`. Write
  what it waits on in the Note column of its row in the umbrella's table, by
  hand: the command writes the Status column and no other. When the wait is a
  question, put it in the umbrella's `## Handoff` as well. Commit
  `plan [block]: {NNN}<letter> - <step>`. When the wait is over,
  `--set <letter>=active` resumes it, and the Note is cleared by hand.
  `activate` does not take a nested subplan.

**Retire** — run `{cli} retire {NNN}`, with `--into <NNN>` when the work moved
to another plan and `--note "<sentence>"` for why. It sets `status: retired`,
fills `concluded` from the authored date of `HEAD`, writes `null` for a
`branch`/`pr` that was never filled, appends the Log entry, refreshes the index,
and commits `plan [retire]: {NNN} - <slug>`. Do not hand-edit the frontmatter
for this; the CLI owns it. The Log entry already says "Retired. The work moved
to plan NNN.", so `--note` carries the reason and does not repeat that. A nested
subplan keeps an empty `branch`, which for it means the umbrella's branch.

`--into` names a plan that exists **on the branch where `retire` runs**. A
follow-up plan made during the work is added on the mainline, as every plan is,
so from a feature branch it is not there yet. The order is:

1. Add the follow-up plan from the base's checkout (`{cli} add <slug>`).
2. Merge the base into the feature branch (`git merge --no-ff <base>`), from the
   feature branch's worktree.
3. Retire with `--into`, from that worktree. It refuses an umbrella that still has a `draft`,
`active`, `implemented`, or `blocked` nested subplan: finish each, or retire it first
(`{cli} retire {NNN}<letter>`).

**Handoff** — for an effort that spans sessions, keep a `## Handoff` section
between Log and Retrospective. It is **rewritten in place**, the one exception
to append-only, because it describes the present and the Log keeps the history.
It holds the state of each piece (including what is uncommitted or unpushed),
the open questions (numbered once, never renumbered, each answer and its date
beside its question), the questions settled or handed to another plan, what is
not verified, and the order of the remaining work with who each item waits on.

**Close** — defer to `/planners close`, which runs the review gate and merge.

### 3. Refresh the index

```bash
{cli} index .
```

Commit the regenerated `.planners/README.md` if the status change moved the row.
`activate`, `implemented`, `retire`, and `set-pr` refresh and commit the index themselves, so
this step is for the hand-written actions.
