# kandev-workflow-test

Home for our **Kandev** multi-agent workflow definitions and the tooling that drives them.

Started as a throwaway repo for validating a `draft → independent review → implement →
human-gate` pipeline; it now holds the two workflows we actually run, plus the ops scripts
and design notes. The toy `src/` string helpers are leftovers from the early dry-runs.

## Layout

| Path | What |
|---|---|
| `docs/kandev-brief.md` | **Start here.** Current-state handoff brief — the orchestrator setup, both workflows + step IDs, the MCP driving surface, hard-won lessons, what's shipped. |
| `docs/specs/feature-delivery-workflow.md` | The original design spec + `§13` "build reality" (divergences, the session-limit story, `§13.4` open items, `§13.6` the reverted `on_turn_start` guards). |
| `workflows/design-doc.yaml` | **Design Doc** workflow (8 steps): idea → approved design doc committed as a PR. |
| `workflows/feature-delivery.yaml` | **Feature Delivery** workflow (11 steps): approved design doc → implemented PR. |
| `ops/kandev-mcp.py` | Minimal Kandev MCP client. `./kandev-mcp.py <tool> '<json>' [--url …]` |
| `ops/resume-driver.py` | Self-driving monitor for one task — resumes it after a rate-limit death, restarts the backend, stops at a human gate. |
| `ops/runs/<slug>.md` | Per-feature tracking file (git-ignored; `rm` when the feature ships). |
| `ops/README.md` | Operational notes. |
| `docs/specs/{capitalize,truncate-string}.md`, `src/` | Dry-run artifacts. |

The two `workflows/*.yaml` files are kept **in sync with the live Kandev instance** — after
editing one, sync the live steps with `update_workflow_step_kandev` (it does not accept
`agent_profile`), or regenerate the YAML from `export_workflow_kandev`.

## Using it

Kandev runs as a systemd `--user` service on a fixed port:

```
systemctl --user status kandev          # health
kandev service logs -f                   # backend logs
./ops/kandev-mcp.py list_workflows_kandev '{"workspace_id":"692988fd-8e4f-45b4-934e-0c608e10cd40"}'
```

MCP endpoint: `http://localhost:38429/mcp`. Everything else — IDs, the workflow step maps,
how to create/drive a task, the resume mechanics — is in `docs/kandev-brief.md`.
