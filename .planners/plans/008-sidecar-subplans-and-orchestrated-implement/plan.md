---
id: 8
slug: sidecar-subplans-and-orchestrated-implement
status: draft
branch:
created: 2026-09-27T00:14:23-07:00
concluded:
pr:
---

# Support sidecar subplans and an orchestrated implement run

## Plan

### Goal

Two ways of working already succeed with `planners` but are documented nowhere, so each session
has to rediscover them:

1. **Sidecar subplans.** A plan split into files under its own directory, rather than into
   numbered `NNN<letter>` sibling plans.
2. **An orchestrated implement run.** One `implement` of the umbrella that works through the
   subplans in dependency order, fanning independent ones out to subagents.

This plan documents both as supported shapes, and gives them the small amount of tooling that
keeps them honest.

### The sidecar shape

```
.planners/plans/NNN-<slug>/
  plan.md                  # umbrella: goal, decisions, order, risks, out of scope
  subplans/
    a-<step>.md            # one file per step or workstream
    b-<step>.md
```

- The umbrella keeps everything the pieces share, a subplan table (scope, step, status), and
  the execution order as a one-line dependency chain, e.g. `a -> b -> d (1-2) -> c -> e`.
- Each sidecar has its own `## Log`, and a minimal frontmatter of `status` and `branch`.
- Sidecars carry no `id` or `sub`, so they stay out of the index and out of `validate`. The
  umbrella's table is the status of record.

When to pick which, for the rule and the `add` skill:

| Shape | Use when |
|---|---|
| `NNN<letter>` subplans | each step has its own branch, PR, and lifecycle |
| sidecar subplans | one branch and one PR carry the whole effort, and the split is for length and focus |

### The orchestrated implement run

Guidance for the `implement` and `pipeline` skills, used only when the user asks for subagents
or a workflow:

- **Scout first, then fan out.** The orchestrator reads the umbrella and every subplan, then
  groups the subplans into phases from the execution order. Subplans with no dependency between
  them run in parallel; each phase's results are read before the next is launched.
- **One writer for git.** Subagents never stage, commit, push, or switch branches. The
  orchestrator commits each agent's output as its own logical chunk.
- **Disjoint file ownership.** Every agent's brief names the paths it may touch. Work that
  would overlap is sequenced, or the orchestrator stages it outside the tree and places it
  once the owning agent has finished.
- **Spikes stay in scratch.** An investigative step writes nothing to the repo; its findings
  come back through the agent's report and land in the subplan's Log.
- **Questions are held.** Open questions are collected as the run goes and asked together at
  the end. A step that needs a human (a ruling, a manual test, an external setting) is marked
  blocked in the table and the run carries on with whatever does not depend on it.
- **Truthful status.** A subplan is marked done only when its checks ran and passed. "Not run"
  and "not verified" are recorded in those words.

### Tooling

| Item | Change |
|---|---|
| `planners subplans <NNN>` | List a plan's sidecars with their `status` and `branch`, and exit non-zero when the umbrella's table disagrees with the sidecar frontmatter |
| `validate` | Opt-in check of sidecar frontmatter (`status` in the shipped enum). Off by default, so existing plans with free-form sidecars keep passing |
| `add --sidecar <letter>-<slug> --plan <NNN>` | Scaffold a sidecar with its frontmatter and a back-link to the umbrella |
| Execution order | An optional `needs:` list in sidecar frontmatter, so the dependency chain is data the orchestrator reads, not prose it interprets |
| Blocked state | A way to mark a sidecar as waiting on a person, distinct from `draft` and `inactive`. Decide between a new status and a `blocked:` note field |

### Related improvements

Found while running the shapes above. Each is small and independent of the rest.

- **`implement` assumes the base is checked out in the main checkout.** When the base branch
  lives in a worktree of its own, step 2 should say to find it with `git worktree list` and
  run `activate` there, and step 4 should resolve `.worktrees/` against the main repo root,
  not the current directory.
- **Recording the PR is three hand steps.** Editing `pr:`, refreshing the index, and
  committing is the same shape `activate` already automates. Add `planners set-pr <NNN> <url>`,
  or an equivalent, so the index cannot be forgotten.
- **Worktree setup is per-repo knowledge.** `implement` creates the worktree and stops. A hook
  point, such as a documented `post-worktree` step the repo can define, would cover the
  environment sync and gitignored links a fresh worktree needs.
- **A plan-level "Open questions" section.** The rule names Plan, Log, and Retrospective. A
  held-questions list has no home, so it ends up in chat and is lost with the session.
- **Length guidance counts the umbrella only.** The ~500-line guidance should say whether
  sidecars count toward it, and suggest a per-sidecar ceiling.

### Implementation order

| Step | Work |
|---|---|
| 1 | Document the sidecar shape and the choice between shapes in the rule and the `add` skill |
| 2 | Add the orchestration guidance to the `implement` and `pipeline` skills |
| 3 | `planners subplans` and the opt-in `validate` check, with tests |
| 4 | `add --sidecar`, `needs:`, and the blocked state, once step 3 has settled the frontmatter |
| 5 | The related improvements, each as its own commit |

### Out of scope

- Converting existing `NNN<letter>` subplans to sidecars, or the reverse.
- Running subagents from the CLI. The CLI stays a plan-file tool; orchestration is guidance
  for the harness that drives it.
- Indexing sidecars in `.planners/README.md`.
