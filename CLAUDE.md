# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Not a normal software project. It is the **configuration and tooling for an external
orchestrator, Kandev** (github.com/kdlbs/kandev), which runs `draft → independent review →
implement → human-gate` pipelines using coding agents. The important artifacts:

- `workflows/design-doc.yaml`, `workflows/feature-delivery.yaml` — the two workflow definitions.
- `ops/` — Python tooling to drive a running Kandev instance over MCP.
- `docs/kandev-brief.md` — the authoritative current-state reference (IDs, step maps, mechanics).
- `docs/specs/feature-delivery-workflow.md` — the design spec; `§13` records where the build
  diverged from it and why.

`src/strings.js` + `src/strings.test.js` and `docs/specs/{capitalize,truncate-string}.md` are
leftover dry-run artifacts — ignore them for real work.

**Read `docs/kandev-brief.md` first.** It has the workspace/agent/repo IDs, both step-ID maps,
the MCP tool list, and the resume mechanics that are not obvious from the code.

## Commands

```bash
# Toy test suite (dry-run leftovers)
npm test                               # = node --test
node --test src/strings.test.js        # single file
node --test --test-name-pattern="capitalize"   # single test by name

# Kandev orchestrator (systemd --user service, fixed port 38429)
systemctl --user status kandev
systemctl --user restart kandev        # + rm -f ~/.kandev/.kandev-backend.lock after a hard kill
kandev service logs -f

# Talk to the running Kandev instance
./ops/kandev-mcp.py <tool> '<json-args>' [--url http://localhost:38429]
./ops/kandev-mcp.py list_workflows_kandev '{"workspace_id":"692988fd-8e4f-45b4-934e-0c608e10cd40"}'
./ops/kandev-mcp.py list_workflow_steps_kandev '{"workflow_id":"<id>"}'

# Resume a stuck task after a rate-limit death
./ops/resume-driver.py --run ops/runs/<slug>.md
```

MCP endpoint: `http://localhost:38429/mcp` (streamable HTTP; handshake is
`initialize` → `notifications/initialized` → `tools/call`; responses are bare JSON or SSE —
`ops/kandev-mcp.py` handles both).

## Editing a workflow is a two-part change

The `workflows/*.yaml` files and the **live Kandev instance are kept byte-identical**. A YAML
edit alone does nothing to running workflows because `import_workflow_kandev` **skips any
workflow whose name already exists**. To apply a change:

1. Edit the YAML.
2. Sync each changed step to live with `update_workflow_step_kandev {step_id, prompt, events}`
   — this tool does **not** accept `agent_profile` (agent bindings are UI-only / task-level).
3. Or, after doing it live via the UI/MCP, regenerate the YAML from `export_workflow_kandev`
   and re-add the `#` comments by hand.

Verify with a semantic diff of `export_workflow_kandev` output vs the committed YAML before
considering a change done.

## Workflow design constraints (encoded in the prompts — keep them)

- **Agents never self-merge.** Every PR is merged by a human. Integrate / Commit Doc push +
  open a PR and stop; the prompts forbid `gh pr merge`.
- **Base branch is taken from the task**, never assumed to be `main`. Code Review diffs against
  the task's base branch, not the repo default.
- **Human Approval / Human Review are gates with no agent.** They are enforced by prompt
  discipline only — the **MOVEMENT DISCIPLINE** block at the top of every agent step prompt.
  Structural `on_turn_start` guards were tried and reverted (`§13.6`): they fire on the
  deferred-move arrival and cause bounce loops. Do not re-add them without the `on_turn_complete`
  + step-complete-signal approach.
- **Design-doc directory is detected**, not hardcoded — an existing `docs/**/specs/`
  (e.g. `docs/superpowers/specs/`), else `docs/specs/`.
- Both workflows are Claude-only today (profile `claude-build`, sonnet/acceptEdits,
  `auto_approve`). The `Review - Codex` step in each is a reserved no-agent placeholder for a
  second vendor.

## Operational notes

- **Claude account session limits (5-hour rolling)** kill workflow agents mid-turn. The agent
  dies without handing off and a same-step `move_task` does not re-fire it. Re-trigger by
  **bouncing through Backlog**: `move_task` → Backlog, wait ~4s, `move_task` → the dead step
  with a *minimal* "CONTINUE, don't restart" prompt. A resume prompt must **never** name a file
  or a cross-step action.
- `ops/runs/<slug>.md` tracks one in-flight feature; it is git-ignored and should be `rm`'d when
  the feature ships. `ops/runs/_template.md` is the template (kept).
- Per-task git worktrees live under `~/.kandev/tasks/`; git deregisters them on prune but the
  directories can be left root-owned by docker test runs (`sudo rm -rf` to clear).
