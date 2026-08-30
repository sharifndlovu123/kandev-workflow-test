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
