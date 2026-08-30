# Kandev Multi-Agent Workflow — Implementation Spec

**Status as of:** 2026-08-30
**Purpose:** Orchestrate a `draft → independent review(s) → implement → human-gate` pipeline across coding agents using Kandev.
**State:** Both workflows below are built, hardened, and proven end-to-end on a real codebase (epglum).

---

## 1. Orchestrator Setup

| Item | Value |
|---|---|
| Tool | Kandev — `github.com/kdlbs/kandev`, v0.91.0, installed via `npm i -g` |
| Run mode | systemd `--user` service |
| Install command | `kandev service install --port 38429` |
| Unit file | `~/.config/systemd/user/kandev.service` (`Restart=on-failure`) |
| Port | **Fixed: 38429** |
| Status / restart | `systemctl --user {status,restart} kandev` |
| Logs | `kandev service logs -f` |
| Data root | `~/.kandev/` |
| Database | `~/.kandev/data/kandev.db` (sqlite) |
| Logs file | `~/.kandev/logs/backend-logs.log` |
| Task worktrees | `~/.kandev/tasks/<slug>_<hash>/` (currently empty) |
| Recovery after hard kill | `rm -f ~/.kandev/.kandev-backend.lock` before restart |
| Workspace ID | `692988fd-8e4f-45b4-934e-0c608e10cd40` (the only one) |

### Agent Profile

| Field | Value |
|---|---|
| Profile name | `claude-build` |
| Profile ID | `a8993fd1-e8d3-41b3-806c-81936a54b24d` |
| Agent | `claude-acp` (`b5a7639d…`) |
| Model | `sonnet` |
| Mode | `acceptEdits` |
| Auto-approve | `true` |
| Capability status | `ok` |

**Note:** Gemini / Codex are **not wired up** — everything is Claude-only today. Codex slot is reserved but inactive (needs paid plan / API key).

---

## 2. Repository

| Item | Value |
|---|---|
| Local path | `/home/sharif/Documents/kandev` |
| GitHub | `sharifndlovu123/kandev-workflow-test` (private) |
| Branch | `main` only (all feature branches deleted after merge) |
| Last merge | PR #3 "workflow hardening + ops/", merged 2026-08-30, HEAD `da890c8` |

### Contents

- `workflows/design-doc.yaml` — Design Doc workflow definition
- `workflows/feature-delivery.yaml` — Feature Delivery workflow definition
  - **The live Kandev instance matches these YAMLs exactly** (verified by semantic diff, 2026-08-30)
- `ops/` — tooling (see §6)
- `docs/specs/feature-delivery-workflow.md` — design spec, including:
  - `§13` "build reality" — divergences from original design, session-limit incident history
  - `§13.4` — open items
  - `§13.6` — the `on_turn_start` guard failure

### Test Target Repo (epglum)

| Field | Value |
|---|---|
| Repository ID | `0c3c6b02-6ec2-4b5c-b9c0-c7af417df02c` |
| Default branch | `dev` |
| Local path | `/home/sharif/Documents/vs_code/work/mlankatech/epglum` |
| GitHub | `sonnybrilliant/epglum` |
| Worktree executor profile | `5b235590-0ebb-46f3-8a9e-f413346a9d84` |

---

## 3. Driving Kandev — MCP over HTTP

**Endpoint:** Streamable-HTTP MCP at `http://localhost:38429/mcp`

**Handshake sequence:**
1. `initialize` → returns `Mcp-Session-Id` header
2. `notifications/initialized`
3. `tools/call`

Responses are either bare JSON **or** an SSE stream (`event: message\ndata: {…}` lines).

**Helper script:** `ops/kandev-mcp.py <tool> '<json-args>' [--url http://localhost:38429]`
- Handles both response shapes
- `call(tool, args, url)` is importable

### Common Tools

