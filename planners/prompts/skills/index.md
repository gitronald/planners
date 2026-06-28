---
name: index
description: Regenerate the plan index — fully regenerate .planners/README.md from plan frontmatter.
---

# index — regenerate the plans table

Fully regenerate the repo's `.planners/README.md` from every plan's
frontmatter: a `# Plans` title followed by the table. This is a complete
regeneration, not a splice — there is no curated content to preserve, and the
file is overwritten wholesale (GitHub auto-renders it when the `.planners/`
folder is browsed). This package has **repo mode only** — there is no cross-repo
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
status (`active, draft, done, inactive, retired`), then by concluded datetime,
PR, and plan number (descending); empty cells render as an em-dash.

### 2. Verify

Show `git diff .planners/README.md` so the change is reviewable, then commit
`.planners/README.md`.
