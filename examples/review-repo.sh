#!/usr/bin/env bash
# Read-only code review: the agent runs against a throwaway git worktree instead of your
# checkout. How strong that boundary is depends on the platform:
#   - macOS: the run is additionally confined with --sandbox, so the operating system
#     refuses every write outside the worktree. That matters here, because the worktree
#     shares its git directory with the original repository.
#   - other systems: the worktree keeps the review off your working tree, but nothing stops
#     a misdirected agent from writing to absolute paths outside it. Wrap the call in an
#     approved bubblewrap/firejail setup if you need that guarantee enforced.
#
# Usage:  examples/review-repo.sh /path/to/your/repo
# Requires: opencode on PATH; a MiniMax API key via $MINIMAX_API_KEY or the macOS Keychain
# (store it with: security add-generic-password -a "$USER" -s minimax-api-key -w).
set -euo pipefail

repo="${1:?usage: review-repo.sh /path/to/your/repo}"
here="$(cd "$(dirname "$0")" && pwd)"
wt="$(mktemp -d)/wt"
task="Review this repository for real bugs. For each finding give file:line and a concrete fix. Do not change any files."

# Always remove the throwaway worktree, even on error or Ctrl-C. The trap is set
# BEFORE creating the worktree so an abort right after creation cannot leave it
# behind; if the worktree does not exist yet, the remove fails silently.
trap 'git -C "$repo" worktree remove --force "$wt" 2>/dev/null || true' EXIT
git -C "$repo" worktree add -f "$wt" HEAD >/dev/null

if [ "$(uname -s)" = "Darwin" ]; then
  python3 "$here/../minimax_agent.py" --dir "$wt" --sandbox "$task"
else
  # --sandbox uses the macOS seatbelt and would abort here; see the note at the top.
  python3 "$here/../minimax_agent.py" --dir "$wt" "$task"
fi
