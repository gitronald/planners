# Whole-codebase review: the report

A static review of this repository for simplification, optimization, documentation
drift, and historical cruft. The reviewer was an outside model run read-only, with no
access to the network and no ability to run the tests, so every finding below rests on
reading the code and on read-only git commands.

- **Tree reviewed:** commit `19787b9` on `dev` (version 0.18.1a0). Every `path:line`
  below refers to that commit, not to the current tree.
- **Scope:** `planners/*.py`, `planners/prompts/`, `tests/`, `README.md`,
  `CHANGELOG.md`, `.claude/CLAUDE.md`, `pyproject.toml`, and the repo configuration.
  Plan files and `uv.lock` were out of scope.
- **How it was produced:** the run stopped at its usage limit just before its final
  message and was resumed once, with the instruction to write the report from what it
  had already traced and to read nothing more.
- **Edits to this copy:** links that pointed at a local checkout are rewritten as
  repo-relative paths. Nothing else is changed.

The assessment of each finding against the current code is in `plan.md`.

---

## Summary

Reviewed the requested source, tests, bundled prompts, documentation, and configuration at `19787b9` on `dev`.  
The codebase has substantial regression coverage, and much of its defensive Git handling is justified.  
The strongest simplification opportunity is sharing plan discovery/loading and existing recovery logic.  
The clearest optimization wins are repeated mainline detection, repeated index parsing, and unnecessary test repository initialization.  
The most consequential documentation problems are in the no-PR close and pipeline completion instructions.  
The recent compatibility cleanup is largely complete; I found no basis for another broad compatibility purge.  
All findings below are verified by static tracing, not execution; I made no changes.

## Findings

### Simplifying

**S1. Plan discovery and loading are duplicated, and their error handling has diverged.**

- **Locations:** `planners/cli.py:212`, `planners/cli.py:419`, `planners/cli.py:456`, `planners/review.py:574`, `planners/metadata.py:210`.
- **Evidence:** CLI discovery and review discovery independently walk directories, match plan directory names, and require `plan.md`. CLI loading uses `PlanMetadata.from_file`, which translates read/decode errors into `PlanError` at `metadata.py:219`. Review reads the file **outside** its exception handler at `review.py:584`; its handler catches only parsing failures. An invalid UTF-8 top-level plan therefore escapes instead of becoming a skipped-plan diagnostic. The CLI catches only `ReviewError` around gathering at `cli.py:3071`. Review already handles subplan read failures at `review.py:595`.
- **Status:** **verified**.
- **Change:** Share discovery and a reader that returns metadata plus the original text, normalizing read/decode/parse errors once. Keep command-specific reporting at the callers. Add a review regression case for an invalid UTF-8 plan.
- **Risk:** Preserve malformed-directory discovery, skipped-plan reporting, and body preservation. Other repositories may contain malformed plans that currently produce different diagnostics.
- **Size:** **L**.

**S2. `start` duplicates a weaker PR-completion check instead of using `set-pr`’s recovery logic.**

- **Locations:** `planners/cli.py:2184`, `planners/cli.py:1553`, `planners/cli.py:2249`, `planners/start.py:375`, `planners/prompts/skills/implement/SKILL.md:58`.
- **Evidence:** `_set_pr` writes the URL and Log entry before committing at `cli.py:1568–1576`. It can resume an interrupted commit by comparing the recorded URL with HEAD at `cli.py:1553`. But `_start_pr` immediately returns `DONE` whenever the working file has a URL. After a rejected PR-recording commit, rerunning `start` on the active feature branch skips the base cleanliness check, passes the unchanged upstream commit comparison, and takes that early return. The pending record remains uncommitted despite the skill’s “After any interruption, run it again” instruction.
- **Status:** **verified**.
- **Change:** Route an already-recorded URL through `_set_pr`’s existing recovery check before declaring the PR step complete. Extend `tests/test_cli_start.py` with a hook that rejects the PR-recording commit, then verify the retry commits it without another PR or Log entry. `tests/test_cli_set_pr.py:122` already exercises the underlying recovery behavior.
- **Risk:** Preserve the protection against committing unrelated edits to a plan whose URL is already committed.
- **Size:** **M**.

