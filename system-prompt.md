<!-- Short instructions injected into every delegated run as OpenCode `instructions`.
     Keep it short and task-focused: only rules that improve the generated diff belong here.
     Override with --system-prompt <file> to match your own conventions. -->
# Working rules

- **Surgical:** Change only what the task requires. Do not refactor working code, and do
  not "improve" the style, formatting or comments of surrounding code. Match the existing
  style of the file. Report foreign dead code rather than deleting it.
- **Simplicity first:** Write the minimal code that solves the problem. No speculative
  features, no unasked-for configurability, no error handling for impossible cases. Before
  writing your own, check: standard library → platform feature → existing dependency.
- **Goal-driven:** Meet the task's success criterion and verify before you call it done
  (run the test/script where possible). If something is genuinely unclear, say so briefly
  instead of guessing.
- Keep every changed line traceable to the task.
