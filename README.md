# planners

Tools for managing plain-text plans with a documented schema, CLI commands, and an installable skillstub. It is designed to automate the mechanical components of generating and updating plain-text plans with standardized frontmatter for a given project. To facilitate tracking and reviewing plans, it also automatically generates and maintains an index table of all existing plans and their statuses.

These tools can be used manually via CLI commands, but they are largely intended to be used in conjunction with a language model. To guide usage by a language model, it ships with built-in [skills](https://agentskills.io/home) and [rules](https://code.claude.com/docs/en/memory#organize-rules-with-claude/rules/) that offer an opinionated approach to managing the full plan-file lifecycle and automating usage of this package. These skills and rules can be installed on your system via the CLI commands listed in the instructions below. Once installed, the rules will enforce conventions around how plan files are named, filled, and updated, and the skills will facilitate the addition, implementation, and closing out of plans, which includes the use of git branches and worktrees as specified by the user. While its core functionality and plan files are model-agnostic, some aspects of its built-in support (e.g., the skill files, rule files, and pre-commit validation hook) are currently only available for use with Claude Code.

## Getting Started

`planners` is designed to run as a **global uv tool**, but you can also install it as a per-project dependency.

1. **Install the CLI as a uv tool** (once per machine), so `planners` is on your `PATH`:

   ```bash
   uv tool install planners
   ```

   Or (re)install from GitHub:
   ```bash
   uv tool install --force git+https://github.com/gitronald/planners.git
   ```

2. **Install the global rules and skills** — This installs a global Claude Code rule file and a skills stub: the actual skills are included within this package and are accessible via the CLI; the skills stub just tells the model how to access them and allows you to use the skills via slash commands.

   ```bash
   planners install
   ```

   This will:
   - (Re)generate the global `~/.claude/skills/planners/SKILL.md` holder and
     `~/.claude/rules/planners.md` convention rule, which can change as the package version advances.
   - Wire the `planners-validate` pre-commit hook into the project folder/repo's `.pre-commit-config.yaml` (registering it when `pre-commit` is available).

3. **Start planning** — scaffold your first plan using the `add` command.

   This can be done within a Claude Code terminal via the installed `/planners` skill and its `add` subcommand:
   ```
   /planners add my first feature
   ```

   Or via the CLI directly in your preferred terminal:
   ```bash
   planners add my-first-feature --title "My first feature"
   ```

   Either case will create a new plan file (`.planners/plans/000-my-first-feature/plan.md`) and refresh the index (`.planners/README.md`), though using the skill may produce a slightly different filename.

## Usage

```bash
planners add <slug> --title "<Title>"    # scaffold a new plan (--defer: stage it unnumbered)
planners finalize                        # number and commit the deferred batch, in one commit
planners activate <NNN>                  # flip a plan to active, fill branch:, and commit
planners base                            # print the repo's mainline branch (--all: every one)
planners index .                         # regenerate .planners/README.md
planners validate .planners/plans        # validate plan frontmatter
planners schema                          # show the plan metadata schema
planners skill <name>                    # print a bundled skill body
planners rule <name>                     # print a bundled convention rule body
planners install                         # install global holder + rule + repo hook (--local: per-repo)
planners permissions --level assist      # print an automation-level permission profile (--apply to write it)
```

> **Plan commits land on the mainline.** `add`, `finalize`, and `activate` refuse to commit when `HEAD` is off it,
> so a plan is recorded on the mainline even if the feature branch never merges. The accepted set is
> `dev` (when that branch exists) plus the repo's default branch — `planners base --all` prints it.
> Detection reads git's current refs and goes inert rather than blocking a repo it can't resolve;
> `--allow-branch` overrides the refusal where the mainline isn't detectable by name.

> **Per-repo (local) mode.** To pin planners as a project dependency instead of a global tool, add
> it with `uv add --dev planners` and run everything as `uv run planners …`; then `planners install --local`
> writes the holder and rule into the repo's own `.claude/` rather than `~/.claude/`.

## Plans

Each plan is a directory under `.planners/plans/` (`{NNN}-{slug}/plan.md`) and can carry scoped
sidecar files. The generated [`.planners/README.md`](.planners/README.md) is the plans index, which
GitHub auto-renders on folder browse.

## Convention rule

`planners install` writes a version-stamped, auto-loaded `~/.claude/rules/planners.md` (global) or
`.claude/rules/planners.md` (per-repo). The rule is **owned by the package** — edit the convention in
the package and reinstall; don't hand-edit the installed file. A hand-maintained `plan-files.md` is
superseded by the generated `planners.md` (install warns, never deletes it).

See [`CHANGELOG.md`](CHANGELOG.md) for release notes.