**S3. `test_cli.py` retains live duplicates of helpers it already imports.**

- **Locations:** `tests/test_cli.py:16`, `tests/test_cli.py:21`, `tests/test_cli.py:577`, `tests/test_cli.py:831`, `tests/helpers.py:37`.
- **Evidence:** The search  
  `rg -n '\b(_check_layout|INDEX_MERGE_ATTR|INDEX_ATTR|_write_staged|_commit_all|_git_log)\b' planners/ tests/ planners/prompts/ README.md pyproject.toml`  
  found eight callers of `_commit_all`, three of `_git_log`, and twelve of `_write_staged`, all in `test_cli.py`. `_commit_all` duplicates imported `commit_all`; `_git_log` duplicates `git_out(path, "log", "--oneline")`; `_write_staged` performs the same operations as `_write_plan`.
- **Status:** **verified**.
- **Change:** Replace those callers with the existing helpers and remove the three duplicate definitions. These are used helpers, not dead code.
- **Risk:** Test-only. Preserve subprocess failure checking and output capture. Keep the separately dated helper in `test_review.py:52`, which sets both author and committer dates.
- **Size:** **S**.

### Optimizing

**O1. A normal first activation performs full mainline detection three times.**

- **Locations:** `planners/cli.py:1400`, `planners/cli.py:1471`, `planners/cli.py:1489`, `planners/base.py:177`.
- **Evidence:** For a draft plan, committing without `--allow-branch`, the path is `_activate → _guard_base_branch → detect`, then `_activation_entry → detect`, then `_current_branch → detect`. With an existing HEAD and a valid `origin/HEAD`, each detection launches six Git commands: repository check, HEAD verification, current branch, local `dev`, symbolic remote HEAD, and target verification. That is **18 Git processes for these detections alone**. The final caller needs only the current branch.
- **Status:** **verified**, counted from the call path.
- **Change:** Reuse one pre-commit `Mainline` result for the guard and activation entry. After committing, query only the current branch. This reduces this portion from 18 processes to seven while still observing any branch change during the commit.
- **Risk:** Do not cache across commits, hooks, checkouts, or fetches. Preserve detached/unborn handling.
- **Size:** **M**.

**O2. Index checking discards parsed plans and rendered output that the same command immediately needs again.**

- **Locations:** `planners/cli.py:552`, `planners/cli.py:601`, `planners/cli.py:2622`, `planners/cli.py:3355`, `planners/cli.py:3402`.
- **Evidence:** With **N readable plans and a readable existing index**, full-repository `validate` parses N files in its validation loop, then `_index_is_stale → _collect_metas` parses the same N again: **2N reads/parses**. When an existing index is stale, `log` and `finish` call `_index_is_stale`, then `_refresh_index`; each independently parses N plans. A top-level stale-index `log` additionally reads its target twice at `cli.py:2610` and `2612`: **2N + 2 plan-file reads**, excluding hooks.
- **Status:** **verified**.
- **Change:** Return the desired rendering from the index comparison so a repair can write it directly. Let validation supply its already-parsed metadata, loading only plans outside a partial validation selection.
- **Risk:** Preserve curated/wide column selection, malformed-plan diagnostics, and partial-file validation. Reuse only within a command phase where plan files have not changed.
- **Size:** **M**.

**O3. Review caches trees and tags but repeats identical file and history queries.**

