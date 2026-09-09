# ops/ — running the Kandev workflows

Operational tooling for driving the **Design Doc** and **Feature Delivery**
workflows against a real repo. Lives here (not `/tmp`) so it survives session
limits and context loss — the recurring problem is a Claude session limit killing
a workflow agent mid-run, then the next session having to reconstruct where
everything was.

## Files

| File | What |
|---|---|
| `kandev-mcp.py` | Minimal Kandev MCP client. `./kandev-mcp.py <tool> '<json>'`. The backend port changes every `kandev run` — pass `--url` or check the run log. |
| `resume-driver.py` | Self-driving monitor for one task: re-triggers it after a rate-limit death (waits for the stated reset time, bounces via Backlog), restarts the backend if it dies, stops at a human gate / Done. Runs only while its shell is alive. |
| `reset-task-session.py` | One-shot recovery for a task stuck on a dead / full-queue / conflicted session (see "Recovering a stuck session" below). Run it yourself — it's meant to be invoked directly, not proposed command-by-command. |
| `runs/_template.md` | Per-feature tracking file template. |
| `runs/<slug>.md` | One per in-flight feature — the durable facts to resume it. **Delete it when the feature ships.** Git-ignored. |

## Per-feature lifecycle

1. **Start** a feature: create a task in Kandev, then
   `cp runs/_template.md runs/<slug>.md` and fill in the task/workflow ids,
   branch, worktree.
2. **While it runs**: keep `runs/<slug>.md` current — step, what's left, PR URL.
   If a session limit hits, `./resume-driver.py --run runs/<slug>.md` babysits it.
3. **Shipped** (PR merged): `rm runs/<slug>.md`. The information is no longer
   needed — the git history and the merged PR are the record.

## Re-triggering a stuck task by hand

Bounce it through **Backlog**, then move it back to the step it died on:

```
./kandev-mcp.py move_task_kandev '{"workflow_id":"...","task_id":"...","workflow_step_id":"<Backlog id>"}'
# wait ~4s
./kandev-mcp.py move_task_kandev '{"workflow_id":"...","task_id":"...","workflow_step_id":"<same step id>","prompt":"CONTINUE - killed by a session limit, not a problem. Do NOT restart. Re-read the plan + git log/status/diff, then resume THIS step only."}'
```

**The `prompt` must never add instructions or name a file / cross-step action.**
A step-contradicting resume prompt (e.g. telling a plan-mode Draft step to "write
the file") is what caused a task to blow past its human gate on 2026-08-30. Keep
the prompt to "continue this step, don't restart" and nothing more. The workflows
now also have `on_turn_start` guards on the no-agent steps and a MOVEMENT
DISCIPLINE block in every agent prompt, but don't lean on them — write clean
resume prompts.

## Recovering a stuck session

Three distinct failure modes look similar from the outside (task not progressing)
but need different handling — check the session state
(`list_task_sessions_kandev`) before reacting:

- **`WAITING_FOR_INPUT` because it's a real gate** (Human Approval / Human Review /
  Needs Human) — not stuck, do nothing until a human acts.
- **`WAITING_FOR_INPUT` mid-turn** (e.g. the session called `ask_user_question_kandev`
  and is waiting on an answer) — **never move this task** (by hand or over MCP)
  until that question is answered and the turn completes naturally. Moving it
  force-completes the session and silently discards the pending question/answer —
  observed 2026-09-09, no recovery for the lost exchange once it happens.
- **Genuinely dead**: `updated_at` frozen for several minutes, `journalctl --user -u
  kandev | grep -i "queue full"` shows a hand-off failing to queue, or
  `move_task_kandev` itself returns a CONFLICT/INTERNAL_ERROR. This is what
  `reset-task-session.py` fixes:

  ```
  ./reset-task-session.py --task <uuid> --workflow <uuid> --step <the step it died on>
  ```

  It archives the task, clears `archived_at` directly (no `unarchive_task_kandev`
  tool exists), bounces through Backlog, and hands off with a "continue, don't
  restart" prompt — one script instead of the previous three-step manual dance.
  Two things worth knowing before running it:
  - It **pushes the task's worktree branch to its remote first** as a safety net.
    Forcing a fresh session appears to sometimes spin up a fresh worktree that
    `git reset --hard`s to the branch's merge-base, discarding local-only commits
    (observed 2026-09-09, recovered via `git fsck`/reflog only by luck). Pushing
    first means a reset can't lose anything not already on the remote.
  - It **checks the plan size before and after** and warns loudly if it shrank —
    `update_task_plan_kandev` replaces the whole plan, and a resumed session that
    doesn't read-then-write-back the full content will silently truncate the
    approved design/spec and its entire review history (observed twice
    2026-09-09, ~93KB and ~149KB documents reduced to a few KB each). If you see
    that warning, restore from `task_plan_revisions` before doing anything else:
    ```
    python3 -c "import sqlite3; c=sqlite3.connect('$HOME/.kandev/data/kandev.db'); \
      print(c.execute('select id, length(content), created_at from task_plan_revisions where task_id=? order by created_at desc limit 10', ('<task_id>',)).fetchall())"
    ```
    then write the right revision's `content` back into `task_plans` for that
    `task_id`.

  If an agent's own `move_task_kandev` call fails with CONFLICT even after this
  reset, don't have it keep retrying — issue the identical `move_task_kandev`
  call yourself over `kandev-mcp.py`. This has worked every time it's been tried
  (2026-09-09); the conflict appears tied to stale session-primary bookkeeping,
  not a real invariant violation.

## Backend port

Kandev now runs as a systemd `--user` service on a **fixed** port (38429):
`systemctl --user status kandev` / `kandev service logs -f`. The `--url` default
in `kandev-mcp.py` matches. (Historically `kandev run` bound a random port each
start — if you go back to that, `grep -E 'open:|backend ready'` the run log and
update `kandev_url:` in the active run files.)

## The workflows themselves

`../workflows/feature-delivery.yaml` and `../workflows/design-doc.yaml` are the
source of truth. The **running** Kandev workflows can drift from these files
(imports skip existing names) — after editing a YAML, sync the live steps with
`update_workflow_step_kandev`, or delete + re-import if no task history matters.
The YAMLs are regenerated from `export_workflow_kandev` (which now carries the
`on_turn_start` guards and the workflow-level MOVEMENT DISCIPLINE prompt); the
`#` comments are re-added by hand after export. The workflow-level `prompt` can
only be set on a fresh import — `update_workflow_step_kandev` reaches step
prompts and `events` only, not the workflow prompt.

Both workflows are Claude-only today. Each has a `Review - Codex` slot reserved
for a second model vendor — it runs no agent and tasks route around it until a
second CLI is wired up.
