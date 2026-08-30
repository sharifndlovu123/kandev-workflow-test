# Run: <feature-slug>

status: active            # active | blocked | shipped
workflow: Feature Delivery # Design Doc | Feature Delivery
kandev_task_id:
kandev_workflow_id:
kandev_url: http://127.0.0.1:38429   # from the kandev run log; changes each restart
repo: /home/sharif/Documents/vs_code/work/mlankatech/epglum
worktree:                # /home/sharif/.kandev/tasks/<slug>_<id>/<repo>
branch:                   # feature/<slug>-<suffix>
base_branch: dev

## Where it is

<one line: current step, session state, what's left>

## Next action

<what a resuming session should do first — usually: check kandev up, check step,
 if rate-limited nudge via ops/resume-driver.py --run this-file>

## Resume commands

```
# is kandev up? which port?
grep -E 'open:|backend ready' /tmp/kandev-run.log

# check task
ops/kandev-mcp.py list_tasks_kandev '{"workflow_id": "<workflow_id>"}'

# self-driving monitor (survives only while its shell lives)
ops/resume-driver.py --run ops/runs/<feature-slug>.md
```

## Log

- <YYYY-MM-DD HH:MM SAST> — created