- **Locations:** `planners/review.py:338`, `planners/review.py:392`, `planners/review.py:458`, `planners/review.py:499`, `tests/test_review.py:63`.
- **Evidence:** The existing `DRAFT_BODY` references `src/app.py`, `app.run`, and `app.missing`. During one `_gather` call, `_check_ref` issues the identical file-history `git log` three times, once for each reference. The two symbol references also issue the same `git show main:./src/app.py` twice. These are **five subprocesses for two unique queries**. `_Git` currently caches only trees, tags, and origin presence.
- **Status:** **verified**.
- **Change:** Add per-gather caches for `show(revision, path)` and `log(tuple(arguments))`, including failure results. Verify query counts using the existing multi-reference fixture.
- **Risk:** Cache keys must include revision and the complete history arguments, especially `--since` and pathspecs. Do not share caches between command runs.
- **Size:** **M**.

**O4. The global test fixture initializes Git repositories for pure unit tests.**

- **Locations:** `tests/conftest.py:54`, `tests/conftest.py:29`.
- **Evidence:** `_in_a_repository` is autouse and launches one `git init` for every test without `no_repo`.  
  `rg -n '^def test_' tests/test_{utils,body,entries,metadata,index,subplans,conventions}.py | wc -l` returned **148**.  
  `rg -n 'no_repo|subprocess|CliRunner|init_git|git_out|proc\.'` over those same seven files returned no matches. Reading them confirmed their pure-helper scope. Thus those files incur at least **148 unnecessary Git initializations**, with parameterization increasing the count.
- **Status:** **verified**; no timing claim.
- **Change:** Make repository initialization opt-in for CLI/integration tests, using module-level `usefixtures` where appropriate. Retain Git/gh environment isolation for tests that exercise those services.
- **Risk:** Some integration tests depend on ancestor repository discovery. Move them explicitly rather than broadly deleting isolation.
- **Size:** **M**.

### Docs

**D1. The no-PR close procedure still assumes GitHub and ordinary branch pushes after its opening explicitly supports other remote kinds.**

- **Locations:** `planners/prompts/skills/close/SKILL.md:30`, `:158`, `:247`, `:254`, `:274`, `:285`; `planners/start.py:377`; `planners/cli.py:2039`.
- **Evidence:** The opening selects no-PR automatically off GitHub and requires consent before publishing to a single-branch remote. The detailed procedure says it is used “only when the user asks,” unconditionally runs `gh pr list`, inherits step 5’s PR lookup, and instructs feature-branch push, `git pull`, and base push. Code explicitly skips feature pushes for `none` and `single-branch`; finish uses the local merged base for the latter. `tests/test_cli_finish.py:456` specifies that cleanup can leave that base unpushed.
- **Status:** **verified**.
- **Change:** State: “Use this path when requested or when `remote` reports a kind other than `github`.” Restrict PR lookup/reconciliation to GitHub. Skip PR filling on no-PR closes. Skip feature pushes for `none`/`single-branch`, all pull/push steps for `none`, and make the single-branch base push conditional on the stated approval.
- **Risk:** These instructions drive installed agents; the current inconsistency can cause failed commands or unintended publication.
- **Size:** **M**.

**D2. Pipeline completion is declared before the merge and cleanup it promises to perform.**

- **Locations:** `planners/prompts/skills/pipeline/SKILL.md:22`, `:102`, `:108`; `planners/cli.py:2726`, `planners/cli.py:2027`.
- **Evidence:** The skill says the run is done when frontmatter becomes `done`, and tells a resumed run to stop immediately on that status. `conclude` writes `done` and commits it **before** merging; `finish` requires that status before cleanup. An interruption between conclusion and merge/finish therefore satisfies the skill’s stopping condition while leaving its final stage unfinished.
- **Status:** **verified**.
- **Change:** Replace the completion rule with: “`done` records plan closure. A successful pipeline also confirms the merge and completes `finish`. If a resumed plan is already `done`, inspect and resume the remaining merge/cleanup steps. Report `retired` as its terminal disposition without implying shipment.”
- **Risk:** Installed pipeline prompts currently risk leaving branches, worktrees, or unmerged closing commits behind. Resumption must still respect the close gate.
- **Size:** **M**.

