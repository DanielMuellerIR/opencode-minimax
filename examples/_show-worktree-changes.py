#!/usr/bin/env python3
"""Show one delegated worktree without trusting its .git file or Git config."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-dir", required=True)
    parser.add_argument("--work-tree", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()

    if not os.path.isdir(args.git_dir):
        parser.error("trusted Git directory no longer exists")
    if not os.path.isdir(args.work_tree):
        parser.error("worktree no longer exists")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", args.base):
        parser.error("base must be a full object id captured before the agent run")

    git = shutil.which("git")
    if git is None:
        parser.error("git is not available")
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    common = [
        git, "--no-pager", "--git-dir", os.path.realpath(args.git_dir),
        "--work-tree", os.path.realpath(args.work_tree),
        "-c", "diff.external=", "-c", "core.attributesFile=/dev/null",
        "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
    ]

    # Stream an arbitrarily large agent-written diff instead of holding it in this trusted
    # review process's memory.
    diff = subprocess.run(
        common + ["diff", "--no-ext-diff", "--no-textconv", args.base, "--"],
        env=env,
    )
    if diff.returncode not in (0, 1):
        return 2

    status = subprocess.Popen(
        common + ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        env=env, stdout=subprocess.PIPE,
    )
    print("\n== complete machine-readable status (JSON; includes untracked files) ==")
    print("[")
    first = True
    pending = b""
    while True:
        chunk = status.stdout.read(65536)
        if not chunk:
            break
        items = (pending + chunk).split(b"\0")
        pending = items.pop()
        for item in items:
            if not item:
                continue
            # ASCII escaping preserves undecodable filename bytes instead of making stdout
            # encoding decide whether the safety report itself succeeds.
            prefix = "  " if first else ",\n  "
            sys.stdout.write(prefix + json.dumps(os.fsdecode(item), ensure_ascii=True))
            first = False
    if pending:
        status.kill()
        status.wait()
        print("\n]")
        print("ERROR: git status returned a record without its NUL terminator", file=sys.stderr)
        return 2
    status.stdout.close()
    status_rc = status.wait()
    print("\n]")
    if status_rc != 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
