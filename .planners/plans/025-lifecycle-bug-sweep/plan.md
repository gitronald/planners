---
id: 25
slug: lifecycle-bug-sweep
status: active
branch: feature/025-lifecycle-bug-sweep
created: 2026-11-14T10:29:01-08:00
concluded:
pr: https://github.com/gitronald/planners/pull/72
---

# Fix lifecycle bugs found in a review sweep

## Plan

### Goal

Land the bug fixes and simplifications from a review sweep of the lifecycle
commands. The sweep was written in a sandboxed cloud session, in one commit
plus a changelog commit, without running the gate. Each fix lands here as its
own commit, with a test that fails on the old code, retyped by hand and gated.

### Source

- Reauthored from `origin/ccr-08cc166f-iubhf8` @ `3522aab8`, commits
  `85e37b94` (the sweep) and `3522aab8` (its changelog and `index` skill text).
  The branch's first commits implement plan 024, which lands first. This plan's
  branch is stacked on plan 024's, because both edit `index()`, its tests, and
  the same changelog bullet.
- Gate, after every batch: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pyrefly check`,
  `uv run planners validate .`
- Per-commit review rows: `review.md` in this directory

### Decisions

- The sweep commit mixes about twelve fixes with refactors. It is split into one
  commit per fix, with the pure refactors first.
- `review.py`: the sweep's `len({c.sha for c in found})` -> `len(found)` is not in
  its message. It is not taken, and the de-duplication stays.
- `_is_unmodified` keeps its `ValueError` fallback for a path outside the root.
  The sweep removed it with no need.
- `implemented` prints no push hint on a single-branch remote, where a feature
  branch cannot be pushed. That is the intended wording change.
- The README command reference gains a note on `index`'s new `--cols` default.
- The changelog bullets from `3522aab8` are split across the batches that ship
  the behavior they describe, and checked against it.

### Batches

| # | Batch | Desktop subject | Mobile shas | Fixes / regenerations | Approval |
|---|---|---|---|---|---|
| 1 | `ref-exists` | `simplify repeated rev-parse checks into proc.ref_exists` | 85e37b94 | Only the proc.ref_exists helper (added to __all__) and its call-site swaps: base._has_branch, base._default_branch, the unborn check in base.detect, finish.delete_local_branch, start.ensure_branch, and cli _sync_base, _remote_or_local, _check_merged, and _work_authored; Leaves out base.detect's UNRESOLVED change, start's ahead.total change, and finish's ls-remote change, which land in their own batches |  |
| 2 | `cli-helpers` | `simplify cli commit, log, and resume helpers` | 85e37b94 | _commit takes Sequence[Path] and makes them relative itself; every caller passes paths (add, _add_nested, finalize, _activate, _set_pr, implemented, retire, block, log, conclude, and _review_commit with root / rel); Adds _append_log and uses it in _activate, _set_pr, implemented (both paths), and log_. retire keeps its own calls here, since moving retire's nested write to before=Handoff changes behavior and goes in the retire batch; Adds _resuming and uses it in implemented, block, and conclude, then removes _status_at_head. The retire use goes in the retire batch; Removes _rendered_index and inlines _collect_metas plus _index_document into _refresh_index, keeping `cols: str` required. The None default comes in the index-cols batch. _index_document loses its cols default, and its docstring is updated; _git_status_porcelain goes through proc.git_out with rstrip, _unpublished_work loses its ignore/origin defaults, parses line[3:], and uses start_mod.push_command; _finish_target takes label from on_base.prefix; Module docstring, _shown docstring, and the register comment edits; review.py: `item.status in CAREFUL_STATUSES` (equivalent with StrEnum); Does NOT take the review.py `len({c.sha for c in found})` -> `len(found)` hunk: the de-duplication stays as on dev; Keeps _is_unmodified's ValueError fallback as on dev (desktop decision: the removal buys nothing) |  |
| 3 | `index-keep-cols` | `update index refreshes to keep the tracked column set` | 85e37b94 3522aab8 | index.py: _header_row and tracked_cols; cli.py: _refresh_index(cols: str \| None = None) reads the tracked set and falls back to curated on OSError or UnicodeDecodeError. Every lifecycle call site becomes _refresh_index(root). index --cols defaults to None with the new help text, and the INDEX_COLS check skips None; test_a_wide_index_stays_wide_through_a_lifecycle_command; SKILL.md generator block and the paragraph from 3522aab; CHANGELOG Unreleased/Changed bullet for the --cols default, checked against the landed behavior; README command reference: note that planners index . keeps the column set the index is already in (desktop addition) | **yes**: Changes the public `planners index --cols` default from curated to the tracked set. The lifecycle commands and the post-merge hook stop narrowing a wide index. |
| 4 | `base-detect-unresolved` | `update base detection to keep head with no mainline` | 85e37b94 | detect returns a Mainline with empty branches and the real current/detached instead of UNRESOLVED when nothing resolves; thin=thin and bool(branches); module, UNRESOLVED, and detect docstrings updated; Tests: test_detect_reports_the_branch_when_no_mainline_resolves and test_implemented_in_a_repo_whose_mainline_has_another_name; CHANGELOG Fixed bullet (implemented/conclude refusal, activate logging 'a detached HEAD') |  |
| 5 | `implemented-push-hint` | `update implemented to ask for a push only with a remote` | 85e37b94 | The closing push line prints only for github (PR wording) and for other_forge/bare (remote wording), and names mainline.current; test_implemented_marks_the_plan_and_counts_the_work now asserts no 'push'; adds test_implemented_asks_for_the_push_where_there_is_a_remote; CHANGELOG Changed bullet |  |
| 6 | `add-letters-no-empty-dir` | `update add to skip held letters and leave no empty dir` | 85e37b94 3522aab8 | _taken_numbers becomes _taken (number, letter) from directory names. _umbrella is extracted and used by add and _add_nested; add and finalize drop the eager plans_dir.mkdir, which the later plan_dir.mkdir(parents=True) covers. finalize's docstring is corrected to say one commit; Tests: test_add_sibling_skips_a_letter_whose_plan_does_not_parse and test_add_sibling_of_a_missing_umbrella_leaves_nothing_behind; CHANGELOG: the add --parent Fixed bullet, plus the 'A refused add or finalize no longer leaves an empty .planners/plans/' sentence that 3522aab appended to the index no-op bullet |  |
| 7 | `unreadable-plan-file` | `fix tracebacks on plan files that are not utf-8` | 85e37b94 | PlanMetadata.from_file wraps OSError/UnicodeDecodeError in PlanError, and its docstring says so; cli _collect_staged and _plan_status catch the same errors and exit 1 with 'cannot read'; test_a_plan_that_is_not_utf8_is_reported_not_raised; CHANGELOG bullet. Mobile filed it under Changed; it belongs under Fixed |  |
| 8 | `validate-from-plans-tree` | `update validate to find a stale index from .planners/` | 85e37b94 | _repo_root_of tries plan.parents, then plan.resolve().parents; The parametrized test_validate_finds_a_stale_index_from_inside_the_plans_tree; CHANGELOG Fixed bullet |  |
| 9 | `review-commit-log-before-handoff` | `update review --commit to accept a log before handoff` | 85e37b94 | _split_log returns (fm, the non-blank outside lines) so where the Log sits does not matter, and its return annotation and docstring are updated; Tests: test_cli_commit_accepts_a_log_added_ahead_of_the_handoff and test_cli_commit_still_refuses_a_change_beside_the_new_log; CHANGELOG Fixed bullet |  |
| 10 | `finish-remote-branch` | `update finish remote branch match and checkout hint` | 85e37b94 | delete_remote_branch runs ls-remote on refs/heads/<branch> and keeps only the exact-ref line; _finish names the main checkout from proc.worktrees(root)[0], not root, in the run-from-inside Stop; Tests: test_delete_remote_branch_reads_the_branch_it_was_asked_about, plus the added assertion in test_finish_stops_inside_the_worktree; CHANGELOG Fixed bullet |  |
| 11 | `set-pr-recorded-url` | `update set-pr to compare the recorded url, not the text` | 85e37b94 | _set_pr reads the plan with _read_plan first, parses the recorded pr from the frontmatter, and decides by recorded == url instead of updated == text. staged = [target]; test_set_pr_logs_nothing_for_a_url_the_plan_already_records; CHANGELOG Changed bullet |  |
| 12 | `head-read-below-root` | `update head reads to work from below the repo root` | 85e37b94 | _frontmatter_at_head uses `HEAD:./<path>`; test_set_pr_reads_head_from_a_directory_below_the_repository_root; CHANGELOG Fixed bullet naming set-pr, activate, block, conclude, and retire |  |
| 13 | `retire-resume` | `update retire to resume a failed commit and nest notes` | 85e37b94 | The entry is written through entries.log_entry; Both branches use _resuming with Status.retired and print 'committing the earlier change' when resuming. Both write through _append_log, so a nested retire's first Log now lands ahead of Handoff/Retrospective. The nested slug comes from current.step; Tests: test_retire_nests_the_later_lines_of_a_note and test_retire_finishes_an_earlier_run_that_did_not_commit; CHANGELOG Changed bullet |  |
| 14 | `start-level-count` | `update start to report no unpushed count when level` | 85e37b94 | check_base_pushed adds `and ahead.total` to the waiting condition; test_start_on_a_single_branch_remote_counts_no_commits_when_level; CHANGELOG Fixed bullet |  |
| 15 | `log-path-punctuation` | `update log to drop sentence punctuation from paths` | 85e37b94 | local_paths strips trailing .,;:!? from each match before de-duplicating; test_local_paths_leaves_sentence_punctuation_off_a_path, plus the expected-output change in test_cli_log; CHANGELOG Fixed bullet |  |
| 16 | `subplans-table-and-listing` | `update subplans table rows and listing alignment` | 85e37b94 | write_table inserts added rows after the last non-blank line before the end marker; cli adds _STATUS_WIDTH and uses it in the subplans listing in place of the hard-coded 8. The mobile commit message never mentions this change; test_write_table_appends_a_row_ahead_of_a_blank_line_before_the_end; CHANGELOG: both Fixed bullets (row placement, and alignment on implemented) |  |
| 17 | `schema-concluded-text` | `update schema to describe concluded as never null` | 85e37b94 | The PlanMetadata docstring names branch and pr as the nullable fields and says concluded is never null. The concluded field description becomes '"" if open, never null'. This matches validate: closed plans require a timestamp, and open plans reject null; CHANGELOG Fixed bullet; The mobile commit message never mentions this change | **yes**: `planners schema PlanMetadata` output is the documented authority on frontmatter, and the generated planners rule points readers at it. This changes its text, so the user should approve it alone. |

Dropped: none from the sweep. The cloud session's plan lifecycle commits for
plan 024 are dropped there.

## Log

- **2026-11-14T10:37:57-08:00** — Activated.
  - Branch: `feature/025-lifecycle-bug-sweep`
  - Base: `dev` at `c06d0ed`
  - Worktree: `.worktrees/025-lifecycle-bug-sweep`
  - PR: pending
- **2026-11-14T10:38:17-08:00** — PR opened: https://github.com/gitronald/planners/pull/72
- **2026-11-14T11:53:46-08:00** — Reauthored from `origin/ccr-08cc166f-iubhf8` @ `3522aab8`: all 17 batches retyped by hand, gated, reviewed, and committed one at a time. Every one folds in `85e37b94`; the two marked (+3522aab8) also carry its changelog and skill text.
  - `b61763f` simplify repeated rev-parse checks into proc.ref_exists
  - `5f494ac` simplify cli commit, log, and resume helpers
  - `5a559c9` update index refreshes to keep the tracked column set (+3522aab8)
  - `5a0a9bf` update base detection to keep head with no mainline
  - `32e4f0e` update implemented to ask for a push only with a remote
  - `9464701` update add to skip held letters and leave no empty dir (+3522aab8)
  - `87f5b8b` fix tracebacks on plan files that are not utf-8
  - `71219c2` update validate to find a stale index from .planners/
  - `5cebd35` update review --commit to accept a log before handoff
  - `8b73c4b` update finish remote branch match and checkout hint
  - `c46b8bd` update set-pr to compare the recorded url, not the text
  - `2dc1c25` update head reads to work from below the repo root
  - `15a8aaf` update retire to resume a failed commit and nest notes
  - `836b0ac` update start to report no unpushed count when level
  - `cfd327d` update log to drop sentence punctuation from paths
  - `397dbc0` update subplans table rows and listing alignment
  - `f8b8c98` update schema to describe concluded as never null
  - `git diff 3522aab HEAD` differs from the mobile tip only by the planned decisions (review.py de-duplication kept, `_is_unmodified` fallback kept, README `--cols` note), base.py docstrings reworded to match the new no-mainline result, `_split_log` returning a tuple, ruff import formatting, test order, and the changelog bullets reworded and regrouped under Changed and Fixed.
  - Gate at the last batch: pytest 818 passed (coverage 95.16%), ruff check and format, pyrefly 0 errors, planners validate ok.
