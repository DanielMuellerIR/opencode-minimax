#!/usr/bin/env python3
"""Run MiniMax (or any Anthropic-compatible model) as an agentic coder via OpenCode.

Delegate well-specified coding tasks to a strong-but-cheap model to cut your bill for
frontier subscriptions, while keeping a review-before-merge safety loop.

Why this exists: OpenCode already supports custom providers, but pointing it at MiniMax
agentically has four non-obvious traps that make it look like "the model can't write
files" when the real cause is the harness. This script bakes in the fixes. See README.md.

API key for MiniMax: set the MINIMAX_API_KEY environment variable, or pass
    --key-command "<shell command that prints the key>"
For a custom --base-url, --key-command is required so a MiniMax credential is never
implicitly sent to another provider.

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
import threading
import time

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


def uses_default_base_url(base_url):
    """Treat an optional trailing slash as the same MiniMax endpoint."""
    return base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/")


def get_keychain_account():
    """Return the effective login account used for the Keychain entry."""
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError):
        return (os.environ.get("USER") or "").strip()


def get_api_key(key_command, base_url=DEFAULT_BASE_URL):
    """Return the API key, trying three sources in order:

    1. `--key-command` output (a command that prints the key — keeps the secret out of your
       shell history and process arguments, e.g. reading it from a password manager);
    2. for the default MiniMax endpoint only, the `MINIMAX_API_KEY` environment variable;
    3. for the default endpoint on macOS, the current account's Keychain generic-password
       entry named `minimax-api-key` (create it once with:
       `security add-generic-password -a "$USER" -s minimax-api-key -w`).

    A custom endpoint deliberately accepts only `--key-command`: provider-specific
    credentials must be selected explicitly rather than inheriting a MiniMax key.
    """
    if key_command:
        r = subprocess.run(key_command, shell=True, capture_output=True, text=True)
        key = (r.stdout or "").strip()
        if key:
            return key
        if uses_default_base_url(base_url):
            log("key-command produced no output; falling back to MINIMAX_API_KEY / Keychain")
        else:
            log("key-command produced no output; custom endpoints have no implicit key fallback")
            return None
    if not uses_default_base_url(base_url):
        return None
    env = (os.environ.get("MINIMAX_API_KEY") or "").strip()
    if env:
        return env
    if sys.platform == "darwin":
        account = get_keychain_account()
        if not account:
            return None
        r = subprocess.run(
            ["security", "find-generic-password", "-a", account,
             "-s", DEFAULT_KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True)
        key = (r.stdout or "").strip()
        if key:
            log("using API key from the macOS Keychain (account '%s', service '%s')"
                % (account, DEFAULT_KEYCHAIN_SERVICE))
            return key
    return None


def build_seatbelt_profile(write_dirs):
    """macOS seatbelt profile: allow everything EXCEPT writing; permit writes only under
    write_dirs plus a few harmless device files.

    Callers pass exactly two directories: the work dir and this run's private temp home
    (see run(), which also points TMPDIR/TMP/TEMP at it). The system temp dirs as a whole
    are deliberately NOT writable — that would let a confined run change or delete the
    scratch and cache files of every other process running under the same account, which
    is not what "writes are confined to --dir" promises."""
    system_writable = [
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


def install_termination_handlers():
    """Let SIGTERM/SIGHUP unwind the program instead of ending it on the spot.

    Python's default action for those signals stops the process immediately: no `finally`
    runs, so the temp home with the API key in clear text stays on disk and OpenCode keeps
    working in the background. Raising SystemExit from the handler unwinds through the
    cleanup paths instead. SIGINT (Ctrl-C) already raises KeyboardInterrupt and unwinds
    the same way, so it needs no handler."""
    def bail_out(signum, _frame):
        raise SystemExit(128 + signum)  # shell convention for "killed by signal N"

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue                       # not available on this platform
        try:
            signal.signal(sig, bail_out)
        except (OSError, ValueError):
            pass                           # e.g. imported and called off the main thread


def kill_process_group(proc, grace=5):
    """Kill one attempt's whole process group and wait for it to be gone.

    start_new_session (see run_with_timeout) puts OpenCode and its children (bun) in their
    own process group, so a signal aimed at this wrapper never reaches them — they have to
    be shot down explicitly, or the model keeps editing files after the abort. SIGTERM
    first so OpenCode can shut down cleanly; whatever survives the grace period gets
    SIGKILL."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            proc.poll()                    # already gone: collect it so no zombie is left
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            # SIGTERM ignored, or a child stuck in uninterruptible I/O — escalate once.
            continue
    log("process group still not gone after SIGKILL; continuing anyway")


