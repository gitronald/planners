# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.13.0] - 2026-10-09

### Added

- `planners remote` classifies `origin` as `github`, `single-branch`,
  `other-forge`, `bare`, or `none` from its URL and `gh`'s configured hosts,
  without contacting it; `[remote] kind` in a committed `.planners/config.toml`
  overrides the built-in host table for every clone, and
  `git config planners.remoteKind` for one clone

### Changed

- `implemented` no longer requires the feature branch to have an upstream when
  `origin` is not GitHub
- `finish --no-pr` on a single-branch remote takes the local merge as the merge
  and leaves the base unpushed, since that push publishes into the live document
- The `implement`, `close`, `update`, and `pipeline` skills skip the draft PR
  off GitHub, close through the no-PR path, and ask before pushing the base to
  a single-branch remote

## [0.12.1] - 2026-10-09

### Fixed

- `finish` judges the remote branch by the tip `ls-remote` reports and deletes
  it under a lease on that tip, so a push made after the last fetch stops the
  deletion instead of being lost.
- Lifecycle commits (`add`, `finalize`, `activate`, `set-pr`, `implemented`,
  `retire`, and `finish`'s index commit) take only their own files; anything
  else already staged stays staged and out of the plan's commit.
- `implemented` refuses on a branch other than the one the plan (or the
  subplan, or its umbrella) records.
- `finalize` validates each staged plan before moving any, so an invalid
  value such as an unparseable `created` leaves the batch in staging.
- `retire` refuses an umbrella whose subplans cannot be read, instead of
  treating them as finished.
- `review` ignores fenced example `Review:` markers in a Log, and subplan table
  updates ignore fenced example tables between the markers.
- Setting a frontmatter key that a hand edit left twice rewrites the first
  line and drops the later copy, which the parser would otherwise read.
- `validate` reports a missing or unreadable file as a violation (and in the
  `--json` document) instead of crashing.
- `add` and `finalize` take the next plan number from the directory names, so
  a plan whose frontmatter does not parse keeps its number instead of having
  it reused.
- A timestamp with no UTC offset is read as UTC everywhere. `review` and
  `finalize` read it in the machine's local zone, so their order could differ
  from the index's and from one machine to another.

## [0.12.0] - 2026-10-09

### Added

- `planners validate --json` prints one JSON document on stdout: each plan's
  path, its parsed frontmatter and title (`null` when the frontmatter does not
  parse), and its violations, plus subplan errors, stale index files, and an
  `ok` that agrees with the exit code. A caller can read plans through the CLI
  instead of carrying its own copy of the frontmatter parser.

## [0.11.0] - 2026-10-09

### Added

- An `implemented` status: the implementation is finished and pushed, and
  its PR waits on review. It is open, sorts after `active` in the index, and
  an umbrella cannot close or retire over a subplan in it.
- `planners implemented <NNN>` flips an active plan or nested subplan to
  `implemented`, logs how many commits the branch carries past its base,
  commits on the feature branch, and takes the PR out of draft. It refuses
  while the branch has uncommitted or unpushed work, and on the mainline or a
  detached HEAD. A re-run finishes a run whose commit failed.
- `planners activate` appends a standard Log entry naming the branch, the
  base and commit, the worktree, and the PR. `--worktree <path>` records a
  repo-relative worktree, and `--no-worktree` the main checkout.
- `planners set-pr` appends a `PR opened` Log entry.
- `planners finish <NNN>` runs the cleanup after a closed plan's branch is
  merged, from the main checkout. It removes the worktree (running
  `.planners/hooks/pre-worktree-remove` first), pulls the base, deletes the
  branch on the remote and locally when the base contains it, commits a stale
  plan index, and re-installs any hook whose `INSTALL_PYTHON` points into
  `.worktrees/`. It stops on a branch that is not merged yet (printing the
  merge command), a worktree with uncommitted changes or commits the base
  lacks, a hand-edited plan index, or a refused call, and a re-run skips the steps already done. The
  merge itself stays the session's own `gh pr merge` or `git merge`, so the
  automation level still governs it.

### Changed

- The `close` skill's last step is now: commit and push the closing edit, merge,
  then `planners finish`. The `close` and `pipeline` skills and the rule say
  that the session runs every cleanup step itself, and hands one to the user
  only after a call to it was refused.
- `planners activate` returns an `implemented` plan to `active` on its
  feature branch, without the mainline guard, and logs `Reactivated`.
- `planners review` includes `implemented` plans by default and treats them
  as work in progress, like `active` and `blocked`.
- The `implement` and `pipeline` skills end with `planners implemented`, and
  `close` accepts an `implemented` or `active` plan.

### Fixed

- `planners review` passes a plan's branch or PR to `gh pr view` after
  `--`, so a value starting with `-` is read as the target, not a flag.

## [0.10.0] - 2026-10-09

### Added

- `planners review` reports what changed in the repo around each plan, and
  writes nothing. For each open plan (`active`, `draft`, and `blocked` by
  default; `--status/-s` selects others or `all`, and a plan number selects
  one) it lists the commits and tags since the plan was created or last
  reviewed, the backticked paths and `module.function` names the plan
  mentions with whether each still exists and what changed it, the other
  plans it names with their status, and for an active or blocked plan its
  branch, worktree, and PR state, judged at the branch tip. A summary table
  by status opens the report. `--json` emits it for the new `review` skill,
  with a `now` timestamp to stamp Log entries with; `--stale-days` sets when
  an idle branch is flagged. Missing `gh`, a missing remote, or a shallow
  clone reports the affected fields as unknown. A repo on the legacy
  `docs/plans/` layout is refused.
- `planners review --commit` commits the Log entries a review wrote, as
  `plan [review]: <N> plans`, on the mainline only (`--allow-branch`
  overrides). It refuses when a changed plan file differs outside its Log or
  is an active or blocked plan.
- A `review` skill (`/planners review`): it checks each plan's claims against
  the code, gives a verdict (still open, narrowed, accounted for, moot, or
  unclear), appends a dated `Review: <verdict>.` Log entry that the next
  review starts its window from, and proposes retirements for the user to
  confirm. Active and blocked plans are only reported on, never edited.
- `planners activate` reports the base's unpushed commits after its commit:
  how many sit ahead of the upstream as last fetched, how many are the plan's
  own (every path under the plan's directory or the index), and how many are
  other, listed one per line. The `implement` skill reads that line to decide
  whether the push that follows needs confirming, instead of sorting the
  commits by eye. The report is withheld when the base has no upstream, and
  `--no-commit` prints none.
- The `close` skill has an explicit no-PR path: "no PR" merges the branch into
  the base with a local `git merge --no-ff`, records `pr: null`, and
  regenerates the index after the merge. When a PR already exists for the
  branch, the skill stops and asks whether to merge through it or close it
  unmerged, rather than reading "no PR" as "merge the PR". "minimal review"
  selects a lighter review gate (the project checks plus a diff skim, nothing
  posted) in place of the full review loop. `pipeline` names how a no-PR
  request meets its always-opened draft PR.

## [0.9.0] - 2026-10-06

### Added

- `planners validate --no-index` skips the stale-index comparison and checks
  frontmatter alone. Since 0.6.0 `validate` has also failed when a repo's
  `.planners/README.md` disagrees with its frontmatter, which is right for the
  repo's own hook but makes one unregenerated index abort a caller that
  validates plans across repos it does not maintain and cannot reindex.

### Changed

- The first nested `add` places the generated subplans table near the top of
  the umbrella's `## Plan` section, after its first subsection (the opening
  summary) or after the lead paragraph when there are none, instead of at the
  end of the spec. The table summarizes the steps, so it now comes before the
  decisions and risks it summarizes. An umbrella that already has a table, or a
  pre-placed pair of markers, is left where it is.

## [0.8.0] - 2026-09-29

### Added

- **Nested subplans.** A plan can be split into files under its own directory
  (`subplans/<letter>-<step>.md`) instead of into lettered sibling plans. Each
  subplan carries a minimal frontmatter (`status` and `branch`, with `pr`,
  `needs`, and `moved_to` optional) and stays out of the index. The rule and the
  skills make this the default shape whenever a plan is split; lettered sibling
  plans stay supported, on request.
- `planners subplans <NNN>` lists a plan's nested subplans and exits non-zero
  when the umbrella's table disagrees with the subplan frontmatter. `--write`
  regenerates the table's Status column between two marker comments,
  `--set <letter>=<status>` changes one subplan and the table in the same step,
  and `--require-closed` fails while a subplan is `draft`, `active`, or
  `blocked`. The commands that change a subplan (`--set`, `add --nested`, and
  `retire`) check everything that can refuse before they write, so a refusal
  leaves every file as it was.
- `planners add <slug> --parent <NNN> --nested` scaffolds a nested subplan and
  adds its row to the umbrella's table. It takes the next free letter from `b`;
  `--letter a` makes the investigation.
- `planners set-pr <NNN> <url>` records a plan's PR, refreshes the index, and
  commits.
- `planners retire <NNN>` closes a plan as retired: frontmatter, Log entry,
  index, and commit. `--into <NNN>` records where the work went. Given a nested
  subplan (`retire 012d --into 015`), it writes `moved_to` and updates the
  umbrella's table. It refuses an umbrella that still has a `draft`, `active`,
  or `blocked` subplan.
- A `blocked` status, for work that is waiting on a person. It is an open state:
  `concluded` stays empty, and it sorts after `active` in the index.
- `planners validate --subplans` also checks nested subplan frontmatter. It is
  off by default, so a plan with free-form files under `subplans/` keeps passing.
- The `implement` and `pipeline` skills carry guidance for an orchestrated run,
  used when the user asks for subagents or a workflow, and `implement <NNN><letter>`
  starts one nested subplan on its own.
- The rule documents a `## Handoff` section, between Log and Retrospective, for
  the state an effort is left in between sessions.
- The `implement` and `close` skills run a repo's `.planners/hooks/post-worktree`
  and `.planners/hooks/pre-worktree-remove` scripts when they exist.

### Changed

- `planners validate` with no argument validates the current directory. It used
  to exit with a usage error.
- `planners activate` prints the branch it recorded and the branch it committed
  on as two lines, where one line named only the recorded branch.
- `planners activate <NNN><letter>` on a nested subplan points to
  `planners subplans <NNN> --set <letter>=<status>`.
- The `close` skill refuses to close an umbrella with unfinished nested
  subplans, and confirms a merge with `git merge-base --is-ancestor` before it
  deletes the branch.
- The `implement` skill confirms before a push that would publish unpushed
  commits on the base, finds a base that lives in its own worktree, and creates
  the worktree under the main repo root.
- The length guidance applies to each file on its own: the umbrella, and every
  subplan.

## [0.7.0] - 2026-09-12

### Changed

- The prompt-packaging and install machinery now comes from
  [pkgskills](https://pypi.org/project/pkgskills/) (`>=0.5.1`), a new runtime
  dependency (it brings in PyYAML). `skill`, `rule`, `install`, and `permissions`
  are mounted from it; plan files, the index, and the lifecycle commands are
  unchanged. `pkgskills hosts` now discovers planners through the
  `pkgskills.hosts` entry point.
- **Every existing install reports `foreign` after upgrading, not `drifted`.**
  The generated stamp gains a `via pkgskills X` token, so a holder or rule written
  by an earlier release cannot be verified as generated. A bare `install` refuses
  to overwrite it; run `planners install --force` (`--local --force` for a
  per-repo install) once to replace both. The existing `.pre-commit-config.yaml`
  entries and `.gitattributes` line need nothing.
- `install --check` prints the pkgskills table: one row per artifact, one for the
  `.gitattributes` line, and a non-gating row per hook (`hook planners-validate`,
  `hook planners-index`), replacing the `holder:`/`rule:`/`gitattr:`/`hook:` lines.
- The generated `/planners` stub quotes its `name` and `description` frontmatter
  and uses the pkgskills dispatcher body; the rule is unchanged apart from the stamp.

### Removed

- `install --full`, `--no-activate`, and `--no-rule`. The hooks are always
  registered and the rule always written; instead of `--full`, run
  `uv add --dev pre-commit` once.
- The interactive confirmation before `install --force` overwrites a file; a bare
  `install` over a file it did not generate now refuses with a pointer to `--force`.
- `planners.get_skill` and `planners.list_skills` from the package's public API.

### Added

- `install` now wires a `planners-index` hook at `post-merge`, so the plan index
  is regenerated automatically after a merge instead of being left for whoever
  remembers. The `merge=union` attribute keeps a local merge from conflicting on
  the generated index, but can leave a row duplicated when both sides rewrote the
  same one — repairable only by regenerating from the plan files, and only after
  the merge, once both sides' plans are on disk. Until now that step was manual
  and its omission silent: a duplicated row surfaces as a `validate` failure some
  commits later, well after the merge that caused it. Registration is included —
  `pre-commit install` wires only the `pre-commit` hook, so activation now also
  runs `--hook-type post-merge`, without which the config entry would never fire.
  A config carrying only `planners-validate` predates this and has the new hook
  appended on its next `install`, leaving its committed entry untouched.

  Two limits, both documented in the generated rule: git skips `post-merge` when
  a merge stops on conflicts (finish it by hand and run `planners index .`
  yourself), and the regenerated index lands as an uncommitted change, since git
  writes the merge tree before the hook runs — commit it alongside.

## [0.6.1] - 2026-09-09

### Fixed

- `install` no longer raises on a `.gitattributes` it cannot read. The file was
  read unguarded on the write path while the matching check guarded the same
  read, so a repo whose `.gitattributes` was unreadable or not valid UTF-8 got a
  traceback out of `install` and a misleading `gitattr: missing` out of
  `install --check`. Both now report `unreadable` as its own status, and the
  file is left untouched — with or without `--force`, since every write either
  appends to or edits one line of text that was read, and there is none.

## [0.6.0] - 2026-09-09

### Fixed

- `dependabot.yml` now sets `target-branch: dev` for both ecosystems, so
  dependency-update PRs open against the active branch instead of `main`. They
  previously targeted the default branch, so each batch had to be retargeted by
  hand before it could merge into `dev`, and Dependabot resolved manifests
  against `main` rather than the tree the updates would merge into. Because
  Dependabot reads its config from the default branch, this takes effect once
  the change reaches `main`.

### Added

- `install` now gives the generated plan index its merge semantics: a
  `.planners/README.md merge=union` line in the repo's `.gitattributes`. A local
  merge whose two sides both added or closed plans used to conflict on the index
  and leave every repo to invent its own fix. `union` is a built-in git driver,
  so the one committed line is the whole fix — nothing to configure per clone,
  and it works in a fresh clone that has never run `install`. Other attribute
  lines are preserved; a line that names the index but says something else (such
  as a hand-rolled `merge=ours` stopgap) is reported rather than clobbered, and
  `install --force` rewrites it. Note that GitHub's server-side merge does not
  apply the attribute, so a PR can still report a conflict on the index; merging
  the base in locally now resolves it without hand-editing a generated file.
- `install --check` reports the attribute as a `gitattr:` line and gates on it,
  alongside `holder:` and `rule:`. It also prints a `hook:` line saying whether
  the `planners-validate` git hook is actually registered **in this clone** —
  per-clone state a fresh clone silently lacks, so a hook that never fires used
  to be indistinguishable from one that fires and finds nothing wrong. That line
  is reported, never gated: a consumer without `pre-commit` is correctly
  installed, just unguarded.
- `validate` now fails when the tracked index disagrees with the plan
  frontmatter it is generated from, naming `planners index .` as the fix. It
  works when handed individual plan files, which is how the pre-commit hook
  calls it. This is also the repair signal for the one thing `union` gets wrong:
  when both branches rewrote the *same* row, it keeps both, listing a plan
  twice. A repo with no index yet is not failed for its absence, and a legacy
  `docs/plans/` layout is left alone.

## [0.5.2] - 2026-09-08

### Added

- `activate` command — `planners activate 005` flips a plan to `active`, fills
  `branch:` (`feature/<slug>` by default, `--branch` to choose), refreshes the
  index, and commits `plan [activate]: 005 - <slug>`. Activation was the last
  lifecycle mutation still done by hand-editing frontmatter, which is why the
  mainline guard shipped in 0.5.0 could not cover it; it now carries the same
  guard and the same `--allow-branch` escape hatch as `add`. Closed plans
  (`done`/`retired`) are refused; a parked `inactive` plan may be reactivated.
  Takes a subplan reference (`005a`) as well as a plan number, and re-running it
  is a no-op unless an earlier run wrote the plan but failed to commit.

## [0.5.1] - 2026-09-08

### Fixed

- The publish workflow rejected the release wheel and never uploaded `0.5.0` to
  PyPI. `hatchling` is unpinned and now emits `Metadata-Version: 2.5`, which the
  twine bundled in `pypa/gh-action-pypi-publish` v1.14.0 (twine 6.1.0, packaging
  25.0) refuses. The action is pinned to v1.14.2 (twine 7.0.0, packaging 26.2),
  which accepts it. The break was latent since the backend started emitting 2.5 —
  it would have hit whichever tag came next, not something 0.5.0 introduced.

## [0.5.0] - 2026-09-08

### Added

- `base` command printing the repo's mainline branch — the branches a plan commit
  belongs on. `--all` lists every one in resolution order; it exits non-zero when
  no mainline resolves, so a script can branch on it.
- `add` and `finalize` now refuse to commit when `HEAD` is off the mainline,
  so a plan is recorded there even if the feature branch never merges. The
  accepted set is `dev` (when that branch exists) plus the repo's default branch.
  `--allow-branch` overrides the refusal for a repo whose mainline is not
  detectable by name.

### Changed

- The convention rule and the `add`/`implement` skills now state that plan
  commits land on the mainline before the branch or worktree is created, and
  point at `base --all` instead of assuming `dev`.
- Plan commit subjects are documented as naming the **slug**, not the title, so
  the hand-written `activate`/`close`/`retire` subjects match what `add` and
  `finalize` write. The convention is stated once in the rule.
- `close` returns to the mainline via `base` rather than a hardcoded `git
  checkout dev`, and its cleanup warning covers every mainline branch.
- The convention rule documents the subplan-only `sub:` key and its position in
  the frontmatter (directly after `slug`).

### Fixed

- The `add` skill's own title placeholders were Title Case while the same file
  required sentence case; its `## Umbrella + subplans` and `## Batch / deferred
  creation` sections also sat between steps 1 and 2, so the remaining steps read
  as part of batching. Steps 1–3 are now contiguous.
- The `implement` skill's worktree example named a `plan/<NNN>-<slug>` branch
  while the same skill derives `feature/<slug>`.
- `add` and `finalize` could commit a plan into a **different repository** than
  the one they ran in. An ambient `GIT_DIR` — which git exports to every hook it
  runs, so a hook or wrapper inherits it without anyone setting it — outranks the
  working directory, so the `plan [add]` commit landed in another repo's history
  while the plan files stayed uncommitted here. Every git shell-out is now pinned
  to an explicit repo root with the location variables stripped, including the
  hook-detection helpers and `pre-commit install`.

## [0.4.0] - 2026-07-09

### Added

- `permissions` command that maps an automation level (`none`, `assist`,
  `confirm`, `full`, with numeric aliases `0`-`3`) to the Bash allow-rules in
  `settings.json`, pre-authorizing the shell commands each level unlocks so the
  lifecycle skills prompt less. Grants are additive and never downgrade an
  existing `deny`/`ask` rule, and are mode-aware for global vs. local installs.
- `validate` check that flags malformed PR URLs in plan frontmatter.

### Changed

- The close-gate check now aligns with CI and points at the `permissions`
  command for reducing prompts.

### Fixed

- `permissions` apply is now a no-op when there is nothing to add.
- Fixed the pipeline review-gate note prose wrap.

## [0.3.1] - 2026-06-28

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
