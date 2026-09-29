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
regenerates the umbrella's table in the same step. Its log entries go in the
subplan's own `## Log`. `retire` and `set-pr` take the lettered reference
directly (`{cli} retire 012d --into 015`).

### 2. Apply the action

**Activate** — run `{cli} activate {NNN}` (`--branch <name>` to override the
derived `feature/<slug>`). It sets `status: active`, fills `branch` if empty,
refreshes the index, and commits `plan [activate]: {NNN} - <slug>`. **It commits on
the mainline**, before the branch or worktree exists, and refuses if HEAD is
elsewhere — `{cli} base --all` prints the branches that qualify, so switch to one
first rather than reaching for `--allow-branch`. Do not hand-edit the frontmatter
for this; the CLI owns it.

**Log** — append under `## Log` (create it before `## Retrospective` or at the
end if absent), using a real timestamp from `date -Iseconds`:

```markdown
## Log

- **{timestamp}** — {note}
```

Commit `plan [log]: {NNN} - {brief summary}`.

**Block** — set `status: blocked` for work that is waiting on a person: a
decision, a manual check, access only they have. It is an open state, so
`concluded` stays empty. Write what it waits on, and who, in the plan's
`## Handoff` section. Commit `plan [block]: {NNN} - <slug>`. When the wait is
over, `{cli} activate {NNN}` sets it back to `active`.

**Retire** — run `{cli} retire {NNN}`, with `--into <NNN>` when the work moved
to another plan and `--note "<sentence>"` for why. It sets `status: retired`,
fills `concluded` from the authored date of `HEAD`, writes `null` for a
`branch`/`pr` that was never filled, appends the Log entry, refreshes the index,
and commits `plan [retire]: {NNN} - <slug>`. Do not hand-edit the frontmatter
for this; the CLI owns it.

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
`activate`, `retire`, and `set-pr` refresh and commit the index themselves, so
this step is for the hand-written actions.
