**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

Use MiniMax as an **agentic coding assistant** through [OpenCode](https://opencode.ai) —
delegate everyday coding tasks to a strong, inexpensive model and keep your pricey
frontier subscription for the work that really needs it.

You point it at a folder and describe a task in plain language ("fix the failing test",
"extract this into its own file"). The model reads your files, makes the change, and checks
its own work. You review the result and keep it or throw it away.

## Setup

You need three things:

1. **OpenCode** — install it from [opencode.ai](https://opencode.ai) and check it works:
   ```bash
   opencode --version
   ```
2. **Python 3.8+** (standard library only — nothing to install).
3. **A MiniMax API key** — create one on the [MiniMax](https://www.minimax.io) platform,
   then make it available in your terminal:
   ```bash
   export MINIMAX_API_KEY=your-key-here
   ```
   (Add that line to your shell profile so it persists. You can also read the key from a
   password manager instead — see **Keeping the key safe** in the collapsible sections below.)

Then get this repository:

```bash
git clone https://github.com/DanielMuellerIR/opencode-minimax.git
cd opencode-minimax
```

## Try it (about a minute)

A ready-made demo fixes a deliberately broken function for you, in a throwaway copy — your
own files are never touched:

```bash
export MINIMAX_API_KEY=your-key-here
examples/run-demo.sh
```

What you'll see (real output, lightly trimmed):

```console
$ python3 test_calc.py
FAIL: ZeroDivisionError: division by zero

$ minimax_agent.py --dir ./demo --sandbox \
    "Fix average(): return 0.0 on empty input instead of raising. Keep it minimal."
-> MiniMax agentic: model MiniMax-M3, dir ./demo [sandboxed]
→ Read calc.py
→ Read test_calc.py
← Edit calc.py
$ python3 test_calc.py         # the model verifies its own fix
OK

$ git diff
 def average(numbers):
     # Return the mean of a list of numbers.
+    if not numbers:
+        return 0.0
     return sum(numbers) / len(numbers)
```

Broken test → task in plain words → a small, correct change → green. That's the whole idea.

## Use it on your own code

Two safe patterns, both ready to run in [`examples/`](examples):

```bash
# 1) Ask for a review WITHOUT changing anything (runs against a throwaway copy):
examples/review-repo.sh /path/to/your/repo

# 2) Ask for a fix, confined to a throwaway copy you review before keeping it:
examples/fix-in-sandbox.sh /path/to/your/repo "Fix the crash when the input list is empty."
```

Or call the tool directly:

```bash
minimax_agent.py --dir ./my-project --sandbox "Add a --verbose flag to cli.py."
```

The single biggest thing that makes delegation work well is **describing the task clearly**
— goal, where to look, how to tell it's done, and what not to touch. See the ready-made
[task templates](examples/briefs) for the shape of a good request. You can pipe one in:

```bash
minimax_agent.py --dir ./my-project --sandbox < examples/briefs/fix-failing-test.md
```

## Staying safe

The assistant edits files on its own, so keep it boxed in — the examples above already do
this for you:

- **Reviews** run against a **throwaway copy** of your repo, so nothing can change your work.
- **Fixes** run with `--sandbox` (macOS), which stops the assistant from writing anywhere
  outside the target folder, even by mistake.
- **Always read the change before you keep it** (`git diff`). Treat the assistant as a fast,
  capable helper whose work you check — not an oracle.
- Never point `--dir` at your home folder or a broad path.

<details>
<summary><b>Under the hood — the four setup traps this solves</b> (optional; you don't need
this to use the tool)</summary>

<br>

OpenCode already supports custom providers, so in principle you just point it at MiniMax. In
practice, four non-obvious things make it look like "the model can't write files" when the
real cause is the setup. `minimax_agent.py` handles all four for you:

1. **Declare the context window explicitly.** OpenCode pulls no limits from `models.dev` for
   a *custom* provider, so without `models.<name>.limit.context` it assumes a conservative
   default and shortens the conversation far too early — you never get the model's full
   window. The wrapper sets it (default `1000000`).
2. **Put OpenCode's state under the system temp dir.** OpenCode keeps its SQLite state DB
   under `~/.local/share/opencode`. If you confine writes to your work directory (the
   sandbox), that database write is denied and OpenCode crashes *immediately*
   (`PRAGMA wal_checkpoint`) — before the model runs. This is the classic "MiniMax can't
   write" symptom. The fix: give each run an isolated `XDG_*` home under the system temp
   dir, which the sandbox always allows.
3. **Bypass the global config to dodge plugin hangs.** A global `~/.config/opencode` can load
   an `@latest` plugin that revalidates against npm on every start and blocks OpenCode when
   npm is slow. An isolated `XDG_CONFIG_HOME` sidesteps it entirely.
4. **Add a start-up timeout with retry.** OpenCode occasionally stalls at session start (a
   small title/provider-init call) while the API itself is healthy. The stall happens before
   the first tool call, so a restart is safe. The wrapper times out and retries; each attempt
   runs in its own process group so child processes get cleaned up too.

The whole thing is about 200 lines of Python you can read in one sitting.

</details>

<details>
<summary><b>Keeping the key safe</b>, and using other providers</summary>

<br>

**Keeping the key safe.** Instead of an environment variable you can hand the tool a command
that prints the key, so the secret never sits in your shell history:

```bash
# macOS Keychain example:
minimax_agent.py --dir ./my-project \
  --key-command "security find-generic-password -s minimax-api-key -w" "..."
```

**Other providers.** Nothing here is MiniMax-specific except the defaults. Point `--base-url`
at any Anthropic-compatible endpoint and pass `--model` accordingly; check that provider's
docs for the exact model id.

</details>

## Good to know

- Built and tested on **macOS** with **OpenCode 1.16–1.17.x**. The `--sandbox` confinement is
  macOS-only; on Linux, run the assistant against a throwaway git worktree you can revert
  (the examples do this), or wrap it with `bubblewrap`/`firejail`.
- OpenCode changes quickly. Treat this as a **working recipe**, not a maintained product — if
  a future OpenCode release changes behavior, read the short script and adjust.
- Many MiniMax plans have a **rolling usage window**; when you exceed it you get a generic
  server error rather than a clear quota message. Wait a bit and retry.

## License

MIT — see [LICENSE](LICENSE).
