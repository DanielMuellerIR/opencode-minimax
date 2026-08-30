#!/usr/bin/env bash
# One-minute demo: watch the agent fix a failing test, start to finish.
#
# It copies the tiny demo project to a throwaway directory (your repo stays untouched),
# runs the agent confined to that directory, and shows the before/after.
#
# Requires: opencode and git on PATH, and a MiniMax API key. Set $MINIMAX_API_KEY, or (macOS) store it
# once in the Keychain and the tool finds it automatically:
#   security add-generic-password -a "$USER" -s minimax-api-key -U -w
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
source "$here/_example-lib.sh"
demo_root="$(mktemp -d)"
repo="$demo_root/repo"
work="$demo_root/demo"
mkdir -p "$repo"
cp "$here/demo-project/"*.py "$repo/"
( cd "$repo" && git init -q && git add -A &&
  git -c user.name=opencode-minimax-demo -c user.email=demo@example.invalid commit -qm demo )
git -C "$repo" worktree add -f "$work" HEAD >/dev/null
trusted_git_dir="$(git -C "$repo" rev-parse --absolute-git-dir)"
base_commit="$(git -C "$repo" rev-parse HEAD)"

echo "== before: the test fails =="
( cd "$work" && python3 test_calc.py ) || true
echo

echo "== delegating the fix to MiniMax =="
task="Fix average() in calc.py: return 0.0 on empty input instead of raising. Keep it minimal; do not touch test_calc.py."
run_agent_supervised --dir "$work" "$task"
echo

echo "== the change the agent made =="
show_worktree_changes
echo

echo "The generated code has not been executed outside the agent sandbox."
if [ -t 0 ]; then
  printf "After reviewing the change above, run its test now? [y/N] "
  read -r answer
  case "$answer" in
    y|Y|yes|YES)
      echo "== after: run the test with a clean environment =="
      mkdir -p "$work/.test-home" "$work/.test-tmp"
      ( cd "$work" && env -i PATH="$PATH" HOME="$work/.test-home" \
          TMPDIR="$work/.test-tmp" python3 test_calc.py )
      ;;
  esac
fi
echo
echo "Demo directory: $demo_root  (delete when you are done)"
