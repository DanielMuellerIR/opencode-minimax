# Brief template: add a small feature (a CLI flag)

    python3 minimax_agent.py --dir ./my-project --sandbox < examples/briefs/add-cli-flag.md

---

Add a `--dry-run` flag to the command-line tool in `cli.py`.

- **Goal:** with `--dry-run`, the tool prints what it *would* do and makes no changes;
  without it, behavior is unchanged.
- **Where:** the argument parser and the single function that performs the writes.
- **Success criterion:** running with `--dry-run` produces the planned output and leaves
  all files untouched; running without it behaves exactly as before. Add one test for the
  dry-run path.
- **Constraints:** smallest change that works; reuse the existing argument-parser and
  logging style; no new dependencies; do not reformat surrounding code.
