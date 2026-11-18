# Plan Files: always-on part

Plans live in `.planners/plans/<NNN>-<slug>/plan.md` and are managed by the **`planners`**
package through the `/planners` skill. This generated file is the part of the convention
that holds in every session. The full convention is the `planners` rule, which loads only
once a session reads or writes a plan file in its working directory: before writing,
judging, or describing a plan without it, run `{cli} rule planners`.

- **Through the tool, not by hand.** Create, activate, log, close, index, and backfill
  plans with `/planners` and the CLI. Never compute a plan number, type a timestamp, or
  hand-edit the generated `.planners/README.md`
- **Print a step's instructions before describing or running it**:
  `{cli} skill <subcommand>`. They change with the installed version, and a step
  described from memory is described wrongly
- **`plan [add]` and `plan [activate]` commits belong on the mainline**, before the
  feature branch or worktree exists, so the plan is recorded there even if the branch
  never merges. `add`, `finalize`, and `activate` refuse off it; switch to the mainline,
  and do not reach for `--allow-branch` to get past the refusal
- **Plan commit subjects are the tool's**: `plan [<verb>]: {NNN} - <slug>`. Do not write
  one by hand, imitate the format in other commits, or flag it against another
  commit-message rule
- **A plan is shared.** Keep real names, personal emails, account handles, and absolute
  or home-directory paths out of the plan, its Log, and its sidecar files; use stand-ins
  (`Jane Doe`, `you@example.com`, `owner/repo`, repo-relative paths). On a public repo
  this is a hard blocker; on a private one, warn and continue
- **Never overwrite plan content.** Make targeted edits or append; the original spec is
  the record of what was planned. Handoff is the one section rewritten in place
