#!/usr/bin/env bash
# One-minute demo: watch the agent fix a failing test, start to finish.
#
# It copies the tiny demo project to a throwaway directory (your repo stays untouched),
# runs the agent confined to that directory, and shows the before/after.
#
# Requires: opencode on PATH, and an API key in MINIMAX_API_KEY.
#   export MINIMAX_API_KEY=...   # then: examples/run-demo.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)/demo"
mkdir -p "$work"
cp "$here/demo-project/"*.py "$work/"
( cd "$work" && git init -q && git add -A && git commit -qm demo )

echo "== before: the test fails =="
( cd "$work" && python3 test_calc.py ) || true
echo

echo "== delegating the fix to MiniMax (writes confined to the demo dir) =="
python3 "$here/../minimax_agent.py" --dir "$work" --sandbox \
  "Fix average() in calc.py: return 0.0 on empty input instead of raising. Keep it minimal; do not touch test_calc.py."
echo

echo "== the change the agent made =="
git -C "$work" --no-pager diff
echo

echo "== after: the test passes =="
( cd "$work" && python3 test_calc.py )
echo
echo "Demo directory: $work  (delete when you are done)"
