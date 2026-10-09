#!/usr/bin/env bash
# Description: time `planners validate` with and without --no-index on a synthetic repo.
#
# Usage: bench_validate.sh <scratch-dir> [plan-count] [runs]
#
# Builds <scratch-dir>/repo with <plan-count> minimal conformant plans and a
# fresh index, then reports the best of <runs> wall-clock times for each form,
# both as a directory argument (one root) and as one argument per plan file
# (how the pre-commit hook calls it). Run from the planners checkout so
# `uv run planners` resolves to the tree under test. Needs GNU date (%N).
set -euo pipefail

show_help() {
  echo "Usage: $0 <scratch-dir> [plan-count] [runs]"
  echo ""
  echo "Description: time planners validate with and without --no-index"
  echo ""
  echo "Arguments:"
  echo "  scratch-dir   new directory to build the synthetic repo in"
  echo "  plan-count    number of plans to generate (default 300)"
  echo "  runs          timed runs per form; the best is reported (default 5)"
  echo ""
  echo "Options:"
  echo "  -h, --help    Show this help"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi
[ $# -ge 1 ] || { echo "Error: missing <scratch-dir>" >&2; show_help >&2; exit 1; }

scratch=$1
count=${2:-300}
runs=${3:-5}
repo="$scratch/repo"
for n in "$count" "$runs"; do
  [[ "$n" =~ ^[1-9][0-9]*$ ]] || { echo "Error: plan-count and runs must be positive integers, got '$n'" >&2; exit 1; }
done

[ -e "$repo" ] && { echo "Error: refusing to reuse existing $repo" >&2; exit 1; }
mkdir -p "$repo/.planners/plans"
git -C "$repo" init -q

for i in $(seq 0 $((count - 1))); do
  id=$(printf '%03d' "$i")
  dir="$repo/.planners/plans/$id-bench-$i"
  mkdir -p "$dir"
  cat >"$dir/plan.md" <<EOF
---
id: $i
slug: bench-$i
status: draft
branch:
created: 2026-01-01T00:00:00-08:00
concluded:
pr:
---

# Benchmark plan $i

## Plan

Synthetic.
EOF
done

uv run planners index "$repo" >/dev/null

best() {
  local best_ms=
  for _ in $(seq "$runs"); do
    local start end ms
    start=$(date +%s%N)
    # A failing command would be timed on its error path, so stop instead.
    "$@" >/dev/null 2>&1 || { echo "Error: command failed: $*" >&2; return 1; }
    end=$(date +%s%N)
    ms=$(((end - start) / 1000000))
    if [ -z "$best_ms" ] || [ "$ms" -lt "$best_ms" ]; then best_ms=$ms; fi
  done
  echo "$best_ms"
}

files=("$repo"/.planners/plans/*/plan.md)
# Assign before echoing: a failure inside $(...) in an echo argument is not
# caught by set -e, but one in a plain assignment is.
dir_index=$(best uv run planners validate "$repo/.planners/plans")
dir_noindex=$(best uv run planners validate --no-index "$repo/.planners/plans")
files_index=$(best uv run planners validate "${files[@]}")
files_noindex=$(best uv run planners validate --no-index "${files[@]}")
echo "plans=$count runs=$runs (best wall-clock ms)"
echo "dir   with index: $dir_index"
echo "dir   --no-index: $dir_noindex"
echo "files with index: $files_index"
echo "files --no-index: $files_noindex"
