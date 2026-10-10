---
name: add
description: Scaffold a new plan file. Use when the user wants to plan, spec out, propose, draft, or outline new work.
metadata:
  version: "1.0.0"
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
- Pass `--parent <N> --nested` to scaffold a **nested subplan** of umbrella `N`
  (see *Nested subplans* below) instead of a top-level plan.

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

## Nested subplans

**A plan is not split until it needs it.** Most plans are one file and stay that
way. Split when a plan would cross ~500 lines, or when the user asks, and not
before. A short plan with a few ordered steps keeps them as a list. Splitting an
existing plan is a proposal: surface it and confirm first.

**Subplans are nested.** Any request for subplans gets this shape, whatever
words it uses:

```
.planners/plans/NNN-<slug>/
  plan.md                  # umbrella: goal, decisions, order, risks, out of scope
  subplans/
    a-<step>.md            # one file per step or workstream
    b-<step>.md
```

```bash
{cli} add <step-slug> --parent <N> --nested --title "<Step title>"
```

This writes `subplans/<letter>-<step-slug>.md` inside the umbrella's directory,
with a frontmatter of `status: draft` and `branch:` and a back-link to the
umbrella, and adds the subplan's row to the umbrella's table. The umbrella must
already exist. Always pass `--nested`: `--parent` without it makes a lettered
sibling plan (see below).

The first nested `add` **writes the table itself**, under a `### Subplans`
heading of its own, after the first subsection of the umbrella's `## Plan`
section (the opening summary), or at the top of it when there are no
subsections yet. Do not write a heading or a table for it beforehand, or the
umbrella ends up with two. To place the table somewhere else, put the two
marker comments there first, with nothing between them, and the command fills
them in.

- **Letters are fixed once assigned**, as plan numbers are. The command takes
  the next free letter from `b`. `a` is reserved for the investigation from the
  first split, whether or not one is written yet: `--letter a` makes it. Making
  room for it later would shift every letter, rewrite every cross-link, and
  leave earlier Log entries naming files by letters they no longer have.
- **The commit follows the umbrella.** Under an umbrella that is not yet
  `active` the commit belongs on the mainline, and the same guard as a plain
  `add` applies. Under an `active` one it lands on the current branch, where the
  work is. `--no-commit` writes the files only.
- **`--defer` does not apply.** A nested subplan takes a letter from its
  umbrella, not a number from `finalize`. Add nested subplans one at a time.

### What goes where

- **The umbrella holds decisions, not findings.** It keeps the goal, the
  numbered decisions, the order, the risks, and what is out of scope. The
  inventory, the research, and the measurements behind them belong to the
  investigation subplan. An umbrella that keeps the whole design is still too
  long after the split and has to be split again.
- **The umbrella's table is generated.** It sits between two marker comments,
  and its Status column is written from the subplan frontmatter, which is the
  status of record. The Scope and Note columns are hand-written: the command
  seeds Scope with the title and leaves both alone afterwards. The Status column
  holds only the enum, and anything else ("waiting on review") goes in Note.

  ```markdown
  <!-- planners:subplans:start -->
  | Subplan | Scope | Status | Note |
  |---|---|---|---|
  | [a](subplans/a-investigate.md) | What exists today | done | |
  | [b](subplans/b-build.md) | The work itself | active | |
  <!-- planners:subplans:end -->
  ```

- **The execution order is a one-line dependency chain** in the umbrella, e.g.
  `a -> (b, c, d) -> e`. To make it data, give each subplan an optional `needs:`
  list of the letters it depends on. It is added by hand, as a line in the
  subplan's frontmatter after `branch:` (`needs: [a]`); `add` has no flag for
  it. `{cli} subplans <N>` prints the chain those lists describe and fails on a
  cycle. A retired subplan is left out of the chain, since it is not run.
- **A subplan is one node in the order.** An order that needs part of one
  subplan before another and the rest after it, e.g. `c (1-2) -> b -> c (3)`,
  is a sign that `c` is two subplans. Splitting by workstream reads well and
  orders badly; when the two disagree, split by order.
- **An empty `branch` means the umbrella's branch.** One PR for the effort does
  not mean every step lands through it. A step that lands in another repo
  records that branch, and the PR URL in an optional `pr`. Parallel steps that
  commit for themselves each get a sub-branch off the umbrella's branch.
- **Each file has its own length guidance.** ~500 lines applies to the umbrella
  and to every subplan, each on its own.

A suggested arc for the steps, as a starting point: investigate or spike, the
work itself in one or more steps, review, then documentation. An investigation
first tends to pay for itself, because its findings change the steps after it.

### Splitting a plan that already exists

1. Scaffold each subplan with `{cli} add ... --parent <N> --nested --no-commit`.
2. Move the sections to `subplans/` **verbatim**. Raise the headings to fit
   their new file, repoint the relative links, and condense or drop nothing on
   the way.
3. Diff the moved text against the original. This is how a dropped instruction
   gets caught.
4. Record the split, and what moved where, in the umbrella's Log.
5. Commit the split in the session that made it. Do not leave it staged for the
   next one.

### A subplan's Log entry

A subplan's Log entry is dated like any other: `- **{timestamp}** — ...`, with
a real timestamp from `date -Iseconds`. These headings go inside the entry. They
are a suggestion, not a schema. Each has earned its place by being the thing a
later session went looking for:

| Heading | Holds |
|---|---|
| What was done | the work, with its commits |
| Departures from the spec | the spec is left as written; each departure and its reason go here |
| Surprises | defects and discoveries outside the step's scope |
| Dead ends | approaches that failed, so they are not tried again |
| Deferred | work passed to a later subplan, named by letter, and repeated in the umbrella's Log |
| Gaps | what the step was meant to cover and did not |
| Not verified | what was not run, not compared, or not looked at |

### Lettered sibling plans, on request

| Shape | Use when |
|---|---|
| nested subplans | the default whenever a plan is split. One PR into the mainline carries the whole effort |
| `NNN<letter>` subplans | on request only: each step has its own branch, PR, and lifecycle |

Make lettered sibling plans only when the request describes them. Building the
lettered shape by mistake means folding it back by hand.

```bash
{cli} add <step-slug> --parent <N> --title "<Step title>"
```

This writes a sibling directory `.planners/plans/{NNN}<letter>-<step-slug>/`
(e.g. `010a-…`, then `010b-…`) that **shares the umbrella's number** and adds the
next free letter, with `id: {NNN}` and `sub: <letter>` in its frontmatter. Each
is a normal plan with its own frontmatter, lifecycle, and row in the index.
The index sorts by status first, so the umbrella and its lettered subplans sit
together only while they share a status. The umbrella stays `active` until
every subplan is done.

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
  notes the duplicate. `--defer` is for top-level plans only (not `--parent`,
  nested or lettered).
