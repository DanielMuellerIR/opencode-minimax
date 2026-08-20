# Extract code into a new module

Extract the URL-parsing helpers from `utils.py` into a new file `url.py`.

- **Goal:** move `parse_url`, `normalize_url` and their private helpers into `url.py`,
  and update every import site to use the new module.
- **Where:** search the whole project for uses before moving anything.
- **Success criterion:** behavior is identical and the existing tests still pass
  (run them). No function is renamed and no signature changes.
- **Constraints:** pure move + re-import — do not "improve" the moved code, do not add
  features, do not touch unrelated files. Keep existing comments with the code they belong to.
