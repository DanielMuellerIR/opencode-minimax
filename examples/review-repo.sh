#!/usr/bin/env bash
# Read-only code review: the agent runs against a throwaway git worktree instead of your
# checkout. How strong that boundary is depends on the platform:
#   - macOS: the run is additionally confined with --sandbox, so the operating system
#     refuses every write outside the worktree. That matters here, because the worktree
#     shares its git directory with the original repository.
#   - other systems: the worktree keeps the review off your working tree, but nothing stops
#     a misdirected agent from writing to absolute paths outside it. Wrap the call in an
#     approved bubblewrap/firejail setup if you need that guarantee enforced.
# The worktree contains committed HEAD only. Commit the state you want reviewed first.
# Under macOS seatbelt, the shared Git directory stays read-only as part of the safety
# boundary, so Git operations that write metadata fail; the review task itself is read-only.
#
# Usage:  examples/review-repo.sh /path/to/your/repo
# Requires: opencode on PATH; a MiniMax API key via $MINIMAX_API_KEY or the macOS Keychain
# (store it with: security add-generic-password -a "$USER" -s minimax-api-key -U -w).
set -euo pipefail

repo="${1:?usage: review-repo.sh /path/to/your/repo}"
here="$(cd "$(dirname "$0")" && pwd)"
task="Review this repository for real bugs. For each finding give file:line and a concrete fix. Do not change any files."

if [ -n "$(git -C "$repo" status --porcelain)" ]; then
  echo "ERROR: the source repository has uncommitted changes; commit them first" >&2
  exit 2
fi
wt="$(mktemp -d)/wt"
# Always remove the registered throwaway worktree, even on error or Ctrl-C. The trap is
# installed before `worktree add`, so an abort immediately after registration is covered.
trap 'git -C "$repo" worktree remove --force "$wt" 2>/dev/null || true' EXIT
git -C "$repo" worktree add -f "$wt" HEAD >/dev/null

# codereview-ok: The shared Git directory remains read-only intentionally; this task only
# reads files and reports findings, while the worktree is discarded afterward (2026-08-20).
"$here/_run-agent.sh" --dir "$wt" "$task"
