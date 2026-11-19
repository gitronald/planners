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
# the column set the index is already in; curated for a new one
# (#, Plan, Status, Concluded, PR)
{cli} index .

# wide column set (adds Branch + Created)
{cli} index . --cols all

# back to the curated set
{cli} index . --cols curated
```

The lifecycle commands and the `post-merge` hook refresh the index in the set
it is in, so an index made wide stays wide until `--cols curated` narrows it.

Pass a different path in place of `.` to target another repo root. Rows sort by
status (`active, implemented, blocked, draft, done, inactive, retired`), then by
concluded datetime, PR number, and plan number, each descending. A plan with no
concluded datetime or no PR sorts after one that has it. Empty cells render as
an em-dash.

In a repo with no `.planners/plans/` directory the generator writes nothing and
prints `no .planners/plans/; nothing to index`, so the `post-merge` hook leaves
a repo that has no plans yet clean. `{cli} add` writes the index along with the
first plan.

### 2. Verify

Show `git diff .planners/README.md` so the change is reviewable, then commit
`.planners/README.md`.

## After a merge

The index is marked `merge=union` in `.gitattributes` (written by
`{cli} install`), so a **local** merge whose two branches both touched it
resolves instead of conflicting. When both branches rewrote the *same* row,
though, union keeps both, leaving that plan listed twice. The `post-merge` hook
`install` wires (`planners-index`) runs the generator after a clean merge
(`{cli} index . --after-merge`). Git writes the merge commit before the hook
runs, so the hook puts the repair **into that commit**: same parents, message,
and author, with the regenerated index. There is nothing to commit by hand, and
the tree is clean when the merge returns.

The hook leaves the repair as an **uncommitted change**, and prints why, when
rewriting the commit would be wrong: the merge was a fast-forward or a squash
(there is no merge commit of its own to put it in, whatever HEAD is), a remote
branch already holds the commit, the commit is signed or merges a signed tag,
the commit does not track the index, or another operation is in progress. Run
by hand, outside the hook, the command also leaves it. Then add the index
to the next commit you make. Do not make a commit that holds only the index.
`{cli} validate` fails on an index that disagrees with the frontmatter, so a
missed repair surfaces on the next plan commit rather than going unnoticed.

A config written by an earlier release runs the hook without `--after-merge`.
`{cli} install --check` reports that entry as `outdated`, and `{cli} install`
rewrites it.

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
