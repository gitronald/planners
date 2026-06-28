# planners

Own a repo's plan-file lifecycle through a documented schema, a CLI, and an installable skillstub.

`planners` is the single source of truth for the plan-file process in a repo: it defines plan
frontmatter as a `PlanMetadata` schema, validates it, regenerates the `.planners/README.md` plans
index, and installs a single `/planners` dispatcher, the plan-files convention rule
(`.claude/rules/planners.md`), and a pre-commit validation hook into `.claude/`.

The convention rule is **owned by the package, not hand-copied**: `planners install` generates a
version-stamped `.claude/rules/planners.md` (per-repo) or `~/.claude/rules/planners.md` (global),
which Claude Code auto-loads. Edit the convention in the package and reinstall — don't hand-edit the
installed file. A pre-existing hand-maintained `plan-files.md` is superseded by the generated
`planners.md`; install warns about it (and never deletes it).

Plans live in `.planners/plans/`, where each plan is its own directory
(`.planners/plans/{NNN}-{slug}/plan.md`) so it can carry scoped sidecar files; the generated
`.planners/README.md` is the plans index (GitHub auto-renders it on folder browse).

## Usage

```bash
uv run planners add <slug> --title "<Title>"   # scaffold a new plan
uv run planners index .                         # regenerate .planners/README.md
uv run planners validate .planners/plans        # validate plan frontmatter
uv run planners schema                          # show the plan metadata schema
uv run planners skill <name>                    # print a bundled skill body
uv run planners rule <name>                     # print a bundled convention rule body
uv run planners install                         # install the /planners holder, rule, and hook
```

See [`.planners/README.md`](.planners/README.md) for a plan index with links and [`CHANGELOG.md`](CHANGELOG.md) for release notes.
