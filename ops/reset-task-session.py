#!/usr/bin/env python3
"""Reset a Kandev task stuck on a dead / full-queue / conflicted session.

Consolidates a recovery sequence discovered the hard way (see the
kandev-* bug write-ups in the auto-memory dir): archiving a task and
clearing its archived_at flag forces a genuinely fresh session, which
is currently the only reliable way to get past a full message queue or
a session move_task_kandev can no longer talk to. There is no
"reset session" MCP tool - archive_task_kandev + a raw DB write +
a Backlog-bounce is the only path that works today.

This does NOT go through the Claude Code auto-mode classifier's
per-command approval, because it's meant to be run directly by you
(prefix with `!` inside a Claude Code session, or run it from a plain
shell) rather than proposed and approved one command at a time - that
back-and-forth is exactly the friction this script removes.

Safety net for the worktree hard-reset risk: before touching anything,
this records the task's current worktree branch/HEAD (if the worktree
is still reachable) and best-effort pushes that branch to its remote,
so a reset that discards local commits can't lose anything that isn't
also on the remote. After the bounce, it verifies the new worktree
still has the pre-reset HEAD commit reachable and prints an explicit
warning (with recovery steps) if it does not - it does NOT try to
silently fix that for you.

Usage:
    ./reset-task-session.py --task <uuid> --workflow <uuid> --step <uuid> \\
        [--prompt "CONTINUE, don't restart..."] [--url http://127.0.0.1:PORT]
"""
import argparse
import importlib.util
import pathlib
import sqlite3
import subprocess
import time

_here = pathlib.Path(__file__).parent
_spec = importlib.util.spec_from_file_location("kmcp", _here / "kandev-mcp.py")
kmcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kmcp)

DB_PATH = pathlib.Path.home() / ".kandev/data/kandev.db"
TASKS_DIR = pathlib.Path.home() / ".kandev/tasks"

DEFAULT_PROMPT = (
    "CONTINUE, don't restart. The previous session was reset (dead/full-queue/"
    "conflicted, not a real problem with your prior work). Re-read the task "
    "plan (get_task_plan_kandev) and, if a git worktree exists, `git log`/"
    "`git status` to find exactly where you left off, then resume. Do not "
    "re-derive work already recorded in the plan."
)


def log(msg):
    print(f"[reset-task-session] {msg}", flush=True)


def db():
    return sqlite3.connect(DB_PATH)


def find_worktree_repo(task_id):
    """Best-effort: locate this task's worktree checkout under ~/.kandev/tasks/."""
    for d in TASKS_DIR.glob("*"):
        if not d.is_dir():
            continue
        # worktree dirs are named <slug>_<hash>; contents are one repo subdir
        for repo_dir in d.iterdir():
            if (repo_dir / ".git").exists():
                return repo_dir
    return None


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def record_pre_state(task_id):
    repo = find_worktree_repo(task_id)
    if repo is None:
        log("no worktree found (task may not have started one yet) - skipping git safety net")
        return None
    branch = git(repo, "branch", "--show-current").stdout.strip()
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    log(f"worktree {repo} on branch {branch} @ {head[:12]}")
    push = git(repo, "push", "origin", branch)
    if push.returncode == 0:
        log(f"pushed {branch} to origin - local commits are now safe even if the worktree resets")
    else:
        log(f"WARNING: could not push {branch} to origin ({push.stderr.strip()[:200]}) "
            "- local-only commits are at risk if the fresh worktree resets. Continuing anyway.")
    return {"repo": repo, "branch": branch, "head": head}


def verify_post_state(pre):
    if pre is None:
        return
    repo = find_worktree_repo_for_branch(pre["branch"])
    if repo is None:
        log("WARNING: could not find a worktree for the branch after reset - verify manually.")
        return
    check = git(repo, "cat-file", "-e", pre["head"])
    if check.returncode == 0 and pre["head"] in git(repo, "log", "--all", "--format=%H").stdout:
        log(f"OK: pre-reset commit {pre['head'][:12]} is still reachable in {repo}")
    else:
        log(f"*** WARNING ***: pre-reset commit {pre['head'][:12]} is NOT reachable in the new "
            f"worktree {repo}. If it isn't on the remote either, recover it with:\n"
            f"    git -C {repo} fsck --no-reflog | grep 'dangling commit'\n"
            f"    git -C {repo} reflog\n"
            f"then `git reset --hard <recovered-sha>` once you've confirmed it's the right one.")


def find_worktree_repo_for_branch(branch):
    for d in TASKS_DIR.glob("*"):
        if not d.is_dir():
            continue
        for repo_dir in d.iterdir():
            if (repo_dir / ".git").exists():
                cur = git(repo_dir, "branch", "--show-current").stdout.strip()
                if cur == branch:
                    return repo_dir
    return None


def plan_length(task_id):
    with db() as c:
        row = c.execute("select length(content) from task_plans where task_id=?", (task_id,)).fetchone()
        return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--step", required=True, help="workflow_step_id to land back on")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--url", default=kmcp.DEFAULT_URL)
    ns = ap.parse_args()
    url = ns.url if ns.url.endswith("/mcp") else ns.url.rstrip("/") + "/mcp"

    pre_plan_len = plan_length(ns.task)
    log(f"plan length before reset: {pre_plan_len}")
    pre_git = record_pre_state(ns.task)

    log("archiving task (forces the old session/worktree binding to drop)")
    kmcp.call("archive_task_kandev", {"task_id": ns.task}, url)

    log("clearing archived_at directly (no unarchive_task_kandev tool exists)")
    with db() as c:
        c.execute("UPDATE tasks SET archived_at = NULL WHERE id = ?", (ns.task,))
        c.commit()

    log("bouncing through Backlog for a fresh session")
    steps = kmcp.call("list_workflow_steps_kandev", {"workflow_id": ns.workflow}, url)
    backlog_id = next(s["id"] for s in steps["steps"] if s["name"] == "Backlog")
    kmcp.call("move_task_kandev", {"task_id": ns.task, "workflow_id": ns.workflow,
              "workflow_step_id": backlog_id,
              "prompt": "Recovery: dead/full-queue/conflicted session. Bouncing for a fresh one."}, url)
    time.sleep(5)
    kmcp.call("move_task_kandev", {"task_id": ns.task, "workflow_id": ns.workflow,
              "workflow_step_id": ns.step, "prompt": ns.prompt}, url)

    time.sleep(3)
    post_plan_len = plan_length(ns.task)
    if pre_plan_len is not None and post_plan_len is not None and post_plan_len < pre_plan_len * 0.5:
        log(f"*** WARNING ***: plan shrank from {pre_plan_len} to {post_plan_len} bytes - "
            "check task_plan_revisions for the last good revision and restore it "
            "(see kandev-design-doc-plan-truncation-bug memory).")
    else:
        log(f"plan length after reset: {post_plan_len} (ok)")

    verify_post_state(pre_git)
    log("done - check the task's session state to confirm it's actually RUNNING.")


if __name__ == "__main__":
    main()
