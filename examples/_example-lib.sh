#!/usr/bin/env bash
# Shared signal forwarding for examples that need to inspect or clean up after the agent.

run_agent_supervised() {
  _agent_pid=""

  _forward_agent_signal() {
    _signal="$1"
    _status="$2"
    trap - INT TERM HUP
    if [ -n "$_agent_pid" ]; then
      kill -s "$_signal" "$_agent_pid" 2>/dev/null || true
      wait "$_agent_pid" 2>/dev/null || true
    fi
    exit "$_status"
  }

  trap '_forward_agent_signal INT 130' INT
  trap '_forward_agent_signal TERM 143' TERM
  trap '_forward_agent_signal HUP 129' HUP
  "$here/_run-agent.sh" "$@" &
  _agent_pid=$!
  set +e
  wait "$_agent_pid"
  _agent_status=$?
  set -e
  _agent_pid=""
  trap - INT TERM HUP
  return "$_agent_status"
}

show_worktree_changes() {
  python3 "$here/_show-worktree-changes.py" \
    --git-dir "$trusted_git_dir" --work-tree "$work" --base "$base_commit"
}
