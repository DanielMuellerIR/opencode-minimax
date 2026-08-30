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
        "LC_ALL": "C",
    }
    common = [
        git, "--no-pager", "--git-dir", os.path.realpath(args.git_dir),
        "--work-tree", os.path.realpath(args.work_tree),
        "-c", "diff.external=", "-c", "core.attributesFile=/dev/null",
        "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
    ]

    diff = subprocess.run(
        common + ["diff", "--no-ext-diff", "--no-textconv", args.base, "--"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if diff.returncode not in (0, 1):
        sys.stderr.buffer.write(diff.stderr)
        return 2
    sys.stdout.buffer.write(diff.stdout)

    status = subprocess.run(
        common + ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if status.returncode != 0:
        sys.stderr.buffer.write(status.stderr)
        return 2
    records = [os.fsdecode(item) for item in status.stdout.split(b"\0") if item]
    print("\n== complete machine-readable status (JSON; includes untracked files) ==")
    # ASCII escaping preserves undecodable filename bytes instead of making stdout encoding
    # decide whether the safety report itself succeeds.
    print(json.dumps(records, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
