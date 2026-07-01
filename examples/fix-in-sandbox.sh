#!/usr/bin/env bash
# Apply a fix with the agent, OS-confined to a throwaway git worktree you can review
# before merging anything into your real branch.
#
# Usage:  examples/fix-in-sandbox.sh /path/to/your/repo "the task for the agent"
# Requires: opencode on PATH; macOS (the --sandbox flag); a MiniMax API key via
# $MINIMAX_API_KEY or the macOS Keychain (security add-generic-password -a "$USER" -s minimax-api-key -w).
set -euo pipefail

repo="${1:?usage: fix-in-sandbox.sh /path/to/your/repo \"the task\"}"
task="${2:?provide the task as the second argument}"
here="$(cd "$(dirname "$0")" && pwd)"
wt="$(mktemp -d)/wt"

git -C "$repo" worktree add -f "$wt" HEAD >/dev/null
python3 "$here/../minimax_agent.py" --dir "$wt" --sandbox "$task"

echo
echo "== review this diff; if it is good, cherry-pick it into your branch =="
git -C "$wt" --no-pager diff
echo
echo "Worktree: $wt"
echo "Remove it with:  git -C '$repo' worktree remove --force '$wt'"