| Tool | Notes |
|---|---|
| `list_workflows_kandev {workspace_id}` | |
| `list_workflow_steps_kandev {workflow_id}` | |
| `list_tasks_kandev {workflow_id}` | `workflow_id` **required** |
| `list_task_sessions_kandev {task_id}` | |
| `get_task_conversation_kandev {task_id}` | Paginated; current session only |
| `create_task_kandev` | Needs `title`. For a top-level task also pass `workspace_id`, `workflow_id`, `workflow_step_id`, `repository_id`, `base_branch`, `executor_profile_id`, `agent_profile_id`, `prompt` (the agent's only context). `start_agent: false` = placeholder in Backlog. |
| `move_task_kandev {task_id, workflow_id, workflow_step_id, prompt}` | The handoff note is the `prompt` param. **Mid-turn moves are deferred to turn end.** |
| `update_workflow_step_kandev {step_id, prompt, events, …}` | **Does NOT take `agent_profile`** (agent bindings are UI-only). Use to sync live steps to an edited YAML. |
| `export_workflow_kandev {workflow_id}` | Returns a re-importable doc (includes workflow-level `prompt`; strips instance IDs). |
| `import_workflow_kandev {workspace_id, document}` | **Skips any workflow whose name already exists.** This is why live can drift from YAML. To re-import: delete the workflow first (loses task history) or sync step-by-step. |
| `archive_task_kandev` / `delete_task_kandev` | Pass the **full UUID**, not a prefix. |

---

## 4. Workflow Definitions

### 4.1 Design Doc — `6fbfa90f-a831-4d49-994c-be8561b09a3d` (8 steps)

```
Backlog → Draft Doc → Review-Codex → Review-Design → Human Approval → Commit Doc → Done
                                                   ↘ Needs Human
```

| Step | Behavior |
|---|---|
| **Draft Doc** | Plan-mode; writes the design doc into the task plan |
| **Review - Codex** | Reserved, no agent — routed past |
| **Review - Design** | `reset_agent_context`; reject loop, cap 3 |
| **Human Approval** | No-agent gate |
| **Commit Doc** | Writes the doc to the repo's design-doc dir, opens a PR — **does not merge** |
| **Done / Needs Human** | Terminal states |

**Output:** an approved design doc — immutable input to a Feature Delivery task.

#### Step IDs
| Step | ID |
|---|---|
| Backlog | `a5167f08` |
| Draft Doc | `c6cf0503` |
| Review-Codex | `a13d44ce` |
| Review-Design | `0bd3d534` |
| Human Approval | `91757f9e` |
| Commit Doc | `04b01cfd` |
| Done | `1cfe2f7a` |
| Needs Human | `dfecab0c` |

---

### 4.2 Feature Delivery — `f3660f19-d30b-4b9a-8de6-df4cab942d0d` (11 steps)

```
Backlog → Draft → Review-Codex → Review-Spec → Implement → Test → Code Review → Human Review → Integrate → Done
                                            ↘                                              ↘ Needs Human
```

| Step | Behavior |
|---|---|
| **Draft** | Plan-mode; task-level implementation spec |
| **Review - Codex** | Reserved |
| **Review - Spec** | `reset_agent_context`; reject → Draft, cap 3 |
| **Implement** | TDD, commits |
| **Test** | Cold, fresh session, runs the full suite |
| **Code Review** | Fresh session; diffs vs the task's **base branch** (not repo default) |
| **Human Review** | No-agent gate |
| **Integrate** | Formatters, push, `gh pr create --base <task base>` — **no merge**, moves to Done |
| **Done / Needs Human** | Terminal states |

**Assumes:** an approved design doc already exists in the repo.
**Contains:** two 3-round loops (spec, code).

#### Step IDs
| Step | ID |
|---|---|
| Backlog | `4b8982fb` |
| Draft | `4f2b4604` |
| Review-Codex | `40bd92b2` |
| Review-Spec | `f65d6b15` |
| Implement | `8eb731d0` |
| Test | `20c34f50` |
| Code Review | `88044457` |
| Human Review | `c2d0bea7` |
| Integrate | `e1a70990` |
| Done | `aa9d65ff` |
| Needs Human | `e694bb7b` |

---

## 5. Key Mechanics & Hard-Won Lessons

- **The task PLAN is the source of truth, never chat history.** Use `get/create/update_task_plan_kandev` (agent-side tools, not in the external MCP surface). Verdicts and round counters live there.

- **Agents over-help and won't stop.** Recurring failure mode: an agent correctly moves the task to a gate, then keeps going and moves it *past* the gate.
  - **Fix:** every agent step prompt starts with a **MOVEMENT DISCIPLINE** block:
    - Move to EXACTLY ONE step named in this prompt
    - Never move ≥2 steps ahead
    - Never move to Done/Integrate/Commit/Needs Human unless explicitly named
    - If unsure, stop with no move
    - A handoff/resume note never adds work
    - Plan-mode steps never write files
  - Same rules are duplicated in the workflow-level navigation prompt.

- **`on_turn_start` bounce guards were tried and REVERTED** (see `§13.6` of the spec doc). They fire on the deferred-move arrival while the moving agent's session is still bound — so every correct hand-off to a gate bounced straight back into a loop.
  - **Current state: there is no structural gate enforcement — it is prompt-discipline only.**
  - **Real fix (deferred):** linear steps using `on_turn_complete: move_to_step` so the agent has no say in the destination. Needs the runtime step-complete signal plus a way to test a whole cycle without risking a live task.
  - **This is the most likely target of the next "workflow upgrade."**

- **`reset_agent_context` on-enter** gives genuinely fresh, independent review sessions.

- **Live ≠ YAML by default.** `import_workflow_kandev` skips existing names. After editing a YAML:
  1. Sync via `update_workflow_step_kandev` (prompt + events only)
  2. Regenerate the YAML from `export_workflow_kandev`
  3. Re-add the `#` comments by hand

- **Agent bindings are task-level, not step-level.** Live steps show `agent_profile: null` — the agent comes from `create_task_kandev`'s `agent_profile_id` or the workspace default.

- **Claude account session limit (5-hour rolling) kills agents mid-turn.** Happened ~5× during the F1 build.
  - The agent dies without handing off; the task sits.
  - A same-step `move_task` does **NOT** re-fire it.
  - **Re-trigger procedure ("Backlog bounce"):**
    1. `move_task` → Backlog
    2. wait ~4 seconds
    3. `move_task` → the dead step with a *minimal* "CONTINUE, don't restart, re-read the plan + git" prompt
  - **Critical:** a resume prompt must never name a file or a cross-step action — one did, and the task blew past its human gate. This incident is what drove the MOVEMENT DISCIPLINE hardening above.

- **kandev-as-a-service now survives backend crashes.** The resume tooling is still needed for the *agent* dying, not the backend.

---

## 6. `ops/` Tooling

| File | Purpose |
|---|---|
| `ops/kandev-mcp.py` | The MCP client described in §3 |
| `ops/resume-driver.py` | Self-driving monitor for one task: polls it, on a rate-limit death parses the stated reset time, waits, re-triggers via Backlog bounce, restarts the backend if down, exits at a human gate / Done. Invoke via `--run ops/runs/<slug>.md` or `--task … --workflow …`. Runs only while its shell lives. (Note: Claude Code's auto-mode classifier has blocked running it in the background from within a session — run it manually, or do manual nudges.) |
| `ops/runs/<slug>.md` | One per in-flight feature: task id, workflow id, branch, worktree, state, next action. Git-ignored except `!_template.md`. **Delete when the feature ships.** |
| `ops/README.md` | Operational notes |

---

## 7. Shipped Through the Workflows (target repo: epglum)

| Feature | Design Doc → | Feature Delivery → |
|---|---|---|
| **F1 — HTTP method hygiene** (39 mutating-GET endpoints → POST) | PR #16 (design + tester checklist), merged | PR #17 (impl, 49 new tests), merged |
| **F2 — read-only impersonation middleware** (blocks unsafe methods while `request.user.is_hijacked`; gated by `FEATURE_USER_IMPERSONATION`; dedicated 403 + htmx notice) | PR #18, merged | PR #19 (squash), merged |

F2 also spawned ~9 follow-up fixes committed straight to `epglum` `dev` (form_class accordion saves, backoffice htmx CSRF, finalised-application locks, dashboard tour step, custom scrollbar, appeal/oppose backoffice list filter).

Both features are on `dev`. **Next promotion: `dev` → `cloud-env` (prod)** — human-driven.

---

## 8. Current Status (2026-08-30)

- Kandev consolidated: `main` only, live instance == committed YAMLs, service healthy, all tasks archived, `~/.kandev/tasks/` empty.
- `architecture-review` skill now backed by two `book-to-skill` knowledge bases in `~/.claude/skills/` + `~/.gemini/skills/`:
  - `kleppmann-data-intensive` (DDIA)
  - `burns-distributed-systems`

### Open / Deferred (`§13.4` of spec doc)

- `notify` target unconfigured — Human Review / Needs Human rely on someone watching the board
- Codex slot reserved but inactive — needs a paid plan / API key
- `clean-code` skill not copied to `~/.gemini/skills/` — Claude-only for now

### Next

**"Kandev workflow upgrade"** — scope still being defined. Leading candidate per §5: replace prompt-discipline gate enforcement with structural `on_turn_complete: move_to_step` linear steps, once the runtime step-complete signal and a safe cycle-test method are available.

---

## 9. Relevant Automation & Remote-Operation Context (from prior discussion)

For the planned "start it and walk away for 3–5 days" automation:

- **Kandev supports headless operation** (`--headless` / `KANDEV_NO_BROWSER=1`) and already runs as a systemd service here (§1) — compatible with unattended operation.
- **Remote trigger options:** REST API, or a workspace automation with a webhook trigger (`POST /api/v1/automations/webhook/{automationId}`).
- **Pi's role (decided):** local watchdog — polls task/run status, sends Wake-on-LAN to the main machine when a job is queued, SSHs in to shut it down after a grace period once all tasks reach a terminal state, and alerts on `WAITING_FOR_INPUT` / `FAILED` / stuck states (a run cannot itself answer a live permission prompt).
- **Given §5 above** (no structural gate enforcement, session-limit deaths, resume-prompt fragility), the Pi/automation layer will need to reuse or extend `ops/resume-driver.py`'s Backlog-bounce recovery logic rather than assuming Kandev's native retry alone is sufficient for a multi-day unattended run.
