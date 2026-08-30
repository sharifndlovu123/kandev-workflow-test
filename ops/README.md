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

## Backend port

`kandev run` binds a free port each start. Find it:

```
grep -E 'open:|backend ready' /tmp/kandev-run.log   # or wherever you redirected it
```

Update `kandev_url:` in the active run file(s) after any restart.

## The workflows themselves

`../workflows/feature-delivery.yaml` and `../workflows/design-doc.yaml` are the
source of truth. The **running** Kandev workflows can drift from these files
(imports skip existing names) — after editing a YAML, sync the live steps with
`update_workflow_step_kandev`, or delete + re-import if no task history matters.

Both workflows are Claude-only today. Each has a `Review - Codex` slot reserved
for a second model vendor — it runs no agent and tasks route around it until a
second CLI is wired up.
