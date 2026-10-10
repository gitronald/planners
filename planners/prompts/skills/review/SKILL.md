---
name: review
description: Review plans against the repo — find drafts that are done, half done, or moot, give each a verdict and a dated Log entry, and propose retirements.
metadata:
  version: "1.0.0"
---

# review — check plans against the repo

Plans go stale without anyone deciding they should. A draft may already be done
by a later plan, be half done as a side effect, rest on files that no longer
exist, or still be open with a different scope than the one it describes. This
skill finds out which, plan by plan, and records it.

`{cli} review` gathers the evidence and never writes. You read the evidence,
check each plan's claims against the code itself, give each plan a verdict, and
write a dated Log entry. The only commit is `{cli} review --commit`, and the
only status changes are retirements the user confirms.

## Steps

### 1. Gather the evidence

```bash
{cli} review --json                 # open plans: active, implemented, draft, blocked
{cli} review --json -s done -s retired   # closed plans, for drift
{cli} review --json -s all
{cli} review --json 011             # one plan, whatever its status
```

`--stale-days N` (default 14) sets when an active, implemented, or blocked plan's branch
counts as idle. A repo on the legacy `docs/plans/` + `TODO.md` layout is
refused; it needs migrating to `.planners/` first.

The report holds:

- `now`: the command's own timestamp. **Stamp every Log entry with it**, or
  with a fresh `date -Iseconds`. Never type a timestamp from memory.
- `summary`: one row per status (plans, commits that touched those plans,
  earliest `created`, latest `concluded`, newest commit date) and a `total`.
  It covers every status whatever was selected, so show it to the user first:
  it says what the review left out. `open_subplans` names each umbrella with
  an open subplan, which its own status hides.
- `plans`: per plan, the evidence window (`window_start`: the last review
  marker, else `created`), the commits in it that reach past `.planners/`
  (tool-written `plan [...]` and `version [...]` commits left out), the tags
  in it, each backticked path or `module.function` the plan names with
  `present`, `missing`, or `unresolved` and the commits that changed it, the
  other plans it names with their status, its nested subplans, and `flags`.
  An active, implemented, or blocked plan also carries `branch_state` (local, origin,
  commits ahead, last commit, worktree, dirty) and `pr_state`.

A field that is `null` is unknown (no `gh`, no remote, a shallow clone), not
false. Say so where it matters rather than reading it as absence.

### 2. Check each plan against the code

The report is where to look, not the verdict. For each plan:

- Read the plan's spec and the commits in its window. Open the ones whose
  subjects or paths touch what the plan describes.
- For every `missing` reference, find out why: deleted, renamed (`git log
  --follow --diff-filter=R`), or never written because the plan proposes it.
  A path the plan says it will create is expected to be missing.
- For every `present` reference that `changed`, read the change.
  `unresolved` references are often not code at all; check by hand only those
  that look like code.
- Grep for the functions, flags, and files the plan proposes. Read them where
  they exist. Run the tests or coverage the plan mentions when the verdict
  turns on them.
- Check the plans it names: one that is `done` may have absorbed this work.

### 3. Give each plan a verdict

| Verdict | Meaning | Default action |
|---|---|---|
| still open | nothing material has changed | log only |
| narrowed | partly done elsewhere | log the remaining scope |
| accounted for | done by other work | propose `{cli} retire <NNN> --into <MMM>` |
| moot | its premise no longer holds | propose `{cli} retire <NNN> --note "..."` |
| unclear | evidence conflicts | log the question, no status change |

**Active, implemented, and blocked plans get care.** Someone may be working on them right
now, in another session, a worktree, or a branch that is not pushed.

- Never edit an active, implemented, or blocked plan's file, on any branch, and never touch
  its branch or worktree. Write its entry as a suggestion in your report, for
  the owner to paste where the work lives.
- Judge from the branch, not the mainline: the report's references for these
  plans are already checked at the branch tip. Uncommitted work in a worktree
  means "in progress", not "missing".
- "accounted for" and "moot" are not available. The strongest finding is
  "possibly overlaps with <commit or plan>, confirm with the owner", phrased
  as a question.
- Flags (idle branch, missing branch, no branch, merged PR on an active plan)
  are observations. Report them; never act on them.

**Closed plans (`done`, `retired`)** are checked for drift only: the
deliverable still exists and was not later reverted, `pr` points at a merged
PR, and the plan a retired one moved to exists. Findings are Log entries. A
review never reopens a closed plan.

### 4. Write the Log entries

Every reviewed plan that is not active, implemented, or blocked gets one entry, appended to
its `## Log` (create the section before `## Handoff` or `## Retrospective` if
absent). It opens with the fixed marker, which the next review reads as the
start of its window:

```markdown
- **<now>** — Review: <verdict>. <what changed since created or the last
  review, and the evidence: commit SHAs, function names, test counts>
```

The verdict is one of the five above, lowercase, followed by a period. For a
narrowed plan, the entry states the remaining scope. Never edit the plan's
`## Plan` section or its frontmatter: the scope change lives in the Log.

### 5. Present, then commit

Show the user one table: plan, status, verdict, and the proposed action. Then
show the suggested entries for active, implemented, and blocked plans, which you did not
write. Wait for the user before committing.

```bash
{cli} review --commit
```

It commits only plan files whose `## Log` changed, as `plan [review]: <N>
plans`, with a refreshed index, on the mainline (it refuses elsewhere;
`--allow-branch` overrides). It refuses the whole commit when one of those
files changed outside its Log or is an active, implemented, or blocked plan, so revert the
stray edit rather than forcing it.

Then retire only the plans the user confirms, one `{cli} retire` each, which
commits separately:

```bash
{cli} retire 007 --into 012
{cli} retire 009 --note "The importer it extends was removed."
```

A review never activates, closes, or reopens a plan.

## Large runs

For more than about ten plans, check them in batches. Each batch may go to a
subagent on a smaller model, briefed with the report's entries for its plans
and steps 2 to 4, returning its verdicts and draft Log entries as its final
message. The subagents write no files. Merge their results into the one
verdict table; only the main loop writes Log entries and commits.