**D3. The core rule’s absolute mainline and commit-subject instructions conflict with supported lifecycle paths.**

- **Locations:** `planners/prompts/rules/planners-core.md:15`, `:19`; `planners/prompts/rules/planners.md:293`; `planners/prompts/skills/add/SKILL.md:65`; `planners/prompts/skills/implement/SKILL.md:213`.
- **Evidence:** The core rule forbids handwritten plan subjects, while the add and nested-implementation skills explicitly issue them. It says add/activate commits must precede feature branches, but nested add bypasses the guard for active umbrellas at `cli.py:895`, and reactivation bypasses it at `cli.py:1364–1400`. The full rule describes finalize subjects as single-plan subjects, while `cli.py:1230` emits a range/count for batches; review emits a count at `cli.py:2969`.
- **Status:** **verified**.
- **Change:** Use: “Use CLI-generated subjects when the command commits; for `--no-commit` and nested `subplans --set`, use the subject specified by the printed skill.” Scope the mainline rule to initial top-level creation/activation and name the nested/reactivation exceptions. Document batch finalize and review subject forms alongside the existing log-summary exception.
- **Risk:** Documentation only, but the always-on rule can otherwise override the more accurate skill instructions. Generated installed rules need regeneration.
- **Size:** **S**.

**D4. The add skill describes the wrong table position when `## Plan` has no subsections.**

- **Locations:** `planners/prompts/skills/add/SKILL.md:98`, `planners/body.py:140`, `planners/subplans.py:459`, `tests/test_subplans.py:308`.
- **Evidence:** The skill says “at the top” of the section. The insertion function defaults to the section’s end, and the existing test expects the lead paragraph before the generated table.
- **Status:** **verified**.
- **Change:** Replace that clause with: “or at the end of that section, after its existing content, when there are no subsections.”
- **Risk:** Only changes installed instructions; existing files remain untouched.
- **Size:** **S**.

**D5. The finalize recovery guarantee does not distinguish preflight refusal from failure after materialization.**

- **Locations:** `planners/prompts/skills/add/SKILL.md:239`, `planners/cli.py:1114`, `planners/cli.py:1197`, `planners/cli.py:1235`.
- **Evidence:** The skill says a refused finalize leaves the batch staged with nothing half-materialized. That holds for the mainline guard and validation pass. Materialization then writes numbered plans, moves sidecars, and deletes staging entries before committing. A rejecting commit hook leaves numbered, uncommitted plans; an I/O failure during materialization can stop partway.
- **Status:** **verified**.
- **Change:** Use: “Mainline and validation refusals leave the batch staged. After materialization begins, a failure may leave numbered files; a failed commit leaves the materialized batch uncommitted. Inspect those files before retrying or completing the commit.”
- **Risk:** Documentation only. Correct recovery instructions matter to every caller using deferred creation.
- **Size:** **S**.

**D6. `log` does not include the already-repaired, uncommitted index that its documentation promises to carry.**

- **Locations:** `planners/prompts/skills/update/SKILL.md:105`, `planners/cli.py:2578`, `planners/cli.py:2622`, `tests/test_cli_log.py:148`.
- **Evidence:** Both the skill and docstring name an uncommitted post-merge repair as a handled case. `_index_is_stale` compares the **working file** with freshly rendered content at `cli.py:572–576`. If the post-merge hook has already repaired it, the comparison is fresh and `log` excludes the index from its pathspec. `_commit` commits only those paths at `cli.py:513–515`, leaving the repair out. The existing tests cover a stale working file and a fresh committed index, which are different states.
- **Status:** **verified** for the exclusion; the resulting pre-commit failure was not reproduced.
- **Change:** Honor the documented contract: include a canonical repaired index when its committed version differs, even if the working copy already matches the renderer. Add the case “stale index committed, generator run without committing, then log.” Wording can then say: “A stale index is regenerated; an existing canonical repair is included in the Log commit.”
- **Risk:** Avoid sweeping arbitrary index edits into the commit. This affects repositories with the installed post-merge and validation hooks.
- **Size:** **M**.

