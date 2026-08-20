# Task brief templates

Each other Markdown file in this directory is ready to pipe directly into the wrapper. For
example, from the repository root:

```bash
python3 ./minimax_agent.py --dir ./my-project --sandbox \
  < examples/briefs/fix-failing-test.md
```

`--sandbox` is macOS-only. On another system, omit it and run against a throwaway Git
worktree instead. The template files themselves contain only the task sent to the model;
usage instructions live here so they do not become accidental model instructions.
