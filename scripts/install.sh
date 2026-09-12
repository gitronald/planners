#!/usr/bin/env bash
#
# install.sh — install planners into a consuming repo.
#
# Automates the per-repo install recipe from a multi-repo fleet rollout (its
# pilot phase, reused for the broader rollout): write the /planners dispatcher
# skillstub and the plan-files convention rule, wire the planners-validate
# pre-commit hook, and verify the CLI end to end. The plan-data standardization
# (git mv into .planners/plans/, the
# frontmatter transform, titles/status) is deliberately NOT automated here —
# those need human review (see the plan's pilot learnings).
#
# Two install modes, both first-class:
#
#   --local    (default) per-repo editable dev dependency, invoked as
#              `uv run planners`; wires the local validate hook. Needs the
#              target to be a uv project (pyproject.toml).
#   --global   CLI on PATH via `uv tool install`, one ~/.claude/skills/planners
#              holder serving every repo (bare `planners`). Works in non-uv repos.
#
# The planners source checkout is the repo containing this script, resolved at
# runtime — no hard-coded paths.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [--local|--global] [--force] [TARGET_REPO]

  --local    per-repo editable dev dep, `uv run planners` (default)
  --global   CLI on PATH (uv tool install) + one ~/.claude holder, bare `planners`
  --force    pass --force to `planners install` (overwrite a drifted holder)
  -h, --help show this help

TARGET_REPO defaults to the current directory.
EOF
}

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    ok: %s\n' "$*"; }
note() { printf '    note: %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

mode=local
force=0
target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --local)   mode=local ;;
    --global)  mode=global ;;
    --force)   force=1 ;;
    -h|--help) usage; exit 0 ;;
    --*)       die "unknown option: $1 (try --help)" ;;
    *)         [ -z "$target" ] || die "unexpected extra argument: $1"; target=$1 ;;
  esac
  shift
done

command -v uv >/dev/null 2>&1 || die "uv is required but not on PATH"

script_dir=$(cd "$(dirname "$0")" && pwd)
planners_root=$(cd "$script_dir/.." && pwd)
target=$(cd "${target:-.}" 2>/dev/null && pwd) || die "target repo not found: ${target:-.}"
git -C "$target" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || die "target is not a git repository: $target (the validate hook needs git)"

step "configuration"
note "planners source: $planners_root"
note "target repo:     $target"
note "install mode:    $mode"

force_arg=()
[ "$force" -eq 1 ] && force_arg=(--force)

if [ "$mode" = local ]; then
  [ -f "$target/pyproject.toml" ] \
    || die "local mode needs a uv project (no pyproject.toml in target); re-run with --global"
  # GNU `realpath --relative-to` is not portable (BSD/macOS lacks it); uv is
  # already a hard dependency, so compute the relative path with stdlib instead.
  rel=$(uv run --no-project python -c \
    'import os.path, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
    "$planners_root" "$target")
  step "adding planners as an editable dev dependency ($rel)"
  ( cd "$target" && uv add --dev --editable "$rel" )
  # Two explicit steps (add pre-commit, then activate the hook) so the step
  # list stays transparent; `planners install` itself never adds the dependency.
  step "ensuring pre-commit is available"
  ( cd "$target" && uv add --dev pre-commit )
  step "writing the /planners holder + rule + wiring the pre-commit hook"
  ( cd "$target" && uv run planners install --local "${force_arg[@]+"${force_arg[@]}"}" )
  step "activating the validate hook (uv run pre-commit install)"
  ( cd "$target" && uv run pre-commit install )
  inv=(uv run planners)
else
  if command -v planners >/dev/null 2>&1; then
    note "planners already on PATH ($(command -v planners)) — skipping uv tool install"
    note "(this may not be $planners_root; 'uv tool uninstall planners' then re-run to install from source)"
  else
    step "installing the planners CLI on PATH (uv tool install --editable)"
    uv tool install --editable "$planners_root"
  fi
  step "writing the global /planners holder + rule + wiring the pre-commit hook"
  ( cd "$target" && planners install "${force_arg[@]+"${force_arg[@]}"}" )
  step "activating the validate hook"
  if command -v pre-commit >/dev/null 2>&1; then
    ( cd "$target" && pre-commit install )
  else
    note "pre-commit not on PATH — the validate hook is wired but dormant;"
    note "install it ('uv tool install pre-commit') then run 'pre-commit install'"
  fi
  inv=(planners)
fi

step "verifying the CLI end to end"
(
  cd "$target"
  "${inv[@]}" --help >/dev/null              || die "planners --help failed"
  ok "planners --help"
  "${inv[@]}" schema PlanMetadata >/dev/null || die "planners schema PlanMetadata failed"
  ok "planners schema PlanMetadata"
  "${inv[@]}" index . >/dev/null             || die "planners index . failed"
  ok "planners index . -> .planners/README.md"
  if compgen -G ".planners/plans/*/plan.md" >/dev/null 2>&1; then
    "${inv[@]}" validate .planners/plans >/dev/null || die "planners validate .planners/plans failed"
    ok "planners validate .planners/plans"
  else
    note "no plans under .planners/plans yet — skipping validate"
    note "migrate with: git mv docs/plans/<NNN>-<slug>.md .planners/plans/<NNN>-<slug>/plan.md"
  fi
  # `install --check` now reports each generated artifact (holder + rule) on its
  # own line and exits non-zero if any is drifted/missing, so gate on the exit
  # code and surface the per-artifact status on one line either way.
  if check=$("${inv[@]}" install --check 2>&1); then
    ok "install --check: $(printf '%s' "$check" | tr '\n' ' ')"
  else
    die "install --check reported: $(printf '%s' "$check" | tr '\n' ' ')"
  fi
)

step "done — /planners is installed in $target"
note "next: migrate plan files into .planners/plans/ and standardize frontmatter (human-reviewed)"
