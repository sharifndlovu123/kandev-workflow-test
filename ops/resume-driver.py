#!/usr/bin/env python3
"""Self-driving monitor for a Kandev workflow task.

We keep hitting Claude session limits mid-run. When that happens the agent dies
without handing off and the task just sits. This polls the task and:

  - re-triggers it after a rate-limit death (bounce via Backlog, then forward
    with a "continue, don't restart" prompt), waiting until the limit's stated
    reset time
  - restarts the kandev backend if it died
  - un-strands a task stuck in Backlog
  - exits (and prints REACHED ...) when the task reaches a human gate / Done, or
    stalls for a non-rate-limit reason

Runs only while its shell stays alive — it is a stopgap until kandev runs as a
real service. Point it at a run file (ops/runs/<slug>.md) or pass ids directly.

Usage:
    ./resume-driver.py --run ops/runs/<slug>.md
    ./resume-driver.py --task <uuid> --workflow <uuid> [--url http://127.0.0.1:PORT]
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import time

import importlib.util

_here = pathlib.Path(__file__).parent
_spec = importlib.util.spec_from_file_location("kmcp", _here / "kandev-mcp.py")
kmcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kmcp)

KANDEV_REPO = str(_here.parent)
HUMAN_GATE_NAMES = {"Human Review", "Human Approval", "Needs Human", "Done", "Integrate", "Commit Doc"}
TERMINAL_NAMES = {"Human Review", "Human Approval", "Needs Human", "Done"}


def log(msg):
    print(f"[{datetime.datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


def read_run_file(path):
    text = pathlib.Path(path).read_text()
    def field(name):
        m = re.search(rf"^{name}:\s*(\S+)", text, re.M)
        return m.group(1) if m else None
    return {"task": field("kandev_task_id"), "workflow": field("kandev_workflow_id"),
            "url": field("kandev_url")}


def kandev_up(url):
    try:
        import urllib.request
        urllib.request.urlopen(url.replace("/mcp", "/"), timeout=4)
        return True
    except Exception:
        return False


def ensure_kandev(url):
    if kandev_up(url):
        return
    log("kandev backend DOWN — restarting")
    subprocess.run(["rm", "-f", str(pathlib.Path.home() / ".kandev/.kandev-backend.lock")])
    subprocess.Popen("nohup kandev run > /tmp/kandev-run.log 2>&1 &", shell=True, cwd=KANDEV_REPO)
    for _ in range(60):
        time.sleep(5)
        if kandev_up(url):
            log("kandev back up")
            time.sleep(8)
            return
    log("kandev restart FAILED after 5 min")


def secs_until_reset(msg):
    m = re.search(r"resets\s+(\d{1,2}):(\d{2})\s*(am|pm)", msg or "", re.I)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "pm" and hh != 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2)))  # SAST
    tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tgt <= now:
        tgt += datetime.timedelta(days=1)
    return max(60, int((tgt - now).total_seconds()) + 180)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--task")
    ap.add_argument("--workflow")
    ap.add_argument("--url", default=kmcp.DEFAULT_URL)
    ns = ap.parse_args()

    task, workflow, url = ns.task, ns.workflow, ns.url
    if ns.run:
        rf = read_run_file(ns.run)
        task = task or rf["task"]
        workflow = workflow or rf["workflow"]
        url = rf["url"] or url
    if not (task and workflow):
        ap.error("need --task and --workflow (directly or via --run file)")
    if not url.endswith("/mcp"):
        url = url.rstrip("/") + "/mcp"

    def steps():
        d = kmcp.call("list_workflow_steps_kandev", {"workflow_id": workflow}, url)
        return {s["id"]: s["name"] for s in d.get("steps", d.get("workflow_steps", []))}

    id_to_name = steps()
    name_to_id = {v: k for k, v in id_to_name.items()}
    backlog_id = name_to_id.get("Backlog")

    def state():
        d = kmcp.call("list_tasks_kandev", {"workflow_id": workflow}, url)
        t = next((x for x in d.get("tasks", []) if x["id"] == task), None)
        if not t:
            return None, None, None
        sd = kmcp.call("list_task_sessions_kandev", {"task_id": task}, url)
        sess = (sd.get("sessions") or [{}])[0]
        return t.get("workflow_step_id"), t.get("state"), sess.get("state")

    def last_status():
        d = kmcp.call("get_task_conversation_kandev",
                      {"task_id": task, "sort": "desc", "limit": 6}, url)
        for m in d.get("messages", []):
            txt = m.get("content", m.get("text", ""))
            if isinstance(txt, list):
                txt = " ".join(str(p.get("text", p)) for p in txt)
            if m.get("role") == "status" or m.get("type") == "status" or "session limit" in str(txt):
                return str(txt)
        return ""

    def retrigger(step_id, note="continue"):
        name = id_to_name.get(step_id, step_id)
        log(f"re-triggering at {name} (bounce via Backlog)")
        if backlog_id:
            kmcp.call("move_task_kandev", {"task_id": task, "workflow_id": workflow,
                                           "workflow_step_id": backlog_id}, url)
            time.sleep(4)
        kmcp.call("move_task_kandev", {"task_id": task, "workflow_id": workflow,
                  "workflow_step_id": step_id, "prompt":
                  "CONTINUE - the previous turn was killed by an account session limit "
                  "(now reset), not by any problem. Do NOT restart. Re-read the task plan, "
                  "`git log`, `git status`, `git diff` in the worktree to find exactly "
                  "where you are, then resume. Follow THIS step's own prompt exactly - "
                  "this resume note adds no new instructions and overrides nothing. Do "
                  "only this step's work, do not do work that belongs to another step, "
                  "and hand off (one move_task_kandev call) only when this step is fully "
                  "done."}, url)

    prev = None
    while True:
        ensure_kandev(url)
        step_id, tstate, sstate = state()
        if step_id is None:
            log("task not found"); time.sleep(120); continue
        name = id_to_name.get(step_id, step_id)
        line = f"step={name} task={tstate} session={sstate}"
        if line != prev:
            log(line); prev = line

        if name in TERMINAL_NAMES:
            log(f"REACHED {name} — done driving."); return

        if sstate in ("WAITING_FOR_INPUT", "FAILED", "CANCELLED", None):
            st = last_status()
            if any(k in st for k in ("session limit", "rate_limit", "resets")):
                wait = secs_until_reset(st) or 1200
                log(f"rate-limited: \"{st[:90]}\" — sleeping {wait // 60} min")
                time.sleep(wait)
                ensure_kandev(url)
                s2, _, ss2 = state()
                if id_to_name.get(s2) in TERMINAL_NAMES:
                    continue
                if ss2 in ("WAITING_FOR_INPUT", "FAILED", None):
                    retrigger(s2 or step_id)
                    time.sleep(150)
                continue
            if step_id == backlog_id:
                log("stranded in Backlog — pushing forward")
                fwd = name_to_id.get("Implement") or name_to_id.get("Draft") or name_to_id.get("Draft Doc")
                if fwd:
                    retrigger(fwd)
                    time.sleep(150)
                continue
            log(f"idle for non-rate-limit reason. last status: {st[:200]}")
            log("EXITING for human attention.")
            return

        time.sleep(150)


if __name__ == "__main__":
    main()
