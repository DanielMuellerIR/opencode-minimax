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
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = "MiniMax-M3"
DEFAULT_BASE_URL = "https://api.minimax.io/anthropic/v1"  # @ai-sdk/anthropic appends /messages
DEFAULT_CONTEXT = 1_000_000
DEFAULT_MAX_OUTPUT = 16_384
DEFAULT_TIMEOUT = 300
DEFAULT_RETRIES = 1
KEY_COMMAND_TIMEOUT = 30
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

    1. `--key-command` output (exactly one non-empty line within 30 seconds; a failure is
       final and never falls back to an unrelated credential source);
    2. for the default MiniMax endpoint only, the `MINIMAX_API_KEY` environment variable;
    3. for the default endpoint on macOS, the current account's Keychain generic-password
       entry named `minimax-api-key` (create it once with:
       `security add-generic-password -a "$USER" -s minimax-api-key -U -w`).

    A custom endpoint deliberately accepts only `--key-command`: provider-specific
    credentials must be selected explicitly rather than inheriting a MiniMax key.
    """
    if key_command:
        try:
            r = subprocess.run(key_command, shell=True, capture_output=True, text=True,
                               timeout=KEY_COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            log("ERROR: key-command did not finish within %d seconds" % KEY_COMMAND_TIMEOUT)
            return None
        if r.returncode != 0:
            detail = " ".join((r.stderr or "").split())[:300]
            log("ERROR: key-command failed with exit code %d%s"
                % (r.returncode, ": " + detail if detail else ""))
            return None
        lines = [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]
        if len(lines) != 1:
            log("ERROR: key-command must print exactly one non-empty line; got %d" % len(lines))
            return None
        key = lines[0]
        if any(ord(char) < 32 or ord(char) == 127 for char in key):
            log("ERROR: key-command output contains a control character")
            return None
        return key
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


def _sbpl_string(value):
    """Quote one path for an SBPL string without allowing rule injection."""
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("sandbox paths must not contain control characters")
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


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
        '(literal "/dev/tty")', '(regex #"^/dev/ttys[0-9]*$")',
    ]
    allow = "\n  ".join(["(subpath %s)" % _sbpl_string(d) for d in write_dirs]
                         + system_writable)
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
    previous = {}

    def bail_out(signum, _frame):
        raise SystemExit(128 + signum)  # shell convention for "killed by signal N"

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue                       # not available on this platform
        try:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, bail_out)
        except (OSError, ValueError):
            previous.pop(sig, None)
            pass                           # e.g. imported and called off the main thread
    return previous


def restore_termination_handlers(previous):
    """Restore handlers changed by install_termination_handlers()."""
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (OSError, ValueError):
            pass


def kill_process_group(proc, grace=5):
    """Kill one attempt's whole process group and wait for it to be gone.

    start_new_session (see run_with_timeout) puts OpenCode and its children (bun) in their
    own process group, so a signal aimed at this wrapper never reaches them — they have to
    be shot down explicitly, or the model keeps editing files after the abort. SIGTERM
    first so OpenCode can shut down cleanly; whatever survives the grace period gets
    SIGKILL."""
    if proc.poll() is not None:
        return
    pgid = proc.pid  # start_new_session=True guarantees PID == process-group ID.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            proc.poll()                    # already gone: collect it so no zombie is left
            return
        except OSError as exc:
            log("could not send %s to process group %d: %s"
                % (signal.Signals(sig).name, pgid, exc))
            continue
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            proc.poll()                    # reap the direct child as soon as it exits
            try:
                os.killpg(pgid, 0)         # the whole group, not just the direct child
            except ProcessLookupError:
                return
            except PermissionError:
                pass                       # it still exists; SIGKILL gets one attempt below
            time.sleep(0.05)
    log("process group still not gone after SIGKILL; continuing anyway")


def _drain_ready(selector, sinks, seen, wait):
    """Read every ready child pipe once; sink failures do not hide child progress."""
    events = selector.select(wait)
    for key, _mask in events:
        fd = key.fd
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            selector.unregister(key.fileobj)
            continue
        if not chunk:
            selector.unregister(key.fileobj)
            continue
        seen["at"] = time.monotonic()
        seen["any"] = True
        target = sinks.get(fd)
        if target is None:
            continue                       # still drain and count output after EPIPE
        sink, binary = target
        try:
            sink.write(chunk if binary else chunk.decode("utf-8", "replace"))
            sink.flush()
        except (OSError, ValueError):
            sinks[fd] = None
    return bool(events)


def _normalise_returncode(rc):
    """Map Python's negative signal return codes to the shell's 128+signal form."""
    return 128 - rc if rc < 0 else rc


def _one_attempt(cmd, env, timeout):
    """Run OpenCode once. Returns (exit code, "did it produce any output?").

    The exit code is None when the run was killed for staying silent for `timeout`
    seconds; only then does the second value say whether output preceded the timeout.
    The main thread polls both pipes, so inherited write descriptors in a background
    descendant cannot strand a reader thread after OpenCode itself exits."""
    proc = None
    selector = None
    try:
        proc = subprocess.Popen(cmd, env=env, start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        selector = selectors.DefaultSelector()
        seen = {"at": time.monotonic(), "any": False}
        sinks = {}
        for pipe, stream in ((proc.stdout, sys.stdout), (proc.stderr, sys.stderr)):
            selector.register(pipe, selectors.EVENT_READ)
            sink = getattr(stream, "buffer", stream)
            sinks[pipe.fileno()] = (sink, sink is not stream)
        while True:
            _drain_ready(selector, sinks, seen, 0.2)
            rc = proc.poll()
            if rc is not None:
                drain_deadline = time.monotonic() + 0.05
                while (time.monotonic() < drain_deadline
                       and _drain_ready(selector, sinks, seen, 0)):
                    pass                   # forward bytes already buffered at normal exit
                return _normalise_returncode(rc), None
            if time.monotonic() - seen["at"] >= timeout:
                kill_process_group(proc)
                return None, seen["any"]
    except BaseException:
        # Ctrl-C, SIGTERM/SIGHUP (see install_termination_handlers) or an internal error:
        # never leave OpenCode running behind our back.
        if proc is not None:
            kill_process_group(proc)
        raise
    finally:
        if selector is not None:
            selector.close()
        if proc is not None:
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
    timeout == 0 disables timeout/retry and connects standard streams directly. The child
    still has its own session for reliable cleanup, so commands must remain non-interactive
    and must not open /dev/tty."""
    if not timeout or timeout <= 0:
        try:
            proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        except OSError as exc:
            log("ERROR: could not start %s: %s" % (cmd[0], exc))
            return 2
        try:
            return _normalise_returncode(proc.wait())
        except BaseException:
            kill_process_group(proc)
            raise
    attempts = retries + 1
    for i in range(1, attempts + 1):
        try:
            rc, produced_output = _one_attempt(cmd, env, timeout)
        except OSError as exc:
            log("ERROR: could not start %s: %s" % (cmd[0], exc))
            return 2
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
    instructions = [system_prompt] if system_prompt else []
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "instructions": instructions,
        "provider": {"minimax": {
            "npm": "@ai-sdk/anthropic",
            "options": {
                "baseURL": base_url,
                # @ai-sdk/anthropic turns apiKey into x-api-key. MiniMax also expects the
                # same credential as a Bearer token; anthropic-version is required too.
                "apiKey": key,
                "headers": {"Authorization": "Bearer " + key,
                            "anthropic-version": "2023-06-01"},
            },
            # Declare the context window explicitly: OpenCode pulls NO limits from
            # models.dev for a custom provider and would otherwise assume a conservative
            # default and compact the history far too early instead of using the full window.
            "models": {model: {"limit": {"context": context, "output": max_output}}},
        }},
    }
    # mkdtemp creates the private home with mode 0700; config.json below holds the key.
    cfg_path = os.path.join(home, "config.json")
    try:
        with open(cfg_path, "w") as fh:
            json.dump(cfg, fh)
        os.chmod(cfg_path, 0o600)
        scratch = os.path.join(home, "tmp")
        os.makedirs(scratch, exist_ok=True)
        # codereview-ok: Builds need the caller's toolchain/proxy environment; the documented
        # sandbox confines writes, not reads or inherited credentials (2026-08-20).
        env = dict(os.environ,
                   OPENCODE_CONFIG=cfg_path,
                   XDG_CONFIG_HOME=os.path.join(home, "config"),
                   XDG_DATA_HOME=os.path.join(home, "data"),
                   XDG_CACHE_HOME=os.path.join(home, "cache"),
                   XDG_STATE_HOME=os.path.join(home, "state"),
                   # Tools that honour TMPDIR/TMP/TEMP write scratch files inside this run's
                   # temp home. macOS confstr paths deliberately remain closed: opening them
                   # would expose other processes' shared temp/cache files to writes.
                   # codereview-ok: Keep that stricter boundary and document the limitation
                   # instead of weakening write confinement (2026-08-20).
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
            try:
                profile = build_seatbelt_profile(
                    [os.path.realpath(work_dir), os.path.realpath(home)])
            except ValueError as exc:
                log("ERROR: cannot build sandbox profile: %s" % exc)
                return 2
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
    if not os.path.isdir(args.dir):
        ap.error("--dir does not exist: %s" % args.dir)
    args.dir = os.path.realpath(args.dir)
    forbidden_dirs = {os.path.realpath(os.sep), os.path.realpath(os.path.expanduser("~"))}
    if args.dir in forbidden_dirs:
        ap.error("--dir must not be the filesystem root or your home directory: %s" % args.dir)
    if args.retries < 0:
        ap.error("--retries must be at least 0")
    if args.timeout < 0:
        ap.error("--timeout must be at least 0")
    if args.context <= 0:
        ap.error("--context must be greater than 0")
    if args.max_output <= 0:
        ap.error("--max-output must be greater than 0")
    if args.system_prompt:
        args.system_prompt = os.path.abspath(args.system_prompt)
        if not os.path.isfile(args.system_prompt):
            ap.error("--system-prompt does not exist or is not a file: %s" % args.system_prompt)
    if args.sandbox and sys.platform != "darwin":
        ap.error("--sandbox uses macOS seatbelt; use bubblewrap/firejail on this platform")
    if shutil.which("opencode") is None:
        log("ERROR: opencode was not found on PATH; install it and run 'opencode --version'")
        return 2
    if args.sandbox and shutil.which("sandbox-exec") is None:
        log("ERROR: sandbox-exec was not found on PATH")
        return 2
    task = args.task if args.task is not None else sys.stdin.read().strip()
    if not task:
        ap.error("no task given (pass it as an argument or via stdin)")

    previous_handlers = install_termination_handlers()
    try:
        key = get_api_key(args.key_command, args.base_url)
        if not key:
            if uses_default_base_url(args.base_url):
                log("ERROR: no API key. Set MINIMAX_API_KEY, pass --key-command, or (macOS) "
                    "store it in the Keychain: security add-generic-password -a \"$USER\" "
                    "-s minimax-api-key -U -w")
            else:
                log("ERROR: a custom --base-url requires an explicit provider credential via "
                    "--key-command; MINIMAX_API_KEY and the MiniMax Keychain entry are ignored")
            return 2
        return run(task, args.dir, key,
                   model=args.model, base_url=args.base_url, context=args.context,
                   max_output=args.max_output, system_prompt=args.system_prompt,
                   timeout=args.timeout, retries=args.retries, sandbox=args.sandbox,
                   variant=args.variant)
    finally:
        restore_termination_handlers(previous_handlers)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl-C: the cleanup already ran on the way out, so report it plainly
        # instead of dumping a traceback.
        log("aborted (Ctrl-C)")
        sys.exit(130)
