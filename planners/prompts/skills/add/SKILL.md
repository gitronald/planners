---
name: add
description: Scaffold a new plan file. Use when the user wants to plan, spec out, propose, draft, or outline new work.
metadata:
  version: "1.0"
---

# add — scaffold a new plan

Create a schema-conformant plan in `.planners/plans/` — each plan is its own
directory (`.planners/plans/{NNN}-{slug}/plan.md`) so it can carry scoped
sidecar files. The `planners` CLI does all the mechanical work — next number,
timestamp, frontmatter, index refresh, and commit — so your only authored work
is the title and the `## Plan` body.

There is **no separate checklist file** and no number to track by hand: plan
state lives entirely in frontmatter, and the index is regenerated from it.

## Steps

### 1. Scaffold the file

Derive a kebab-case `<slug>` from the request, then run:

```bash
{cli} add <slug> --title "<Descriptive title>"
```

- Add `--branch <name>` to record an intended implementation branch (a record
  of intent only — `/planners implement` creates it later).
- This writes `.planners/plans/NNN-<slug>/plan.md` with `id`, `slug`,
  `status: draft`, and `created` filled in, regenerates the plans table in
  `.planners/README.md`, and commits both on the current branch
  (`plan [add]: NNN - <slug>`).
- **The commit must land on the mainline**, so the plan is recorded there even if
  a feature branch never merges. `add` refuses when HEAD is off it — `dev` when
  that branch exists, plus the repo's default branch; `{cli} base --all` prints
  the set. Switch to a mainline branch rather than reaching for the override.
  `--allow-branch` exists for a repo whose mainline genuinely is not detectable
  by name, not as a way past the refusal.
- Pass `--no-commit` to write the file only — no index refresh, no commit — when
  you want to author the `## Plan` body before committing, or are batching.
- Pass `--parent <N>` to scaffold a **subplan** of umbrella `N` (see *Umbrella +
  subplans* below) instead of a top-level plan.

Do not compute the next number, run `date`, or edit the index yourself; the CLI
handles all of it.

### 2. Fill in the plan body

Edit the scaffolded file:

- **Title** — a descriptive goal in **sentence case**, not Title Case (capitalize
  only the first word and proper nouns/identifiers); no "Plan:" prefix, no number.
  Bad: "Update", "Migrate Pandas To Polars". Good: "Migrate pandas to polars".
- **`## Plan`** — the implementation spec: scope, approach, key decisions, and
  an implementation order. Write enough that someone picking this up later
  understands it.

### 3. Commit the body (only if you used `--no-commit`)

```bash
{cli} index .
git add .planners/plans/NNN-<slug>/plan.md .planners/README.md && git commit -m "plan [add]: NNN - <slug>"
```

If you let `add` commit in step 1, edit-then-commit the body as a normal follow-up.

## Umbrella + subplans

When a plan is really one effort done in **steps in order** (or it would cross
~500 lines), keep the parent as an *umbrella* and split the steps into subplans:

```bash
{cli} add <step-slug> --parent <N> --title "<Step title>"
```

This writes a sibling directory `.planners/plans/{NNN}<letter>-<step-slug>/`
(e.g. `010a-…`, then `010b-…`) that **shares the umbrella's number** and adds the
next free letter, with `id: {NNN}` and `sub: <letter>` in its frontmatter. The
umbrella must already exist (create it first with a plain `{cli} add`).

Conventions, mirroring the global plan-files rule:

- The umbrella's `## Plan` is just a **subplan table** (`# | Subplan | Scope |
  Status`) plus the explicit **execution order** and a whole-effort *out of
  scope* — the real spec for each step lives in its subplan.
- Each subplan is a normal plan with its own frontmatter and lifecycle; cross-
  link the umbrella and siblings.
- The umbrella keeps its own metadata and stays `active` until every subplan is
  done; closing the last subplan closes the umbrella.

The generated `.planners/README.md` renders an umbrella and its subplans as one
contiguous block (umbrella first, then `a`, `b`, …). The canonical shape is an
umbrella `NNN` plus subplans `NNNa`–`NNNe`, each its own directory.

## Batch / deferred creation

When several plans are created **at once** (e.g. fanned out across parallel
agents), do **not** run parallel `{cli} add`s — they assign the number by scanning
the directory, so concurrent creators can race on the next `NNN` and the commit.
Use deferred numbering instead:

```bash
{cli} add <slug> --defer --title "<Title>"   # each creator, in parallel
{cli} finalize                               # once, after all creators finish
```

- `--defer` writes an **unnumbered** plan under `.planners/staging/<token>-<slug>/`
  with no number, no commit, and no shared state, so any number of creators run
  safely in parallel. Edit the staged `plan.md` body just like a normal plan.
- `{cli} finalize` is the **single serialized writer**: it orders the staged
  plans by `created`, assigns the next sequential numbers, materializes them under
  `plans/` (sidecar files included), refreshes the index, commits the batch in one
  commit (`plan [add]: NNN - <slug>` for one plan, else `plan [add]: NNN-MMM
  (N plans)`), and runs a self-check. Run it **once**, after every deferred creator
  has finished (the explicit "batch complete" signal). It commits, so the same
  mainline guard applies — run it from a mainline branch. A refused finalize
  leaves the batch staged and recoverable, nothing half-materialized.
- Two creators may pick the same slug; finalize keeps them distinct by number and
  notes the duplicate. `--defer` is for top-level plans only (not `--parent`).
