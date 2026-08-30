# Assistant instruction snippet

Paste this into your AI coding assistant's project instructions — `CLAUDE.md`, `AGENTS.md`, a
system prompt, or a custom-instructions field — and adjust the path to where you cloned
`opencode-minimax`. After that, telling your assistant *"do X and delegate the implementation to
MiniMax"* is enough: it writes the brief, runs the tool in an isolated worktree/sandbox, reviews
the diff, and reports back.

Nothing here is project-specific — it is the same rule an experienced user keeps in their
assistant's config, made portable.

---

## Delegating implementation to MiniMax

For well-specified implementation work (new code, refactors, mechanical edits, bulk changes),
delegate to MiniMax instead of writing it yourself, to save frontier tokens:

1. Write a precise brief: goal, files, success criterion, style, and what not to touch.
2. Require a clean source repository, then make a throwaway Git worktree of committed
   `HEAD`: `git worktree add -f <wt> HEAD`. Uncommitted work is not copied. Before the
   delegated process starts, capture the full base object id and the trusted Git directory
   from the source repository; do not later trust the worktree's writable `.git` file.
3. Run according to the host platform (or pipe the brief in via stdin):
   - macOS: `python3 /path/to/opencode-minimax/minimax_agent.py --dir <wt> --sandbox "<brief>"`
   - Linux/non-macOS: run the same command without `--sandbox` inside the throwaway
     worktree. If an approved `bubblewrap`/`firejail` wrapper exists, use it for OS-level
     confinement. The worktree protects the original checkout but is not an OS sandbox.
   On macOS, the shared Git directory remains read-only inside seatbelt; the delegated task
   should edit files and run tests, not run Git commands that write metadata.
4. Inspect the result through a trusted Git directory and the captured base. Disable
   external diffs and text conversion, ignore global/system Git configuration, compare all
   tracked files against the base (not just the unstaged index diff), and list untracked
   files through `git status --porcelain=v1 -z --untracked-files=all`. The bundled
   `examples/_show-worktree-changes.py` performs these checks when given `--git-dir`,
   `--work-tree` and `--base`. Check correctness, scope and style, then merge. Never
   blind-merge machine output or execute generated code before this review.
5. Remove the worktree when done.

Keep planning, correctness-critical, and security-sensitive work for yourself.