### Historical cruft

**C1. The stale-index docstring still points to a symbol in the installer removed during the pkgskills extraction.**

- **Locations:** `planners/cli.py:557`, `planners/host.py:89`, `planners/index.py:19`.
- **Evidence:**  
  `rg -n 'planners\.install|install\.INDEX_MERGE_ATTR' planners/ tests/ planners/prompts/ README.md pyproject.toml`  
  returned only `cli.py:557`. A direct `test -e planners/install.py` check established that the file is absent. `git show 9369792 --stat` identifies its removal on **2026-09-12**. The declaration now lives at `host.INDEX_ATTR`; `index.py:19` already uses the correct reference.
- **Status:** **verified**.
- **Change:** Replace `install.INDEX_MERGE_ATTR` with `planners.host.INDEX_ATTR`, retaining the explanation of union-merge behavior.
- **Risk:** None to plan formats or CLI consumers; this removes a dangling documentation reference, not a compatibility implementation.
- **Size:** **S**.

**C2. A historical test edit left the deferred-add test checking an unrelated slug.**

- **Locations:** `tests/test_cli.py:586`, `tests/test_cli.py:602`.
- **Evidence:** The test creates `my-feature` but checks that `000-alpha` does not exist. `git blame -L 594,603 -- tests/test_cli.py` and `git show 4e2ab48 -- tests/test_cli.py` trace the assertion change to **2026-10-09**: it replaced a plans-directory assertion with the unrelated alpha path. A regression that also writes `000-my-feature/plan.md` would pass this check.
- **Status:** **verified**.
- **Change:** Assert that no numbered `*/plan.md` was materialized under the plans directory. Also check that HEAD remains unborn to substantiate the adjacent “never commits” comment.
- **Risk:** Test-only; allow an empty plans directory so the assertion checks the intended behavior rather than incidental directory creation.
- **Size:** **S**.

## Suggested batches

Each row is one commit, ordered from low-risk cleanup toward changes needing behavioral regression coverage.

| Order | Findings | Suggested commit subject |
|---:|---|---|
| 1 | C1 | `update the index attribute reference` |
| 2 | C2 | `update deferred add assertions to check its output` |
| 3 | S3 | `remove duplicate cli test helpers` |
| 4 | D4 | `update subplan table placement instructions` |
| 5 | D5 | `update finalize recovery instructions` |
| 6 | D3 | `update plan commit rules and their exceptions` |
| 7 | D1 | `update no-pr close steps for each remote kind` |
| 8 | D2 | `update pipeline completion and resume checks` |
| 9 | O4 | `update test fixtures to initialize git only when needed` |
| 10 | O1 | `update activation to reuse mainline detection` |
| 11 | O3 | `update review to cache repeated git reads` |
| 12 | S2 | `update start to resume pending pr record commits` |
| 13 | D6 | `update log to include an uncommitted index repair` |
| 14 | S1 | `fix review read errors with shared plan loading` |
| 15 | O2 | `update index checks to reuse parsed plans and renders` |

## Looked at and left alone

- **The recent legacy cleanup is real.** The direct search  
  `rg -n '\b(completed|abandoned|legacy_stamps|previous_names|PRE_ADOPTION_STAMP)\b|docs/plans|plan-files\.md' planners/ tests/ planners/prompts/ README.md pyproject.toml`  
  returned no matches. Direct path checks found `docs/plans`, `TODO.md`, and `scripts/install.sh` absent. Current parsing constructs the shipped `Status` enum at `metadata.py:192`; it does not map old status aliases.

