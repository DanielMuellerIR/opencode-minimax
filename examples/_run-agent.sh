#!/usr/bin/env bash
# Internal launcher shared by all example scripts. It adds the macOS-only seatbelt
# flag on Darwin and preserves the wrapper's exit code on every platform.
set -u

here="$(cd "$(dirname "$0")" && pwd)"
if ! platform="$(uname -s)"; then
  echo "ERROR: could not determine the operating system; refusing to run without a sandbox decision" >&2
  exit 2
fi
case "$platform" in
  Darwin)
    exec python3 "$here/../minimax_agent.py" --sandbox "$@"
    ;;
  Linux)
    exec python3 "$here/../minimax_agent.py" "$@"
    ;;
  *)
    echo "ERROR: unsupported operating system '$platform'" >&2
    exit 2
    ;;
esac
