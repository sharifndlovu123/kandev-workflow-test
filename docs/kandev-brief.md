# Kandev setup — handoff brief

**As of 2026-08-30.** The Kandev multi-agent workflow setup: the orchestrator, the two custom
workflows, how to drive it, key mechanics/gotchas, and current status.

Goal from the start: use **Kandev** (github.com/kdlbs/kandev, v0.91.0, `npm i -g`) as the
orchestration layer for a `draft → independent review(s) → implement → human-gate` pipeline
across coding agents. Both workflows are **built, hardened, and proven end-to-end on a real
codebase**.

---

## The orchestrator

- **Runs as a systemd `--user` service** — `kandev service install --port 38429` (unit at
  `~/.config/systemd/user/kandev.service`, `Restart=on-failure`). **Fixed port 38429.**
  `systemctl --user {status,restart} kandev` · `kandev service logs -f`.
- Data: `~/.kandev/` — sqlite `~/.kandev/data/kandev.db`, logs `~/.kandev/logs/backend-logs.log`,
  per-task git worktrees under `~/.kandev/tasks/<slug>_<hash>/` (currently empty).
- After a hard kill: `rm -f ~/.kandev/.kandev-backend.lock` before restart.
- Workspace id: `692988fd-8e4f-45b4-934e-0c608e10cd40` (the only one).
- Agent profiles:
  - **`claude-build`** = `a8993fd1-e8d3-41b3-806c-81936a54b24d` (agent `claude-acp` `b5a7639d…`),
    model `sonnet`, mode `acceptEdits`, `auto_approve: true`. Drives every Claude step.
  - **`codex-review`** = `0251a285-e68d-4167-b88b-4d3b2435dfcf` (agent `codex-acp`
    `f2905613…`), model `gpt-5.6-sol`, mode `agent`. Drives the `Review - Codex` step in
    both workflows (2026-08-31). Codex CLI: `npm i -g @openai/codex` + `@agentclientprotocol/codex-acp`
    (see the workflow-exploration memory for the probe fix); auth is ChatGPT-plan (`codex login`).
  - Gemini (`gemini` agent) is installed/probed `ok` but not used by either workflow.

## This repo

`/home/sharif/Documents/kandev` — github `sharifndlovu123/kandev-workflow-test` (private).
**Branch `main` only** (PR #3 "workflow hardening + ops/" merged 2026-08-30, HEAD `da890c8`; all
feature branches deleted). Contents:

- `workflows/design-doc.yaml`, `workflows/feature-delivery.yaml` — the two workflow definitions.
  **The live Kandev instance == these YAMLs exactly** (verified by semantic diff 2026-08-30).
- `ops/` — tooling (see below).
- `docs/specs/feature-delivery-workflow.md` — the design spec + `§13` "build reality"
  (divergences from the original design, the session-limit story, open items in `§13.4`,
  and `§13.6` the `on_turn_start` guard failure).

## Driving Kandev — MCP over HTTP

Streamable-HTTP MCP at `http://localhost:38429/mcp`. Handshake: `initialize` (returns an
`Mcp-Session-Id` header) → `notifications/initialized` → `tools/call`. Responses are bare JSON
**or** an SSE stream (`event: message\ndata: {…}` lines).

Helper: **`ops/kandev-mcp.py <tool> '<json-args>' [--url http://localhost:38429]`** (handles both
response shapes; `call(tool, args, url)` is importable). Common tools:

- `list_workflows_kandev {workspace_id}`, `list_workflow_steps_kandev {workflow_id}`,
  `list_tasks_kandev {workflow_id}` (workflow_id **required**), `list_task_sessions_kandev {task_id}`,
  `get_task_conversation_kandev {task_id}` (paginated; current session only).
