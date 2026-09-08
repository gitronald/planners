---
name: update
description: Update a plan's lifecycle state — activate, log, or transition status. Maps "abandon" to retired.
---

# update — lifecycle transitions

Set a plan's `status` in frontmatter and refresh the index. There is no
checklist file to tick. Parse the plan number or path from the request, then
infer the action from the user's words or the plan's current state.

| Action | Triggers | Effect |
|--------|----------|--------|
| **activate** | "start", "activate", "begin" | `status: active`; fill `branch`. Commit on the mainline |
| **log** | "log", "note", "update" | Append a dated entry to the `## Log` section |
| **close** | "close", "finish", "done", "complete" | Hand off to `/planners close` (review gate, merge, cleanup) |
| **retire** | "abandon", "drop", "cancel", "retire", "supersede" | `status: retired`; fill `concluded` |

An abandon, drop, or cancel request maps to `status: retired` (neutral terminal
closure) — there is no separate failed status.

## Steps

### 1. Find the plan

Glob `.planners/plans/{NNN}-*/plan.md`. Read its `# Title`, current frontmatter, and
whether a `## Log` section exists.

### 2. Apply the action

**Activate** — set `status: active` and fill `branch` if empty (the plan's
intended branch, or `feature/<slug>`). **Commit on the mainline**, before the
branch or worktree exists — `{cli} base --all` prints the branches that qualify.
The activation commit is a hand-written `git commit`, so no CLI guard covers it;
if `git branch --show-current` is not in that set, switch before committing or
the plan is recorded only on a branch that may never merge. Commit
`plan [activate]: {NNN} - {title lowercase}`.

**Log** — append under `## Log` (create it before `## Retrospective` or at the
end if absent), using a real timestamp from `date -Iseconds`:

```markdown
## Log

- **{timestamp}** — {note}
```

Commit `plan [log]: {NNN} - {brief summary}`.

**Retire** — set `status: retired`. Fill `concluded` with the ISO timestamp of
the deciding commit (`git log --format="%aI" -1`). Use explicit `null` for a
genuinely-absent `branch`/`pr`; never the string `none`. Commit
`plan [retire]: {NNN} - {title lowercase}`.

**Close** — defer to `/planners close`, which runs the review gate and merge.

### 3. Refresh the index

```bash
{cli} index .
```

Commit the regenerated `.planners/README.md` if the status change moved the row.
