#!/usr/bin/env bash
# Apply a fix with the agent in a throwaway git worktree you can review before
# merging anything into your real branch. Only committed HEAD is copied, so commit
# your intended input first. On macOS, seatbelt additionally confines writes.
#
# Usage:  examples/fix-in-sandbox.sh /path/to/your/repo "the task for the agent"
# Requires: opencode and git on PATH; a MiniMax API key via $MINIMAX_API_KEY or the
# macOS Keychain (security add-generic-password -a "$USER" -s minimax-api-key -U -w).
set -euo pipefail

repo="${1:?usage: fix-in-sandbox.sh /path/to/your/repo \"the task\"}"
task="${2:?provide the task as the second argument}"
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/_example-lib.sh"

if [ -n "$(git -C "$repo" status --porcelain)" ]; then
  echo "ERROR: the source repository has uncommitted changes; commit them first" >&2
  exit 2
fi
wt="$(mktemp -d)/wt"
git -C "$repo" worktree add -f "$wt" HEAD >/dev/null
work="$wt"
trusted_git_dir="$(git -C "$repo" rev-parse --absolute-git-dir)"
base_commit="$(git -C "$repo" rev-parse HEAD)"
rc=0
run_agent_supervised --dir "$wt" "$task" || rc=$?

echo
if [ "$rc" -eq 124 ]; then
  echo "The run stopped after output went quiet; inspect the partial work below."
elif [ "$rc" -ne 0 ]; then
  echo "The agent exited with code $rc; the worktree is retained for inspection."
fi
echo "== review this diff; if good, commit it here and cherry-pick that commit =="
show_worktree_changes
echo
echo "Worktree: $wt"
echo "Remove it with:  git -C '$repo' worktree remove --force '$wt'"
exit "$rc"
