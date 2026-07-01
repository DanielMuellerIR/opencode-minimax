#!/usr/bin/env python3
"""Run MiniMax (or any Anthropic-compatible model) as an agentic coder via OpenCode.

Delegate well-specified coding tasks to a strong-but-cheap model to cut your bill for
frontier subscriptions, while keeping a review-before-merge safety loop.

Why this exists: OpenCode already supports custom providers, but pointing it at MiniMax
agentically has four non-obvious traps that make it look like "the model can't write
files" when the real cause is the harness. This script bakes in the fixes. See README.md.

API key: set the MINIMAX_API_KEY environment variable, or pass
    --key-command "<shell command that prints the key>"
(e.g. macOS Keychain: --key-command "security find-generic-password -s minimax-api-key -w").

Quick start:
    export MINIMAX_API_KEY=...
    python3 minimax_agent.py --dir ./my-project "Extract the URL parser from utils.py into url.py."

Safety: OpenCode's `run` edits files under --dir WITHOUT asking. For read-only work
(audits, reviews) run against a throwaway git worktree; for write tasks add --sandbox
(macOS) to confine writes to --dir at the OS level. Never point --dir at your home dir.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = "MiniMax-M3"
DEFAULT_BASE_URL = "https://api.minimax.io/anthropic/v1"  # @ai-sdk/anthropic appends /messages
DEFAULT_CONTEXT = 1_000_000
DEFAULT_MAX_OUTPUT = 16_384
DEFAULT_TIMEOUT = 300
DEFAULT_RETRIES = 1
DEFAULT_SYSTEM_PROMPT = os.path.join(_HERE, "system-prompt.md")
DEFAULT_KEYCHAIN_SERVICE = "minimax-api-key"  # macOS Keychain fallback (see get_api_key)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def get_api_key(key_command):
    """Return the API key, trying three sources in order:

    1. `--key-command` output (a command that prints the key — keeps the secret out of your
       shell history and process arguments, e.g. reading it from a password manager);
    2. the `MINIMAX_API_KEY` environment variable;
    3. on macOS, a Keychain generic-password entry named `minimax-api-key` (create it once
       with: `security add-generic-password -a "$USER" -s minimax-api-key -w`).
    """
    if key_command:
        r = subprocess.run(key_command, shell=True, capture_output=True, text=True)
        key = (r.stdout or "").strip()
        if key:
            return key
        log("key-command produced no output; falling back to MINIMAX_API_KEY / Keychain")
    env = (os.environ.get("MINIMAX_API_KEY") or "").strip()
    if env:
        return env
    if sys.platform == "darwin":
        r = subprocess.run(
            ["security", "find-generic-password", "-s", DEFAULT_KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True)
        key = (r.stdout or "").strip()
        if key:
            log("using API key from the macOS Keychain (service '%s')" % DEFAULT_KEYCHAIN_SERVICE)
            return key
    return None


def build_seatbelt_profile(write_dirs):
    """macOS seatbelt profile: allow everything EXCEPT writing; permit writes only under
    write_dirs plus the system temp dirs (which many tools need for scratch/cache)."""
    system_writable = [
        '(subpath "/private/var/folders")',   # macOS per-user temp/cache
        '(subpath "/private/tmp")',
        '(subpath "/private/var/tmp")',
        '(literal "/dev/null")', '(literal "/dev/zero")',
        '(literal "/dev/stdout")', '(literal "/dev/stderr")',
        '(subpath "/dev/fd")', '(literal "/dev/random")',
    ]
    allow = "\n  ".join(['(subpath "%s")' % d for d in write_dirs] + system_writable)
    return (
        "(version 1)\n"
        "(allow default)\n"        # reading, exec and network stay open so the tool can work
        "(deny file-write*)\n"     # ... but no writing/deleting
        "(allow file-write*\n  %s)\n" % allow  # ... except here
    )


def run_with_timeout(cmd, env, timeout, retries):
    """Run OpenCode with a timeout and retry against transient start-up stalls.

    OpenCode occasionally hangs at session start (a small title/provider-init LLM call
    blocks) while the API itself is healthy. The stall happens BEFORE the first tool call,
    i.e. before any file change, so a restart is safe. Each attempt runs in its own process
    group (start_new_session) so the timeout also kills OpenCode's child processes (bun);
    otherwise the model outlives the killed parent. timeout <= 0 disables timeout/retry."""
    if not timeout or timeout <= 0:
        return subprocess.run(cmd, env=env).returncode
    attempts = retries + 1
    for i in range(1, attempts + 1):
        proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            log("attempt %d/%d aborted after %ds%s"
                % (i, attempts, timeout, " — retrying" if i < attempts else " — giving up"))
    return 124


def run(task, work_dir, key, *, model, base_url, context, max_output,
        system_prompt, timeout, retries, sandbox, variant=None):
    """Run one agentic task and return OpenCode's exit code."""
    # Isolated OpenCode home (config/data/cache/state) under the system temp dir. Three
    # reasons, all hard-won:
    #  1) Sandbox compatibility: OpenCode keeps its SQLite state DB under
    #     ~/.local/share/opencode by default. If you confine writes to the work dir only
    #     (see --sandbox), that DB write is denied and OpenCode crashes IMMEDIATELY
    #     (PRAGMA wal_checkpoint) before the model even runs — the classic "it won't write"
    #     trap. The system temp dir is always writable inside the sandbox, so putting the
    #     XDG home here makes the confined write path work.
    #  2) Plugin immunity: a global ~/.config/opencode may load an "@latest" plugin that
    #     revalidates against npm on every start and blocks OpenCode when npm is slow. An
    #     isolated XDG_CONFIG_HOME bypasses the global config completely.
    #  3) Clean system prompt: inject a short task-focused prompt instead of whatever global
    #     instructions your normal OpenCode setup carries.
    home = tempfile.mkdtemp(prefix="opencode-minimax-")
    os.makedirs(os.path.join(home, "config"), exist_ok=True)  # empty -> global config off
    instructions = [system_prompt] if system_prompt and os.path.isfile(system_prompt) else []
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "instructions": instructions,
        "provider": {"minimax": {
            "npm": "@ai-sdk/anthropic",
            "options": {
                "baseURL": base_url,
                "apiKey": key,  # -> x-api-key header
                # MiniMax expects a Bearer token; anthropic-version is a required header
                # of the Messages API.
                "headers": {"Authorization": "Bearer " + key,
                            "anthropic-version": "2023-06-01"},
            },
            # Declare the context window explicitly: OpenCode pulls NO limits from
            # models.dev for a custom provider and would otherwise assume a conservative
            # default and compact the history far too early instead of using the full window.
            "models": {model: {"limit": {"context": context, "output": max_output}}},
        }},
    }
    cfg_path = os.path.join(home, "config.json")  # holds the key in clear text -> 0700 temp home
    try:
        os.chmod(home, 0o700)
        with open(cfg_path, "w") as fh:
            json.dump(cfg, fh)
        os.chmod(cfg_path, 0o600)
        env = dict(os.environ,
                   OPENCODE_CONFIG=cfg_path,
                   XDG_CONFIG_HOME=os.path.join(home, "config"),
                   XDG_DATA_HOME=os.path.join(home, "data"),
                   XDG_CACHE_HOME=os.path.join(home, "cache"),
                   XDG_STATE_HOME=os.path.join(home, "state"))
        cmd = ["opencode", "run", "-m", "minimax/" + model, "--dir", work_dir]
        if variant:
            cmd += ["--variant", variant]
        cmd.append(task)
        if sandbox:
            if sys.platform != "darwin":
                log("ERROR: --sandbox uses macOS seatbelt and only works on macOS. "
                    "On Linux, wrap this command with bubblewrap/firejail instead.")
                return 2
            profile = build_seatbelt_profile([os.path.realpath(work_dir)])
            prof_path = os.path.join(home, "profile.sb")
            with open(prof_path, "w") as pf:
                pf.write(profile)
            cmd = ["sandbox-exec", "-f", prof_path] + cmd
        log("-> MiniMax agentic: model %s, dir %s%s"
            % (model, work_dir, " [sandboxed]" if sandbox else ""))
        return run_with_timeout(cmd, env, timeout, retries)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", nargs="?",
                    help="the task for the agent; if omitted, read from stdin")
    ap.add_argument("--dir", required=True,
                    help="project directory OpenCode works in (never your home directory)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="default %s" % DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="Anthropic-compatible endpoint (default MiniMax; works with any "
                         "such provider)")
    ap.add_argument("--context", type=int, default=DEFAULT_CONTEXT,
                    help="context window to declare (default %d)" % DEFAULT_CONTEXT)
    ap.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    ap.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT,
                    help="instructions file injected into every run (default: bundled)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="seconds before a stalled run is killed and retried (0 = off)")
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    ap.add_argument("--sandbox", action="store_true",
                    help="macOS only: confine writes/deletes to --dir at the OS level")
    ap.add_argument("--key-command",
                    help="shell command that prints the API key (else $MINIMAX_API_KEY)")
    ap.add_argument("--variant", help="OpenCode agent variant (optional)")
    args = ap.parse_args(argv)

    task = args.task if args.task is not None else sys.stdin.read().strip()
    if not task:
        ap.error("no task given (pass it as an argument or via stdin)")
    if not os.path.isdir(args.dir):
        ap.error("--dir does not exist: %s" % args.dir)
    key = get_api_key(args.key_command)
    if not key:
        log("ERROR: no API key. Set MINIMAX_API_KEY, pass --key-command, or (macOS) store it "
            "in the Keychain: security add-generic-password -a \"$USER\" -s minimax-api-key -w")
        return 2
    return run(task, args.dir, key,
               model=args.model, base_url=args.base_url, context=args.context,
               max_output=args.max_output, system_prompt=args.system_prompt,
               timeout=args.timeout, retries=args.retries, sandbox=args.sandbox,
               variant=args.variant)


if __name__ == "__main__":
    sys.exit(main())