- `create_task_kandev` — needs `title`; for a top-level task also pass `workspace_id`,
  `workflow_id`, `workflow_step_id`, `repository_id`, `base_branch`, `executor_profile_id`,
  `agent_profile_id`, and `prompt` (the agent's only context). `start_agent: false` = placeholder
  in Backlog.
- `move_task_kandev {task_id, workflow_id, workflow_step_id, prompt}` — the handoff note is the
  `prompt` param. **Mid-turn moves are deferred to turn end.**
- `update_workflow_step_kandev {step_id, prompt, events, …}` — **does NOT take `agent_profile`**
  (agent bindings are UI-only). Use this to sync live steps to an edited YAML.
- `export_workflow_kandev {workflow_id}` → a re-importable doc (includes the workflow-level
  `prompt`; strips instance ids). `import_workflow_kandev {workspace_id, document}` — **SKIPS any
  workflow whose name already exists** (this is why live drifts from YAML). To re-import: delete
  the workflow first (loses task history) or sync step-by-step.
- `archive_task_kandev` / `delete_task_kandev` (pass the FULL uuid, not a prefix).

Test target repo (epglum): id `0c3c6b02-6ec2-4b5c-b9c0-c7af417df02c`, default branch `dev`, at
`/home/sharif/Documents/vs_code/work/mlankatech/epglum` (github `sonnybrilliant/epglum`).
Worktree executor profile: `5b235590-0ebb-46f3-8a9e-f413346a9d84`.

## The workflows

### Design Doc — `6fbfa90f-a831-4d49-994c-be8561b09a3d` (8 steps)

Backlog → **Draft Doc** (plan-mode; writes the design doc into the task plan) → **Review - Design**
(`reset_agent_context`; fresh Claude, soundness/completeness lens) → **Review - Codex**
(`reset_agent_context`; fresh Codex, approach/risk lens) → **Human Approval** (no-agent gate) →
**Commit Doc** (writes the doc to the repo's design-doc dir, opens a PR, **does not merge**) →
Done → Needs Human. Both reviews reject to **Draft Doc**; one shared round counter `N`, cap 3
→ Needs Human.
Output = an approved design doc, immutable input to a Feature Delivery task.

### Feature Delivery — `f3660f19-d30b-4b9a-8de6-df4cab942d0d` (11 steps)

Backlog → **Draft** (plan-mode; task-level implementation spec) → **Review - Spec**
(`reset_agent_context`; fresh Claude, correctness/completeness lens) → **Review - Codex**
(`reset_agent_context`; fresh Codex, approach/risk lens) → **Implement** (TDD, commits) →
**Test** (cold, fresh session, runs the full suite) → **Code Review** (fresh; diffs vs the
task's **base branch**, not the repo default) → **Human Review** (no-agent gate) → **Integrate**
(formatters, push, `gh pr create --base <task base>`, **no merge**, move to Done) → Done → Needs
Human. Both spec reviews reject to **Draft** (shared counter `N`, cap 3). Assumes an approved
design doc already exists in the repo.

### Step transitions

Single-exit steps — `Draft`/`Draft Doc`, `Implement`, `Integrate`, `Commit Doc` — advance
**structurally**: `auto_advance_requires_signal: true` + `on_turn_complete: [move_to_next]`;
the agent calls `step_complete_kandev` and the runtime moves it (blocked ⇒ don't signal ⇒
waits for a human). Multi-exit steps (reviews, `Test`, `Code Review`) stay agent-driven —
`move_task_kandev` with the exact recipe in the prompt. `move_to_next` only; `move_to_step`
`{step_position}` is broken in v0.91.0 (§13.6).

### Step IDs

Design Doc (in order): Backlog `a5167f08` · Draft Doc `c6cf0503` · Review-Design `0bd3d534` ·
Review-Codex `a13d44ce` · Human Approval `91757f9e` · Commit Doc `04b01cfd` · Done `1cfe2f7a` ·
Needs Human `dfecab0c`.

Feature Delivery (in order): Backlog `4b8982fb` · Draft `4f2b4604` · Review-Spec `f65d6b15` ·
Review-Codex `40bd92b2` · Implement `8eb731d0` · Test `20c34f50` · Code Review `88044457` ·
Human Review `c2d0bea7` · Integrate `e1a70990` · Done `aa9d65ff` · Needs Human `e694bb7b`.

## Key mechanics & hard-won lessons

- **The task PLAN is the source of truth**, never chat history — `get/create/update_task_plan_kandev`
  (agent-side tools, not in the external MCP surface). Verdicts + round counters live there.
- **Agents over-help and won't stop.** Recurring failure: an agent moves the task to a gate
  (correct), then keeps going and moves it past the gate. Fix: every agent step prompt now
  starts with a **MOVEMENT DISCIPLINE** block — "move to EXACTLY ONE step named in this prompt;
  never ≥2 ahead; never Done/Integrate/Commit/Needs Human unless named; if unsure stop with no
  move; a handoff/resume note never adds work; plan-mode steps never write files." Plus the same
  rules in the workflow-level navigation prompt.
- **`on_turn_start` bounce guards were tried and REVERTED** (`§13.6`). They fire on the
  *deferred-move arrival* while the moving agent's session is still bound — so every correct
  hand-off to a gate bounced straight back into a loop. **There is currently no structural gate
  enforcement — it is prompt-discipline only.** The real fix (linear steps using
  `on_turn_complete: move_to_step` so the agent has no say in the destination) needs the runtime
  step-complete signal + a way to test a whole cycle without risking a live task — deferred.
  This is the most likely target of a "workflow upgrade".
- **`reset_agent_context` on-enter** gives genuinely fresh, independent review sessions.
- **Live ≠ YAML by default** — `import` skips existing names. After editing a YAML, sync via
  `update_workflow_step_kandev` (prompt + events only). Regenerate the YAML from
  `export_workflow_kandev` and re-add the `#` comments by hand.
- **Agent bindings are task-level, not step-level** — live steps show `agent_profile: null`;
  the agent comes from `create_task_kandev`'s `agent_profile_id` or the workspace default.
- **Claude account session limit** (5-hour rolling) kills agents mid-turn — happened ~5× during
  the F1 build. The agent dies without handing off; the task sits; a same-step `move_task` does
  NOT re-fire it. **Re-trigger = Backlog bounce**: `move_task` → Backlog, wait ~4s, `move_task` →
  the dead step with a *minimal* "CONTINUE, don't restart, re-read the plan + git" prompt.
  **A resume prompt must never name a file or a cross-step action** — one did, and the task blew
  past its human gate (that incident drove the MOVEMENT DISCIPLINE hardening).
- **kandev-as-a-service survives backend crashes** now; the resume tooling is still needed for
  the *agent* dying, not the backend.

## ops/ tooling

- `ops/kandev-mcp.py` — the MCP client above.
- `ops/resume-driver.py` — self-driving monitor for one task: polls it, on a rate-limit death
  parses the stated reset time, waits, re-triggers via Backlog bounce, restarts the backend if
  down, exits at a human gate / Done. `--run ops/runs/<slug>.md` or `--task … --workflow …`.
  Runs only while its shell lives. (The Claude Code auto-mode classifier has blocked running it
  in the background from within a session — run it yourself, or do manual nudges.)
- `ops/runs/<slug>.md` — one per in-flight feature (task id, workflow id, branch, worktree,
  state, next action). Git-ignored (`!_template.md` kept). **`rm` it when the feature ships.**
- `ops/README.md` — operational notes.

## What has shipped through the workflows (target repo: epglum)

| Feature | Design Doc → | Feature Delivery → |
|---|---|---|
| **F1 — HTTP method hygiene** (39 mutating-GET endpoints → POST) | PR #16 (design + tester checklist), merged | PR #17 (impl, 49 new tests), merged |
| **F2 — read-only impersonation middleware** (blocks unsafe methods while `request.user.is_hijacked`; gated by `FEATURE_USER_IMPERSONATION`; dedicated 403 + htmx notice) | PR #18, merged | PR #19 (squash), merged |

F2 also spawned ~9 follow-up fixes committed straight to epglum `dev` (form_class accordion
saves, backoffice htmx CSRF, finalised-application locks, dashboard tour step, custom scrollbar,
appeal/oppose backoffice list filter). Both features are on `dev`; `dev → cloud-env` (prod) is
the human's next promotion.

## Current status (2026-08-31)

- Kandev consolidated: **`main` only, live instance == committed YAMLs, service healthy, all
  tasks archived, `~/.kandev/tasks/` empty.**
- **Codex wired in as the second plan/spec reviewer** in both workflows. Order is now
  Draft → Claude review → Codex review → next. `codex-review` profile bound to `Review -
  Codex` in the UI (per-step agent binding is UI-only, not settable over MCP), set to
  full-access. **Design Doc smoke test passed 2026-08-31** — Codex auto-started on the
  step, read the plan, approved, routed to Human Approval, stopped at the gate. Feature
  Delivery not separately tested (same review-step wiring).
- `architecture-review` skill is now backed by two `book-to-skill` knowledge bases in
  `~/.claude/skills/` + `~/.gemini/skills/`: **`kleppmann-data-intensive`** (DDIA) and
  **`burns-distributed-systems`**.
- Open / deferred (`§13.4` of the spec doc): `notify` target unconfigured (Human Review /
  Needs Human rely on someone watching the board); `clean-code` not copied to
  `~/.gemini/skills/`; Codex `auto_approve` would not flip via MCP (set it in the UI).
- **Next: a "Kandev workflow upgrade"** — scope still being defined.
