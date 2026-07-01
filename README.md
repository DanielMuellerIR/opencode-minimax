**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

Run MiniMax (or any Anthropic-compatible model) as an **agentic coder** through
[OpenCode](https://opencode.ai) — a small, honest wrapper that solves four non-obvious
setup traps so you can delegate well-specified coding tasks to a strong-but-cheap model
and keep your frontier subscription for the work that needs it.

## Why

Frontier coding subscriptions (Claude, GPT) are the expensive part of an agentic
workflow. A capable, high-volume model such as MiniMax can handle a large share of
well-specified implementation work — refactors, mechanical edits, first drafts, bulk
changes — at a fraction of the cost. The trick is running it *agentically* (the model
reads files, greps, edits, verifies itself), not just as a one-shot text completion.

OpenCode already supports custom providers, so in principle you just point it at MiniMax.
In practice, four traps make it look like "the model can't write files" when the real
cause is the harness. This wrapper bakes in the fixes and gets out of the way.

## How it works

`minimax_agent.py` generates an **ephemeral, isolated OpenCode config** for one run and
invokes `opencode run`. The model does the rest: read, grep, edit, run tests, iterate.
That's it — no daemon, no lock-in. Roughly 200 lines you can read in one sitting.

## Requirements

- [OpenCode](https://opencode.ai) on your `PATH` (tested with 1.16–1.17.x).
- Python 3.8+ (standard library only).
- A MiniMax API key (or any other Anthropic-compatible endpoint + key).
- macOS if you want the built-in `--sandbox` confinement (seatbelt). Linux works without
  it; see [Safety](#safety).

## Quick start

```bash
export MINIMAX_API_KEY=...        # or use --key-command (see below)

# A read-only audit against a throwaway git worktree (recommended for reviews):
git worktree add -f /tmp/wt HEAD
python3 minimax_agent.py --dir /tmp/wt \
  "Review this repo for real bugs. List each with file:line and a concrete fix."
git worktree remove --force /tmp/wt

# A write task, OS-confined to the target directory (macOS):
python3 minimax_agent.py --dir ./my-project --sandbox \
  "Extract the URL parser from utils.py into a new url.py; keep behavior identical."
```

The task can also come from stdin, which is handy for longer briefs:

```bash
python3 minimax_agent.py --dir ./my-project --sandbox < brief.txt
```

### Keeping the key out of your shell history

Instead of an environment variable you can hand the script a command that prints the key:

```bash
# macOS Keychain example:
python3 minimax_agent.py --dir ./my-project \
  --key-command "security find-generic-password -s minimax-api-key -w" "..."
```

## The four traps (the actual value here)

These cost real debugging time. If you build your own wrapper, these are what to watch:

1. **Declare the context window explicitly.** OpenCode pulls no limits from `models.dev`
   for a *custom* provider, so without `models.<name>.limit.context` it assumes a
   conservative default and compacts the history far too early — you never get the model's
   full window. This wrapper sets it (default `1000000`).
2. **Put OpenCode's state under the system temp dir.** OpenCode keeps its SQLite state DB
   under `~/.local/share/opencode`. If you confine writes to your work directory (a sandbox),
   that DB write is denied and OpenCode crashes *immediately* (`PRAGMA wal_checkpoint`) —
   before the model runs. This is the classic "MiniMax can't write" symptom. The fix: give
   each run an isolated `XDG_*` home under the system temp dir, which the sandbox always
   allows.
3. **Bypass the global config to dodge plugin hangs.** A global `~/.config/opencode` can
   load an `@latest` plugin that revalidates against npm on every start and blocks OpenCode
   when npm is slow. An isolated `XDG_CONFIG_HOME` sidesteps it entirely.
4. **Add a start-up timeout with retry.** OpenCode occasionally stalls at session start (a
   small title/provider-init call) while the API itself is healthy. The stall happens before
   the first tool call, so a restart is safe. This wrapper times out and retries; each attempt
   runs in its own process group so children (bun) get killed too.

## Safety

`opencode run` edits files under `--dir` **without asking**. Two layers keep that contained:

- **Read-only work** (audits, reviews, analysis): run against a **throwaway git worktree**
  (`git worktree add -f <tmp> HEAD`). Any stray writes land in the worktree and are discarded.
- **Write work:** pass **`--sandbox`** (macOS). It runs OpenCode under `sandbox-exec` with a
  seatbelt profile that permits writes/deletes only under `--dir` (plus the system temp dir).
  Even a runaway agent physically cannot write outside the target. On Linux there is no
  built-in confinement yet — wrap the command with `bubblewrap`/`firejail`, or at least keep
  `--dir` a dedicated git worktree you can revert.

Never point `--dir` at your home directory or a broad path.

## Review before you merge

A cheap model is a capable junior, not an oracle. The workflow that makes this safe:

1. Write the task as a precise brief (goal, files, success criterion, style, what *not* to touch).
2. Run it in an isolated worktree.
3. **Read the diff** (`git -C <dir> diff`) and check correctness, scope and style yourself.
4. Only then cherry-pick/merge. Never blind-merge machine output.

## Any Anthropic-compatible provider

Nothing here is MiniMax-specific except the defaults. Point `--base-url` at any
Anthropic-compatible endpoint and pass `--model` accordingly; check your provider's docs
for the exact model id and whether it wants a Bearer token.

## Limitations & disclaimer

- **This tracks OpenCode's behavior at a point in time** (1.16–1.17.x). OpenCode moves
  quickly; a config-schema or CLI change may break one of the workarounds. Treat this as a
  working recipe, not a maintained product, and read the code before you rely on it.
- **`--sandbox` is macOS-only** (seatbelt). No Linux confinement is built in.
- **Rate limits are opaque.** Many MiniMax plans have a rolling window; when you exceed it
  you get a generic server error, not a quota signal. Back off and retry later.
- **No usage telemetry.** Agentic runs go through OpenCode, so this script does not track
  tokens or cost. Watch your provider's dashboard.

## License

MIT — see [LICENSE](LICENSE).
