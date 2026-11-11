**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

Use MiniMax as an **agentic coding assistant** through [OpenCode](https://opencode.ai) —
delegate everyday coding tasks to a strong, inexpensive model and keep your pricey
frontier subscription for the work that really needs it.

You point it at a folder and describe a task in plain language ("fix the failing test",
"extract this into its own file"). The model reads your files, makes the change, and checks
its own work. You review the result and keep it or throw it away.

## TL;DR

1. Install [OpenCode](https://opencode.ai) and get a MiniMax API key — a **M Plan**
   subscription (formerly Token Plan). Check the [current tiers and limits](https://platform.minimax.io/docs/m-plan/intro).
2. **Store the key once** in your macOS Keychain (encrypted persistent storage; see the
   temporary runtime-file note below):
   ```bash
   security add-generic-password -a "$USER" -s minimax-api-key -U -w   # paste the key; input stays hidden
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
3. **A MiniMax API key for your chosen access method.** The subscription is now
   called **M Plan** (formerly Token Plan), with Go, Explore and Build tiers.
   Usage and limits depend on the model, context length and task, among other factors.
   Check the [current plans and supported models](https://platform.minimax.io/docs/m-plan/intro)
   before setup. This guide describes the existing integration; it does not establish
   compatibility with models introduced later.

   **Store it securely (recommended, macOS).** Keep the persistent copy in your Keychain —
   it stays encrypted at rest and out of your shell history:
   ```bash
   # Prompts for the key; paste it in — the input stays hidden; -U also updates an old entry.
   security add-generic-password -a "$USER" -s minimax-api-key -U -w
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

$ python3 ./minimax_agent.py --dir ./demo --sandbox \
    "Fix average(): return 0.0 on empty input instead of raising. Keep it minimal."
-> MiniMax agentic: model MiniMax-M3, dir ./demo [sandboxed]
→ Read calc.py
→ Read test_calc.py
← Edit calc.py
$ python3 test_calc.py         # the model verifies its own fix
OK

== the change the agent made ==
 def average(numbers):
     # Return the mean of a list of numbers.
+    if not numbers:
+        return 0.0
     return sum(numbers) / len(numbers)

After reviewing the diff, run its test now? [y/N] y
OK
```

Broken test → task in plain words → a complete, configuration-safe review → only then run
the generated code. That's the whole idea. The outer demo never imports agent-written Python
before you confirm that you inspected the shown change.

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
They copy committed `HEAD`, not uncommitted changes, and stop with a clear error when the source
repository is dirty. Commit the exact state you want reviewed or changed before invoking them.

Or call the tool directly:

```bash
# --sandbox is macOS-only; on other systems drop it and work in a throwaway copy.
python3 ./minimax_agent.py --dir ./my-project --sandbox "Add a --verbose flag to cli.py."
```

The single biggest thing that makes delegation work well is **describing the task clearly**
— goal, where to look, how to tell it's done, and what not to touch. See the ready-made
[task templates](examples/briefs) for the shape of a good request. You can pipe one in:

```bash
python3 ./minimax_agent.py --dir ./my-project --sandbox < examples/briefs/fix-failing-test.md
```

## The hands-off way: drive it from your AI assistant

The most comfortable way to use this is not to type the command yourself at all, but to let
your main AI coding assistant do it. If your assistant can run shell commands — Claude Code,
Claude Desktop with file access, Cursor, Codex, and similar — then your capable planning model
does the thinking and orchestration and hands the routine implementation to MiniMax through
this tool. You just describe what you want in plain language:

> "Implement the CSV export in `exporter.py`. Delegate the implementation to MiniMax, then
> show me the diff."

The canonical ready-to-paste instruction lives in
[`examples/assistant-instructions.md`](examples/assistant-instructions.md). Put that text in
your assistant's `CLAUDE.md`, `AGENTS.md`, system prompt, or custom-instructions field and
adjust the path. Keeping one canonical copy prevents the three variants from drifting apart.
After that, "do X and delegate the implementation to MiniMax" is enough — your assistant runs
the tool, reviews the diff, and reports back.

## Staying safe

The assistant edits files on its own, so keep it boxed in — the examples above already do
this for you:

- **Reviews** run against a **throwaway copy** of your repo, so your working tree is out of
  the way. On macOS the review is additionally sandboxed, which is what actually stops a
  write to the original checkout — the throwaway worktree shares its Git directory with it.
  That shared Git directory stays read-only inside the sandbox, so commands such as `git add`
  or `git commit` fail there by design; the supplied review task only reads and reports.
- **Fixes** run with `--sandbox` (macOS), which stops the assistant from writing anywhere
  outside the target folder, even by mistake. The only other writable place is the run's own
  temporary directory, which is deleted when the run ends — the temp and cache files of your
  other programs stay off limits.
- **Always read the complete change before you keep or execute it.** The fix and demo scripts
  compare every tracked file with the base captured before the run, disable external diffs and
  text conversion, ignore the worktree's writable `.git` file, and list untracked files in a
  machine-readable status block. Treat the assistant as a fast, capable helper whose work you
  check — not an oracle.
- Never point `--dir` at your home folder or a broad path.
- `--sandbox` confines **writes**, not reads, network access, or secrets. OpenCode inherits the
  caller's environment so delegated builds can find their toolchains, proxies, and credentials.
  Start the wrapper from an environment that contains only credentials the delegated task may
  access; the model can also read files that the current account can read.

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
   points there too, so tools that honour `TMPDIR` find scratch space without the shared temp
   dirs being open. macOS APIs that use `DARWIN_USER_TEMP_DIR` or `DARWIN_USER_CACHE_DIR`
   directly remain read-only under the sandbox; opening those shared directories would also
   let the agent alter other processes' temporary and cache files.
3. **Bypass the global config to dodge plugin hangs.** A global `~/.config/opencode` can load
   an `@latest` plugin that revalidates against npm on every start and blocks OpenCode when
   npm is slow. An isolated `XDG_CONFIG_HOME` sidesteps it entirely.
4. **Time out silence without guessing whether work started.** The wrapper counts output
   silence, not total runtime: a run that keeps printing is never cut off. A silent timeout
   can still happen after a tool side effect, so automatic retry is disabled by default.
   `--retries` is an explicit opt-in only for tasks whose startup cannot have side effects.
   Every attempt gets its own process group, and completion or abort — timeout, Ctrl-C,
   `SIGTERM`, `SIGHUP`, or even an exited OpenCode parent — removes remaining descendants
   before the temporary config is removed.

The whole thing is one Python file that you can read in one sitting.

The less common controls are explicit CLI flags:

| Flag | Default | Effect |
| --- | --- | --- |
| `--timeout` | `300` | Seconds of output silence; `0` disables timeout and retry. |
| `--retries` | `0` | Explicit restarts after a completely silent run; use only for side-effect-free starts. |
| `--context` | `1000000` | Context-window limit declared to OpenCode. |
| `--max-output` | `16384` | Output-token limit declared to OpenCode. |
| `--system-prompt` | bundled `system-prompt.md` | Instruction file injected into the run. |
| `--variant` | unset | Optional OpenCode agent variant. |

</details>

<details>
<summary><b>Using a different provider</b>, or a different key source</summary>

<br>

**Other providers.** Nothing here is MiniMax-specific except the defaults. Point `--base-url`
at any Anthropic-compatible endpoint and pass `--model` accordingly; check that provider's docs
for the exact model id.

**Key sources.** For the default MiniMax endpoint, the tool looks for the key in this order:
`--key-command` (a command that must print exactly one non-empty line within 30 seconds), then
`$MINIMAX_API_KEY`, then — on macOS — the current account's Keychain entry named
`minimax-api-key`. An explicitly supplied key command is authoritative: an error, timeout, or
multi-line result stops the run instead of falling back to another credential. A custom
`--base-url` requires
`--key-command`; the MiniMax environment variable and Keychain fallback are deliberately
ignored so their credential cannot leak to another provider. Use a provider-specific entry or
password manager command:
```bash
python3 ./minimax_agent.py --dir ./my-project --sandbox \
  --key-command "security find-generic-password -a \"$USER\" -s my-other-key -w" "..."
```

</details>

## EU AI Act role

As of 2026-08-24, this repository is an open-source integration component, not a
complete generative AI system offered under this project's name. It provides no
model, OpenCode runtime, or hosted endpoint. Users install OpenCode separately,
choose a compatible model provider, obtain their own API credentials, and remain
customers of those providers. The wrapper only writes the configuration for that
combination, starts OpenCode, and supervises the local process.

This classification should be reviewed if the project later bundles the runtime
and model access, operates a hosted service, or is offered as a complete AI system
under a separate name or trademark. See the EU Commission's
[Article 50 guidelines](https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations)
and the AI Act's [provider definition](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-3).

## Good to know

- Built and tested on **macOS** with **OpenCode 1.16–1.17.x**. The `--sandbox` confinement is
  macOS-only. On Linux, the examples use a throwaway worktree to separate working files, but
  that is not an OS sandbox: the agent can still reach shared Git metadata and absolute paths.
  Use an approved `bubblewrap`/`firejail` setup when you need enforced confinement.
- OpenCode changes quickly. Treat this as a **working recipe**, not a maintained product — if
  a future OpenCode release changes behavior, read the short script and adjust.
- Many MiniMax plans have a **rolling usage window**; when you exceed it you get a generic
  server error rather than a clear quota message. Wait a bit and retry.

## License

MIT — see [LICENSE](LICENSE).