def _forward(stream, sink, seen):
    """Pass one output stream of the child through unchanged and note when it last spoke.

    Runs in its own thread. `seen` is the shared progress record read by _one_attempt."""
    while True:
        try:
            chunk = stream.read1(65536)    # returns as soon as anything is there
        except (OSError, ValueError):
            return                         # pipe closed while we were reading
        if not chunk:
            return                         # end of output: the child is done writing
        seen["at"] = time.monotonic()
        seen["any"] = True
        try:
            sink.write(chunk)
            sink.flush()
        except (OSError, ValueError):
            return


def _one_attempt(cmd, env, timeout):
    """Run OpenCode once. Returns (exit code, "did it produce any output?").

    The exit code is None when the run was killed for staying silent for `timeout`
    seconds. Output is piped through this process so silence is measurable at all;
    it is written on to our own stdout/stderr as it arrives."""
    proc = subprocess.Popen(cmd, env=env, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    seen = {"at": time.monotonic(), "any": False}
    pumps = [threading.Thread(target=_forward, args=(src, sink, seen), daemon=True)
             for src, sink in ((proc.stdout, sys.stdout.buffer),
                               (proc.stderr, sys.stderr.buffer))]
    for pump in pumps:
        pump.start()
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return rc, seen["any"]
            if time.monotonic() - seen["at"] >= timeout:
                kill_process_group(proc)
                return None, seen["any"]
            time.sleep(0.2)
    except BaseException:
        # Ctrl-C, SIGTERM/SIGHUP (see install_termination_handlers) or an internal error:
        # never leave OpenCode running behind our back.
        kill_process_group(proc)
        raise
    finally:
        for pump in pumps:
            pump.join(timeout=5)           # let the last output through
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass


def run_with_timeout(cmd, env, timeout, retries):
    """Run OpenCode, watching its output so that only a stalled START gets retried.

    OpenCode occasionally hangs at session start (a small title/provider-init LLM call
    blocks) while the API itself is healthy. The stall happens BEFORE the first tool call,
    i.e. before any file change, so a restart is safe.

    `timeout` therefore limits SILENCE, not the total runtime: a long task keeps running
    as long as OpenCode keeps printing. Only a run that says nothing for `timeout` seconds
    is killed — and it is restarted only if it never said anything at all. A run that had
    already started may have changed files, so it ends with exit code 124 and no retry;
    review the work dir before running again.

    Each attempt runs in its own process group (start_new_session) so a kill also gets
    OpenCode's child processes (bun); otherwise the model outlives the killed parent.
    timeout <= 0 disables timeout/retry and leaves the terminal to OpenCode directly."""
    if not timeout or timeout <= 0:
        proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        try:
            return proc.wait()
        except BaseException:
            kill_process_group(proc)
            raise
    attempts = retries + 1
    for i in range(1, attempts + 1):
        rc, produced_output = _one_attempt(cmd, env, timeout)
        if rc is not None:
            return rc
        if produced_output:
            log("no output for %ds, but the run had already started — killed without a "
                "retry (exit 124); check the work dir before starting over" % timeout)
            return 124
        log("attempt %d/%d aborted after %ds without any output%s"
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
    #     trap. This directory is one of the two paths the sandbox profile makes writable
    #     (the other is the work dir), so putting the XDG home here makes that path work.
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
        scratch = os.path.join(home, "tmp")
        os.makedirs(scratch, exist_ok=True)
        env = dict(os.environ,
                   OPENCODE_CONFIG=cfg_path,
                   XDG_CONFIG_HOME=os.path.join(home, "config"),
                   XDG_DATA_HOME=os.path.join(home, "data"),
                   XDG_CACHE_HOME=os.path.join(home, "cache"),
                   XDG_STATE_HOME=os.path.join(home, "state"),
                   # Every tool's scratch files land inside this run's own temp home, which
                   # goes away with it. Under --sandbox that home and --dir are the only
                   # writable places, so a redirected TMPDIR is what keeps tools working
                   # without opening up the shared system temp dirs.
                   TMPDIR=scratch, TMP=scratch, TEMP=scratch)
        if not uses_default_base_url(base_url):
            # Even when the custom provider uses its explicit key-command value,
            # do not expose an unrelated MiniMax key to OpenCode or its tools.
            env.pop("MINIMAX_API_KEY", None)
        cmd = ["opencode", "run", "-m", "minimax/" + model, "--dir", work_dir]
        if variant:
            cmd += ["--variant", variant]
        cmd.append(task)
        if sandbox:
            if sys.platform != "darwin":
                log("ERROR: --sandbox uses macOS seatbelt and only works on macOS. "
                    "On Linux, wrap this command with bubblewrap/firejail instead.")
                return 2
            # realpath: the temp home lives under /var/folders, which is a symlink to
            # /private/var/folders — seatbelt only understands the resolved path.
            profile = build_seatbelt_profile(
                [os.path.realpath(work_dir), os.path.realpath(home)])
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
    ap.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT,
                    help="max output tokens to declare (default %d)" % DEFAULT_MAX_OUTPUT)
    ap.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT,
                    help="instructions file injected into every run (default: bundled)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="seconds of silence before a stalled run is killed; a run that "
                         "keeps printing is never cut off (0 = off)")
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                    help="restarts after a run that stalled before printing anything "
                         "(default %d); a run that had already started is never "
                         "restarted" % DEFAULT_RETRIES)
    ap.add_argument("--sandbox", action="store_true",
                    help="macOS only: confine writes/deletes at the OS level to --dir and "
                         "the run's own temp dir (removed when the run ends)")
    ap.add_argument("--key-command",
                    help="shell command that prints the API key (required for custom "
                         "--base-url; default MiniMax endpoint also tries $MINIMAX_API_KEY)")
    ap.add_argument("--variant", help="OpenCode agent variant (optional)")
    args = ap.parse_args(argv)
    install_termination_handlers()  # so an abort takes OpenCode and the key file with it

    task = args.task if args.task is not None else sys.stdin.read().strip()
    if not task:
        ap.error("no task given (pass it as an argument or via stdin)")
    if not os.path.isdir(args.dir):
        ap.error("--dir does not exist: %s" % args.dir)
    key = get_api_key(args.key_command, args.base_url)
    if not key:
        if uses_default_base_url(args.base_url):
            log("ERROR: no API key. Set MINIMAX_API_KEY, pass --key-command, or (macOS) "
                "store it in the Keychain: security add-generic-password -a \"$USER\" "
                "-s minimax-api-key -w")
        else:
            log("ERROR: a custom --base-url requires an explicit provider credential via "
                "--key-command; MINIMAX_API_KEY and the MiniMax Keychain entry are ignored")
        return 2
    return run(task, args.dir, key,
               model=args.model, base_url=args.base_url, context=args.context,
               max_output=args.max_output, system_prompt=args.system_prompt,
               timeout=args.timeout, retries=args.retries, sandbox=args.sandbox,
               variant=args.variant)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl-C: the cleanup already ran on the way out, so report it plainly
        # instead of dumping a traceback.
        log("aborted (Ctrl-C)")
        sys.exit(130)
