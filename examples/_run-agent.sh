#!/usr/bin/env bash
# Internal launcher shared by all example scripts. It adds the macOS-only seatbelt
# flag on Darwin and preserves the wrapper's exit code on every platform.
set -u

here="$(cd "$(dirname "$0")" && pwd)"
if [ "$(uname -s)" = "Darwin" ]; then
  exec python3 "$here/../minimax_agent.py" --sandbox "$@"
else
  exec python3 "$here/../minimax_agent.py" "$@"
fi
