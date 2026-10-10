---
id: 14
slug: non-github-remotes
status: implemented
branch: feature/non-github-remotes
created: 2026-10-09T18:26:35-07:00
concluded:
pr: https://github.com/gitronald/planners/pull/44
---

# Detect remotes that cannot host a PR

## Plan

**Context.** The lifecycle assumes `origin` is a GitHub repository that `gh` can
reach. Nothing checks that. No code reads `git remote get-url origin`; the
commands only ask whether a remote exists and whether one is named `origin`. A
plan in a repo whose remote is not GitHub hits that assumption at three points:

- **`implement`** always opens a draft PR with `gh pr create`, and its body links
  to a `https://github.com/<owner>/<repo>/blob/...` URL. The skill has no no-PR
  variant; "no PR" is only recognized at close.
- **`implemented`** refuses while the feature branch has no upstream in a repo
  that has any remote (`_unpublished_work`: "<branch> has no upstream; push it
  with `git push -u origin <branch>`"). On a remote that rejects the feature
  branch, that refusal can never be satisfied.
- **`activate`** and `implement` step 3 end with `git push` of the base. On some
  remotes that push is not a backup but a publish into a live, shared document.

`close` already has a no-PR path (`finish --no-pr`, `pr: null`), and
`delete_remote_branch` skips a branch that `git ls-remote` does not list, so the
end of the lifecycle copes. The start and middle do not.

**Hosts this covers.** Generic examples, to be confirmed against each host's docs
before they are hard-coded:

| Remote | Limitation |
|---|---|
| A hosted document editor's git bridge (e.g. Overleaf, `git.overleaf.com`) | Single branch only; other branch pushes are rejected. Every push to it updates the live project collaborators are editing |
| GitLab, Gitea/Forgejo, Bitbucket | Branches are fine; review is a merge request through a different CLI (`glab`, `tea`) or none, so `gh` fails |
| A bare repo over SSH or a local path | Branches are fine; there is no review surface at all |
| No remote | Already handled: nothing to push, `implemented` counts only uncommitted changes |

### Scope

**1. Classify the remote.** A small `planners.remote` module returns a
`RemoteKind` for `origin`: `github`, `single-branch`, `other-forge`, `bare`, or
`none`. The URL host decides it (`github.com` and any `gh`-configured enterprise
host -> `github`; a short built-in table of known single-branch hosts ->
`single-branch`; known forges -> `other-forge`; anything else -> `bare`). A
repo-level override in config (`remote.kind = "..."`) wins over the table, so a
self-hosted forge or an unlisted bridge needs no release. The table is the one
place host knowledge lives; each entry carries a comment citing its source.

**2. `planners remote` (read-only).** Prints the kind, the URL host, and what
the lifecycle will do differently, e.g.

    origin: single-branch (git.example-editor.com)
      no PR: implement skips the draft PR; close uses the no-PR path
      no feature-branch push: implemented checks commits, not an upstream
      base push publishes live: activate will not suggest pushing

**3. `implemented` respects the kind.** For any kind other than `github`, the
upstream requirement in `_unpublished_work` is dropped for the feature branch
(uncommitted changes still block). For `github` nothing changes. `gh pr ready`
already runs only when a PR URL is recorded.

**4. Skill text branches on `planners remote`.**

- `implement`: run `planners remote` in step 2. For a non-`github` kind, skip
  step 6 (draft PR, `set-pr`), skip `git push -u origin <branch>` for
  `single-branch`, and say the plan will close through the no-PR path.
- `implement` step 3 and `activate`'s report: for `single-branch`, do not push
  the base as a routine step. Show the ahead count and ask, since the push lands
  in a live document.
- `close`: a non-`github` kind selects the no-PR path without the user having to
  say "no PR", and says so in the gate summary.
- `pipeline`: its "always opens a draft PR" note gains the same exception.

**5. Tests.** URL fixtures per kind (https and scp-style SSH, with and without
`.git`, enterprise host), the config override, `implemented` on a branch with no
upstream for each kind, and `planners remote` output. Fixtures use placeholder
hosts and `owner/repo`, never real projects.

### Order

1 -> 2 -> 3 -> 4 -> 5 (tests land with each step, not only at the end).

### Out of scope

- Opening merge requests on other forges (`glab`, `tea`). This plan only stops
  planners from assuming `gh`; supporting other review tools is a follow-up.
- Network probes. Classification reads the URL and config only; it never
  contacts the remote.

### Risks

- A host table goes stale as services change. The config override is the escape
  hatch, and `planners remote` makes the classification visible before it acts.
- Mis-classifying a GitHub remote as `other` would silently drop the upstream
  check. Default unknown `https` hosts to `bare` only after checking `gh`'s
  configured hosts, and print the kind in every command that branches on it.

## Log

- **2026-10-09T20:03:52-07:00** — Activated.
  - Branch: `feature/non-github-remotes`
  - Base: `dev` at `458ecf9`
  - Worktree: `.worktrees/non-github-remotes`
  - PR: pending
- **2026-10-09T20:06:50-07:00** — PR opened: https://github.com/gitronald/planners/pull/44
- **2026-10-09T20:08:05-07:00** — Steps 1-5 implemented.
  - `planners/remote.py`: `RemoteKind`, `classify`, `url_host`, `gh_hosts`,
    `effects`. The host table holds `git.overleaf.com` (single-branch, checked
    against Overleaf's git docs: "The Overleaf Git system does not support
    branching") and `gitlab.com`, `bitbucket.org`, `codeberg.org`, `gitea.com`,
    `git.sr.ht` (other-forge). `gh` hosts come from `GH_HOST` and the top-level
    keys of `hosts.yml` (`GH_CONFIG_DIR`, then `XDG_CONFIG_HOME/gh`, then
    `~/.config/gh`), parsed without a YAML dependency.
  - Decision: the override is the git config key `planners.remoteKind`. The
    repo had no config file to extend, and a git key works in any repo; an
    unknown value is ignored with a warning.
  - `planners remote [--json]` prints the kind, host, deciding rule, and
    effects. `implemented` drops the no-upstream refusal for every kind but
    `github` and prints `origin is <kind>: the branch needs no upstream`.
  - Skills: `implement` (steps 2, 3, 4, 6, 7), `close` (opening), `update`
    (activate, implemented), and `pipeline` (handoff contract) branch on
    `planners remote`. README and CHANGELOG updated.
  - Tests: `tests/test_remote.py` (URL forms, every kind, gh hosts, override,
    command output); `implemented` parametrized over kinds. The conftest now
    points `GH_CONFIG_DIR` at an empty directory so a developer's gh hosts do
    not leak in. The existing no-upstream test used a local bare repo as its
    "GitHub" remote and now pins `planners.remoteKind github`.
  - Checks: 546 passed, ruff and pyrefly clean.
- **2026-10-09T20:08:19-07:00** — Implemented: 5 commits ahead of `dev`.

## Handoff

State: steps 1-5 committed and pushed on `feature/non-github-remotes` (PR #44).

Open questions for the review gate:

1. A local-path or unknown-host SSH remote now classifies as `bare` and loses
   the upstream check that `implemented` applied before. That is the plan's
   rule, but it changes behavior for anyone using a self-hosted bare remote
   with PR-less review today. Accept, or keep the check for `bare`?
2. `finish --no-pr` still requires the base's upstream to contain the branch,
   so on a `single-branch` remote it forces the live publish before cleanup.
   Left unchanged here (the skill now asks before that push). Follow-up plan,
   or in scope?
3. The override is per-clone git config, not a committed file, so collaborators
   each set it. Acceptable for now?

Not verified: classification against a real enterprise GitHub host or a real
Overleaf project (fixtures only, by design: no network probes).
