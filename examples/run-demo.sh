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
work="$(mktemp -d)/demo"
mkdir -p "$work"
cp "$here/demo-project/"*.py "$work/"
( cd "$work" && git init -q && git add -A &&
  git -c user.name=opencode-minimax-demo -c user.email=demo@example.invalid commit -qm demo )

echo "== before: the test fails =="
( cd "$work" && python3 test_calc.py ) || true
echo

echo "== delegating the fix to MiniMax =="
task="Fix average() in calc.py: return 0.0 on empty input instead of raising. Keep it minimal; do not touch test_calc.py."
"$here/_run-agent.sh" --dir "$work" "$task"
echo

echo "== the change the agent made =="
git -C "$work" --no-pager diff
echo

echo "== after: the test passes =="
( cd "$work" && python3 test_calc.py )
echo
echo "Demo directory: $work  (delete when you are done)"
