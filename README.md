**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

Use MiniMax as an **agentic coding assistant** through [OpenCode](https://opencode.ai) —
delegate everyday coding tasks to a strong, inexpensive model and keep your pricey
frontier subscription for the work that really needs it.

You point it at a folder and describe a task in plain language ("fix the failing test",
"extract this into its own file"). The model reads your files, makes the change, and checks
its own work. You review the result and keep it or throw it away.

## TL;DR

1. Install [OpenCode](https://opencode.ai) and get a MiniMax API key — a **Token Plan**
   subscription (the ~US$20 **Plus** plan already includes ~1.7 billion tokens).
2. **Store the key once** in your macOS Keychain (encrypted persistent storage; see the
   temporary runtime-file note below):
   ```bash
   security add-generic-password -a "$USER" -s minimax-api-key -w   # paste the key; input stays hidden
   ```
3. Clone this repo and watch it fix a bug for you:
   ```bash
   examples/run-demo.sh
   ```
4. Point it at your own code — it edits a throwaway copy you review before keeping:
   ```bash
   examples/fix-in-sandbox.sh /path/to/your/repo "Fix the crash on empty input."
   ```

Everything below just explains these steps, safer use, and how to drive it hands-free from your
AI assistant. Not on macOS? The [Setup](#setup) section covers the environment-variable route.

## Setup

You need three things:

1. **OpenCode** — install it from [opencode.ai](https://opencode.ai) and check it works:
   ```bash
   opencode --version
   ```
2. **Python 3.8+** (standard library only — nothing to install).
3. **A MiniMax API key from a Token Plan.** The cost-effective way to use MiniMax is a
   **Token Plan** subscription — a large monthly bucket of tokens instead of metered
   pay-per-use. The **Plus** plan (~US$20/month at the time of writing) already includes
   ~1.7 billion tokens, plenty for delegated coding. Pick a plan on the
   [MiniMax platform](https://www.minimax.io), then generate an API key from your subscription.

   **Store it securely (recommended, macOS).** Keep the persistent copy in your Keychain —
   it stays encrypted at rest and out of your shell history:
   ```bash
   # Prompts for the key; paste it in — the input stays hidden. (-U updates an existing entry.)
   security add-generic-password -a "$USER" -s minimax-api-key -w
   ```
   That's all — the tool and the example scripts read the key from the Keychain automatically.

   **Runtime exposure:** OpenCode needs the credential in its generated configuration. During
   each run, this wrapper therefore writes it in clear text to a mode-`0600` `config.json`
   inside a private mode-`0700` system-temp directory named `opencode-minimax-*`. Normal exits
   remove that directory, and so does an abort with Ctrl-C, `SIGTERM` or `SIGHUP`.
   A hard crash, `SIGKILL`, or power loss can leave the temporary copy behind; inspect the
   system temp directory and remove stale `opencode-minimax-*` directories if a run was
   terminated that way.

   **Or, the quick way:** set an environment variable for the current terminal instead:
   ```bash
   # Temporary — only for this terminal window. Add it to ~/.zshrc to persist (a plain-text file).
   export MINIMAX_API_KEY=your-key-here
   ```

Then get this repository:

```bash
git clone https://github.com/DanielMuellerIR/opencode-minimax.git
cd opencode-minimax
```

## Try it (about a minute)

A ready-made demo fixes a deliberately broken function for you, in a throwaway copy — your
own files are never touched:

```bash
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

Both example scripts pick the right degree of confinement for your platform: on macOS they
add `--sandbox`, elsewhere they run the same task without it (see [Good to know](#good-to-know)).

Or call the tool directly:

```bash
# --sandbox is macOS-only; on other systems drop it and work in a throwaway copy.
minimax_agent.py --dir ./my-project --sandbox "Add a --verbose flag to cli.py."
```

The single biggest thing that makes delegation work well is **describing the task clearly**
— goal, where to look, how to tell it's done, and what not to touch. See the ready-made
[task templates](examples/briefs) for the shape of a good request. You can pipe one in:

```bash
minimax_agent.py --dir ./my-project --sandbox < examples/briefs/fix-failing-test.md
```

## The hands-off way: drive it from your AI assistant

The most comfortable way to use this is not to type the command yourself at all, but to let
your main AI coding assistant do it. If your assistant can run shell commands — Claude Code,
Claude Desktop with file access, Cursor, Codex, and similar — then your capable planning model
does the thinking and orchestration and hands the routine implementation to MiniMax through
this tool. You just describe what you want in plain language:

> "Implement the CSV export in `exporter.py`. Delegate the implementation to MiniMax, then
> show me the diff."

To make your assistant do this on its own, paste an instruction like the following into its
project instructions — `CLAUDE.md`, `AGENTS.md`, a system prompt, or a custom-instructions
field — and adjust the path:

```markdown
## Delegating implementation to MiniMax
For well-specified implementation work (new code, refactors, mechanical edits, bulk changes),
delegate to MiniMax instead of writing it yourself, to save frontier tokens:

1. Write a precise brief: goal, files, success criterion, style, and what not to touch.
2. Make a throwaway git worktree of the target repo:  git worktree add -f <wt> HEAD
3. Run according to the host platform (or pipe the brief in via stdin):
   - macOS:  python3 /path/to/opencode-minimax/minimax_agent.py --dir <wt> --sandbox "<brief>"
   - Linux/non-macOS: run the same command without --sandbox inside the throwaway worktree.
     If an approved bubblewrap/firejail wrapper exists, use it for OS-level confinement.
     The worktree protects the original checkout but is not an OS sandbox.
4. Read the resulting  git -C <wt> diff , check correctness, scope and style, then merge.
   Never blind-merge machine output.
5. Remove the worktree when done.

Keep planning, correctness-critical, and security-sensitive work for yourself.
```

After that, "do X and delegate the implementation to MiniMax" is enough — your assistant runs
the tool, reviews the diff, and reports back. This snippet is just a portable version of the
same rule an experienced user keeps in their assistant's config. It is also available as a
ready-to-paste file: [`examples/assistant-instructions.md`](examples/assistant-instructions.md).

## Staying safe

The assistant edits files on its own, so keep it boxed in — the examples above already do
this for you:

- **Reviews** run against a **throwaway copy** of your repo, so your working tree is out of
  the way. On macOS the review is additionally sandboxed, which is what actually stops a
  write to the original checkout — the throwaway worktree shares its git directory with it.
- **Fixes** run with `--sandbox` (macOS), which stops the assistant from writing anywhere
  outside the target folder, even by mistake. The only other writable place is the run's own
  temporary directory, which is deleted when the run ends — the temp and cache files of your
  other programs stay off limits.
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
   dir and allow writes to exactly that directory (plus `--dir`) in the sandbox. `TMPDIR`
   points there too, so tools find scratch space without the shared temp dirs being open.
3. **Bypass the global config to dodge plugin hangs.** A global `~/.config/opencode` can load
   an `@latest` plugin that revalidates against npm on every start and blocks OpenCode when
   npm is slow. An isolated `XDG_CONFIG_HOME` sidesteps it entirely.
4. **Time out a stalled start — not a long task.** OpenCode occasionally stalls at session
   start (a small title/provider-init call) while the API itself is healthy. The stall
   happens before the first tool call, so a restart is safe. The wrapper watches OpenCode's
   output and counts *silence* only: a run that keeps printing is never cut off, however
   long it takes, and only a run that never printed anything is restarted. A run that goes
   quiet after it had already started is killed without a retry (exit code 124), so a second
   attempt never continues on a half-finished work directory. Each attempt gets its own
   process group, and every abort — timeout, Ctrl-C, `SIGTERM`, `SIGHUP` — kills that whole
   group (OpenCode plus its `bun` children) before the temporary config is removed;
   otherwise the model keeps editing files after you stopped the wrapper.

The whole thing is one short Python file — about 400 lines including its comments — that you
can read in one sitting.

</details>

<details>
<summary><b>Using a different provider</b>, or a different key source</summary>

<br>

**Other providers.** Nothing here is MiniMax-specific except the defaults. Point `--base-url`
at any Anthropic-compatible endpoint and pass `--model` accordingly; check that provider's docs
for the exact model id.

**Key sources.** For the default MiniMax endpoint, the tool looks for the key in this order:
`--key-command` (a command that prints it), then `$MINIMAX_API_KEY`, then — on macOS — the
current account's Keychain entry named `minimax-api-key`. A custom `--base-url` requires
`--key-command`; the MiniMax environment variable and Keychain fallback are deliberately
ignored so their credential cannot leak to another provider. Use a provider-specific entry or
password manager command:
```bash
minimax_agent.py --dir ./my-project --sandbox \
  --key-command "security find-generic-password -a \"$USER\" -s my-other-key -w" "..."
```

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
