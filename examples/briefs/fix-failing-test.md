# Fix a failing test

Fix the failing test in this project.

- **Goal:** make the test suite pass without changing what the tests assert.
- **Where:** the bug is in the implementation, not the test. Run the tests to see the
  failure, then find the cause.
- **Success criterion:** `python3 -m pytest -q` (or the project's test command) exits 0.
- **Constraints:** minimal change; do not edit the test files; do not refactor unrelated
  code; match the existing style of the file you touch.
