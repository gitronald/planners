---
name: index
description: Regenerate the plan index — fully regenerate .planners/README.md from plan frontmatter.
metadata:
  version: "1.0.0"
---

# index — regenerate the plans table

Fully regenerate the repo's `.planners/README.md` from every plan's
frontmatter: a `# Plans` title followed by the table. This is a complete
regeneration, not a splice. There is no curated content to preserve, and the
file is overwritten wholesale (GitHub auto-renders it when the `.planners/`
folder is browsed). This package has **repo mode only**; there is no cross-repo
aggregate.

## Steps

### 1. Run the generator

```bash
# default: curated 5-column set (#, Plan, Status, Concluded, PR)
{cli} index .

# wide column set (adds Branch + Created)
{cli} index . --cols all
```

Pass a different path in place of `.` to target another repo root. Rows sort by
status (`active, implemented, blocked, draft, done, inactive, retired`), then by
concluded datetime, PR number, and plan number, each descending. A plan with no
concluded datetime or no PR sorts after one that has it. Empty cells render as
an em-dash.

### 2. Verify

Show `git diff .planners/README.md` so the change is reviewable, then commit
`.planners/README.md`.

## After a merge

The index is marked `merge=union` in `.gitattributes` (written by
`{cli} install`), so a **local** merge whose two branches both touched it
resolves instead of conflicting. When both branches rewrote the *same* row,
though, union keeps both, leaving that plan listed twice. The `post-merge` hook
`install` wires (`planners-index`) runs the generator after a clean merge, but
git writes the merge tree before the hook runs, so the repaired index lands as
an **uncommitted change**: commit it alongside. `{cli} validate` fails on an
index that disagrees with the frontmatter, so a missed repair surfaces on the
next plan commit rather than going unnoticed.

Two gaps look like the hook having done its job:

- **A conflicted merge does not run `post-merge`.** Git skips it when the merge
  stops on conflicts, and finishing by hand with `git commit` runs the
  *pre-commit* hooks instead. Run the generator yourself before committing a
  merge you resolved.
- **GitHub's server-side merge applies neither the attribute nor the hook**, so
  a PR whose two sides both touched the index still reports a conflict there.
  Resolve it by merging the base branch in locally, where the attribute does
  apply, then regenerate and push, rather than hand-editing the generated file
  in the web editor.
