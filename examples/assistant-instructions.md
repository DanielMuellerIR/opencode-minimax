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
2. Make a throwaway git worktree of the target repo:  `git worktree add -f <wt> HEAD`
3. Run:  `python3 /path/to/opencode-minimax/minimax_agent.py --dir <wt> --sandbox "<brief>"`
   (or pipe the brief in via stdin).
4. Read the resulting `git -C <wt> diff`, check correctness, scope and style, then merge.
   Never blind-merge machine output.
5. Remove the worktree when done.

Keep planning, correctness-critical, and security-sensitive work for yourself.
