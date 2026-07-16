#!/usr/bin/env bash
# Read-only code review: run the agent against a throwaway git worktree so it physically
# cannot change your working tree, whatever it does.
#
# Usage:  examples/review-repo.sh /path/to/your/repo
# Requires: opencode on PATH; a MiniMax API key via $MINIMAX_API_KEY or the macOS Keychain
# (store it with: security add-generic-password -a "$USER" -s minimax-api-key -w).
set -euo pipefail

repo="${1:?usage: review-repo.sh /path/to/your/repo}"
here="$(cd "$(dirname "$0")" && pwd)"
wt="$(mktemp -d)/wt"

# Always remove the throwaway worktree, even on error or Ctrl-C. The trap is set
# BEFORE creating the worktree so an abort right after creation cannot leave it
# behind; if the worktree does not exist yet, the remove fails silently.
trap 'git -C "$repo" worktree remove --force "$wt" 2>/dev/null || true' EXIT
git -C "$repo" worktree add -f "$wt" HEAD >/dev/null

python3 "$here/../minimax_agent.py" --dir "$wt" \
  "Review this repository for real bugs. For each finding give file:line and a concrete fix. Do not change any files."
