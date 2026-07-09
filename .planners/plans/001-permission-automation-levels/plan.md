---
id: 1
slug: permission-automation-levels
status: draft
branch: feature/permission-automation-levels
created: 2026-07-09T00:34:01-07:00
concluded:
pr:
---

# Add opt-in permission profiles so users choose the automation level

## Plan

### Problem

planners' skills read like self-contained recipes, but their unattended feel is
underwritten by permission grants the skills never declare. A close/implement run
fires ~15 distinct commands (`git worktree`, `git add`/`commit`/`push`, `gh pr
create`/`comment`/`ready`/`merge`, `planners`, the `uv run` check gate), and
whether each runs silently depends entirely on the ambient permission config of
the machine it happens to run on.

A scan of local consumer repos makes the gap concrete:

- The **commit-driven spine** is broadly pre-authorized — `git add`, `git
  commit`, `uv run:*`, and `uv sync` are allowed in most repos that carry
  settings. planners' state machine (a commit per transition) rides on these.
- planners' **distinctive remote-write verbs are pre-authorized almost nowhere**:
  `gh pr comment`, `gh pr ready`, and `git worktree` were allowed in **0** of the
  scanned repos, and the `planners` CLI itself in **0** (in local mode it is
  covered incidentally by `uv run:*`; in global mode, invoked bare, it is not).
- `git push` is deliberately **`ask`-gated** in several repos, and `gh pr merge`
  is allowed in only a minority — i.e. these are *considered per-repo policy*,
  not oversights.

So planners' automation depends on undeclared grants, it is not portable (the
same skills stall at different commands on a stricter machine), and there is no
first-class way for a user to say "give me more (or less) hands-off automation."
[[close-gate-pr-comment-permission]] fixed one instance (a blocked `gh pr
comment`) by degrading gracefully; this plan generalizes the response.

### Goal

Let a user **choose their automation level** through an opt-in, mode-aware
permission profile that planners can print or apply. Higher levels pre-authorize
more of the lifecycle (fewer prompts); lower levels lean on the session mode,
the classifier, and graceful degradation (more portable, more prompts). The
default is the safe, reversible-only, local profile — never a silent grant of
irreversible or policy-sensitive commands.

### Automation levels

Each level is a named profile mapping to *how far through the lifecycle runs
without a prompt*. Each level is a superset of the one above it.

| Level | Name | Pre-authorizes | Lifecycle effect |
|---|---|---|---|
| 0 | `none` | nothing | every remote write prompts; fully portable, relies on 000-style degradation |
| 1 | `assist` **(default)** | `git worktree`, `gh pr comment`, `gh pr ready` | worktree setup and the review-gate publish just work; push and merge still confirmed |
| 2 | `unattended-push` | + `git add`, `git commit`, `git push`, `uv run`, `uv sync` | implement → pushed draft PR, and close up to merge, run unprompted |
| 3 | `unattended-merge` | + `gh pr merge` | full close including the irreversible merge runs unprompted |

- Level 1 grants only **reversible, self-authored** verbs (a comment can be
  deleted, a PR re-drafted, a worktree removed) — the plan-000 class of friction
  — without touching anything irreversible or policy-sensitive.
- `gh pr merge` is isolated at the **top level only**. planners' own `close`
  skill says merge should stay behind the classifier, so granting it must be an
  explicit, clearly-labeled choice, never reachable by default.
- `git push` first appears at level 2; because several repos `ask`-gate it on
  purpose, the writer must be additive and must not downgrade that (see
  guardrails).

### Mechanism

A dedicated, opt-in command — `planners permissions [--level <name>]` — reusing
`install`'s existing global/local **mode** machinery:

- **local by default** — writes the repo's `.claude/settings.local.json`;
  `--global` targets `~/.claude/settings.json`. Permissions are a per-repo policy
  in practice, so a repo-scoped default matches how users already manage them and
  keeps a broad grant from leaking across every repo.
- **mode-aware rule sets** — the emitted rules depend on mode. Global mode emits
  `Bash(planners:*)`; local mode relies on the already-common `Bash(uv run:*)`
  (or emits `Bash(uv run planners:*)`) since the CLI is invoked as `uv run
  planners` there.
- **print or apply** — `--print` (default, or `--dry-run`) emits the rule block
  for the user to paste into a settings template or apply via `/update-config`;
  applying writes it after showing the diff. Printing lets planners *declare* its
  needs without seizing ownership of `settings.json`.
- **additive and deferential** — merge into existing `permissions`, never
  removing or weakening a rule already present. If a command is already on `deny`
  or `ask`, leave it and report the skip; do not promote it to `allow`. This is
  what protects a deliberate `ask`-gate on `git push`.

### Relationship to plan 000

Complementary, not overlapping:

- **000 = degrade, don't stall** — the lifecycle works with *zero* grants (the
  `none` level is viable end to end). Extend 000's degradation from `gh pr
  comment` to its twin **`gh pr ready`** (same gate, same blocked-self-authored-
  write failure), so level 0 does not dead-end at a draft PR. Fold that into 000.
- **001 = profiles** — an opt-in way to trade portability for fewer prompts.

Also reconcile 000's claim that "merge stays behind the classifier regardless"
with the reality that some repos already `allow` merge: soften it to *advisory*
(the recommended default, overridable by the `unattended-merge` level), rather
than an absolute.

### Guardrails / non-goals

- **Never folded into default `install`.** Granting classifier-bypassing rules
  must be a separate, explicit action. `planners install` keeps writing only
  advisory artifacts and the pre-commit hook.
- **No `deny`/`ask` safety-rail seeding.** Offering a general safety baseline
  (force-push, `rm -rf`, `git reset --hard`) is a settings-template concern, not
  planners'. Out of scope; `/update-config` owns that.
- **Respect existing policy.** The writer only ever adds; a user's stricter rule
  always wins.

### Implementation order

1. Define the level → rule-set mapping as data, parameterized by mode (the
   level table above, mode-aware for the `planners`/`uv run` split).
2. Add the `planners permissions` command: `--level` (default `assist`),
   `--global`/local, `--print` default with an apply path.
3. Implement additive merge into `settings.local.json`/`settings.json` that
   never downgrades an existing `deny`/`ask`; report skips.
4. Document it: a short note in the packaged rule summary and in the
   `close`/`implement` skills (point at `planners permissions`, mirroring how 000
   points at `/update-config`).
5. Tests: the rule set per (level, mode); additive merge preserves existing
   `deny`/`ask`; `--print` output is stable; `gh pr merge` never appears below
   `unattended-merge`.

### Open questions

- Level names (`none`/`assist`/`unattended-push`/`unattended-merge`) vs numeric
  `--level 0..3`, or both.
- Whether `git push` should be its own opt-in within a level rather than bundled
  into level 2, given the deliberate `ask`-gating seen in the wild.
- Whether `--print` should emit a paste-ready JSON fragment, a `/update-config`
  invocation, or both.
