---
id: 23
slug: index-branch-link
status: draft
branch:
created: 2026-11-12T13:28:43-08:00
concluded:
pr:
---

# Link each open plan's feature-branch copy from the index

## Plan

### Goal

While a plan is open, its live copy is on its feature branch: the Log entries,
the Handoff, and the status changes land there, and the mainline's copy goes
stale until the merge. The generated index (`.planners/README.md`) links only
the mainline copy. Give each open plan a second link, to the plan file on its
feature branch on GitHub, so the mainline index reaches the live copy in one
click.

### Background

- The `Activated.` Log entry records the worktree as a text path
  (`Worktree: .worktrees/<slug>`), with no link. That stays as it is.
- An earlier attempt, never committed, added a `WorktreePlan` line to that entry: a
  relative Markdown link into the worktree. No relative link resolves both
  from the main checkout and from inside the worktree, since the worktree's
  copy of the file sits two levels deeper. `.worktrees/` is gitignored, so the
  link was dead on GitHub from the start and dead locally once `finish`
  removed the worktree, and it stayed in the plan's Log for good. This plan
  replaces that attempt.
- A link to the index instead of the Log entry fixes the permanence: the
  index is regenerated on every lifecycle change, so the link goes away when the
  plan closes. A GitHub URL instead of a relative path fixes the resolution:
  it is the same from every checkout, the worktree, GitHub, and another
  host's clone.

### Decisions

1. **The link is a GitHub blob URL on the plan's branch.**
   `https://github.com/<owner>/<repo>/blob/<branch>/.planners/plans/<dir>/plan.md`,
   where `<branch>` is the frontmatter `branch` and `<dir>` the plan's
   directory. It opens the pushed state in a browser, not the local file: an
   unpushed edit is not shown. A local worktree link was considered and set
   aside; it works only from the main checkout.
2. **It sits in the Plan cell, after the title link**, which stays the
   mainline link and keeps working everywhere:
   `[Title](plans/031-x/plan.md) · [branch](https://github.com/owner/repo/blob/feature/x/.planners/plans/031-x/plan.md)`.
   The same in the `all` column set.
3. **Only open plans with a branch get one**: status `active`, `implemented`,
   or `blocked`, with a non-empty `branch`. A `draft` with a `branch` recorded
   as intent (`add --branch`) gets none, since the branch does not exist yet.
   `done`, `retired`, and `inactive` get none: the branch is merged or gone.
4. **The inputs are frontmatter and `origin`, nothing on disk.** No worktree
   lookup and no Log parsing, so the index is the same on every host and in
   CI, which `validate`'s index comparison needs.
5. **`owner/repo` comes from `origin`'s URL**, with the SSH (`git@github.com:`),
   `ssh://`, and `https://` forms normalized to one slug and a trailing
   `.git` dropped. `planners/remote.py` already parses the host
   (`url_host`) and resolves SSH config aliases; the slug parse goes beside
   it. Only a remote whose kind is `github` (`planners remote`) gets links. A
   repo with no `origin`, or one on another host, gets none, and its index is
   unchanged from today.

### Risks

- **Index drift between environments.** If one checkout can read `origin` and
  another cannot (an export with no remote, a CI job that rewrites the
  remote), the two generate different indexes and `validate` fails in one of
  them. `actions/checkout` sets `origin` to `https://github.com/<owner>/<repo>`,
  which normalizes to the same slug as a local SSH remote. Check the case
  where the remote kind is set by the committed override in place of the URL,
  and decide whether a committed slug should go with it.
- **A fork's clone** has `origin` on the fork, so its links point there. That is
  where its branches are, so it is right for the fork; note it in the docs.
- **The short 404.** `activate` commits the index before `start` pushes the
  branch, so the link is a 404 until the push. Acceptable; no fix planned.
- **Branch names with characters URLs reserve.** Branch names are usually
  `feature/<slug>`, which needs no escaping, but percent-encode anything outside
  the URL-safe set while keeping the `/` separators.

### Out of scope

- A link in the `Activated.` Log entry, in any form.
- A local link to the worktree copy.
- Hosts other than GitHub.

### Implementation order

1. `remote.py`: a function that returns `owner/repo` for a GitHub `origin`, or
   `None`, with tests over the URL forms (SSH, `ssh://`, `https://`, with and
   without `.git`, a credential in the URL, an SSH config alias).
2. `index.py`: `_plan_cell` takes the slug and adds the branch link under
   decision 3; `render_plans_table` passes it through. The CLI's index builder
   reads the slug once per run. Tests: each status, an empty branch, no
   GitHub remote, both column sets, and a branch name that needs escaping.
3. `validate`: confirm the index comparison builds the slug the same way, and
   test a repo with no `origin` against a committed index that has no links.
4. Docs: the rule's storage-layout section (the index's Plan cell), the
   `index` skill, and the changelog.
5. Regenerate this repo's own index and check it in.