- **The 28 local plans support that conclusion only locally.** A frontmatter-only scan found seven keys in every plan, **27 `done` and one `draft`**, with no legacy keys in those frontmatters. Examples are `.planners/plans/000-close-gate-pr-comment-permission/plan.md:2` and `.planners/plans/023-index-branch-link/plan.md:2`. **Other repositories’ plans are not visible to this review.**

- **Missing-activation-record fallbacks still have a purpose.** `_plan_base` at `cli.py:1492` falls back to detected mainline when no recorded base exists. The older plan 000 has its Log at `plan.md:56` but no `Base:` entry—the direct search for that entry returned no match. Removing the fallback would prevent base resolution for older consumer plans lacking generated activation records. The local sample contains closed older plans; it does not establish how many external open plans still need this.

- **Lettered sibling plans remain a current supported surface.** The add skill documents them, and `tests/test_cli_subplans.py:389` exercises `--parent` without `--nested`. Their absence from this repository’s frontmatter sample would not justify removing that public CLI behavior.

- **Git environment isolation and deletion safeguards are substantive.** `proc.py:56` prevents inherited repository-location variables from redirecting commands. The remote deletion checks exercised at `tests/test_cli_finish.py:597` protect against a collaborator pushing after the fetch. Worktree checks and hook repair address similarly concrete states. Their explanatory historical comments are useful assets.

- **Finalize’s preflight and post-write self-check are different checks.** Validation before materialization and verification afterward protect different boundaries. D5 concerns the recovery wording, not a recommendation to remove either check.

- **Several superficially similar helpers have different contracts.** Review’s unknown-state reporting, lifecycle warnings, and start/finish exceptions should not be collapsed into one universal subprocess policy. Likewise, `test_review.py:52` fixes committer dates because `git log --since` needs them; the ordinary commit helper’s author-date option is not equivalent.

- **Named schema selection and host callbacks have consumers.** The full rule invokes `schema PlanMetadata` at `planners/prompts/rules/planners.md:11`. Host callbacks are registered in the `Host` declaration. Neither is dead merely because ordinary Python callers are sparse.

- **The README command inventory and `.claude/CLAUDE.md` module inventory are current.** The declared runtime dependencies have production consumers; development dependencies have test, hook, build, or CI consumers. Generated caches, build outputs, and worktree ignores are not obsolete merely because their paths are absent today.

- **Historical changelog entries describe historical behavior.** References there to removed layouts and installer options are not current documentation defects. The live changes to `host.py` and `CHANGELOG.md` that appeared during this review were read too; the shortened description has a corresponding changelog entry.

## Not covered

- **No execution validation.** One offline help/import-profile probe was attempted, but I did not obtain usable execution evidence. No test, lint, type-check, coverage, or benchmark result is claimed.
- **Startup timing and slowest-test rankings.** Static tracing shows the CLI eagerly imports the lifecycle modules, including review/start/finish, before help is handled. I did not measure their cost. O1–O4 report demonstrable work counts, not elapsed-time improvements.
- **An exhaustive proof of dead-code absence.** I traced reported candidates and searched consumers, but the broad symbol-search output was partly truncated. I am not asserting that every private method, return field, fixture, or suppression has a necessary consumer.
- **External state:** other repositories’ plans, installed prompt copies, live GitHub configuration, current URL validity, package availability, and publication status. The publish workflow alone does not establish publication.
- **Dependency internals:** delegated pkgskills behavior was assessed through this repository’s host declaration, integration tests, and documentation, not a full audit of pkgskills.
- **Historical release reconstruction:** I read the changelog but did not reconstruct every old entry against every release tree, including the empty initial 0.3.1 sections.
- `uv.lock` remained out of scope. Historical plans were read only for frontmatter/layout sampling and targeted historical evidence.
- The final observed worktree had external modifications to `CHANGELOG.md` and `planners/host.py`. I read those changes and made none myself.