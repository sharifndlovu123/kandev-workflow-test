# Feature Delivery Workflow — Design Spec

**Date:** 2026-08-27
**Status:** Approved design, not yet built
**Owner:** Sharif
**Target system:** Kandev v0.91.0 (orchestration layer over Claude Code, Gemini CLI, Codex CLI)

---

## 1. Goal

Orchestrate a repeatable pipeline that takes a well-specified feature task from a
written plan through independent multi-agent review, implementation, testing, code
review, and a human diff gate, into a merged PR — with automated reject/redo loops
and a human escape hatch.

This workflow **assumes an approved feature document already exists** in the repo
(`docs/specs/<feature>.md`). Producing that document is a separate concern (see
§12, "Design Doc workflow") and is out of scope here. The feature doc is immutable
input: the delivery loop can send a *task spec* back for revision, but it cannot
change the feature doc.

### Non-goals

- Building the design-doc pipeline (future, separate workflow, same control shape).
- Parallel reviewers or verdict-aggregation logic (rejected — sequential steps
  map 1:1 onto Kandev's model).
- Auto-merge without a human gate (the human diff review is mandatory).

---

## 2. Environment & divergences from Kandev docs

| Component | State |
|---|---|
| OS | Ubuntu 24.04.4 |
| Go / Node / Docker | 1.26.7 / 24.13.0 / 29.7.2 — all present |
| `claude` | 2.1.247, authenticated |
| `gemini` | 0.57.0 (`@google/gemini-cli`), authenticated, free tier |
| `codex` | **not installed** — needs a ChatGPT paid plan or API-key top-up; deferred |
| `kandev` | 0.91.0, installed globally via npm; runs headless on port 7317; data in `~/.kandev` |
| Test repo | `github.com/sharifndlovu123/kandev-workflow-test` (private), local clone at `/home/sharif/Documents/kandev` |

**Divergences already hit:**

1. **No Homebrew on this box.** Installed via `npm install -g kandev@latest` instead
   of `brew install kdlbs/kandev/kandev`. Functionally identical.
2. **Claude ACP adapter failed to auto-install.** Kandev probes Claude Code by
   running `npx --yes --prefer-offline @agentclientprotocol/claude-agent-acp`; a
   stale npm metadata cache made this fail with
   `ETARGET No matching version found for @anthropic-ai/sdk@>=0.93.0` and the probe
   reported `capability_status: failed` / "peer disconnected before response".
   **Fix:** `npm install -g @agentclientprotocol/claude-agent-acp@latest`, restart
   backend. Same failure mode will likely apply to `codex-acp` when Codex is added.
3. **SSH key not available in the working shell.** Test repo remote set to HTTPS
   via `gh auth setup-git`. Does not affect Kandev, which uses the shell's own git auth.
4. **Backend debug logs** live in `~/.kandev/logs/backend-logs.log` (run with
   `--debug`); the console output is near-useless for ACP failures.
5. **Stale lock on restart:** `~/.kandev/.kandev-backend.lock` must be removed after
   a hard kill before relaunching.

---

## 3. Pipeline overview

11 steps. `[n]` is the 0-based `position`. Two frozen iteration loops plus an escape hatch.

| `[n]` | Step | Agent profile | `on_enter` automations | Kicks back to |
|---|---|---|---|---|
| `[0]` | Backlog | — | — | — |
| `[1]` | Draft *(start)* | `claude-draft` (mode: plan) | `enable_plan_mode`, `auto_start_agent` | — (all rejections land here) |
| `[2]` | Review · Codex | `codex-review` *(disabled until Codex installed)* | `reset_agent_context`, `auto_start_agent` | `[1]` |
| `[3]` | Review · Gemini | `gemini-review` | `reset_agent_context`, `auto_start_agent` | `[1]` |
| `[4]` | Implement | `claude-build` | `reset_agent_context`, `auto_start_agent` | — (test/review failures land here) |
| `[5]` | Test | `claude-build` (fresh) | `reset_agent_context`, `auto_start_agent` | `[4]` |
| `[6]` | Code Review | `claude-build` (fresh) | `reset_agent_context`, `auto_start_agent` | `[4]` |
| `[7]` | Human Review | — | `notify` | `[4]` |
| `[8]` | Integrate | `claude-build` | `auto_start_agent` | — |
| `[9]` | Done | — | `archive_task` (after 168h) | — |
| `[10]` | Needs Human | — | `notify` | — (manual arbitration) |

- **Spec loop:** `[1]` ↔ `[2]`/`[3]`. Runs before any code is written. Reviews judge
  the *plan*, not code.
- **Code loop:** `[4]` ↔ `[5]`/`[6]`/`[7]`. Runs on the implementation. The spec is
  frozen once `[4]` starts.
- Each loop is capped at **3 rounds**; the 3rd failure routes to `[10] Needs Human`
  instead of looping again.

`on_exit` for `[1]`: `disable_plan_mode`.

---

## 4. Transition mechanism

Kandev's `move_task_kandev` MCP tool is the primitive. Signature:
`move_task_kandev(task_id, workflow_id, workflow_step_id, position?, prompt?)`.

- **Mid-turn moves are deferred to turn-end** automatically. So an agent does its
  full analysis, calls `move_task_kandev(...)`, finishes its turn, and Kandev then
  moves the card and (via the target step's `auto_start_agent`) starts the next
  agent — atomically, no race.
- The `prompt` argument is the **cross-agent hand-off message**. It is the only
  channel by which one step passes free-text context to the next agent's fresh
  session.

### Approve path (reviewer / test / code-review step)

`move_task_kandev(next_step, prompt="APPROVED — <one factual line>")`.

### Reject path

Before ending its turn the agent does **two** things:

1. `update_task_plan_kandev` — append a section to the persistent plan:
   ```
   ## Review round N — REJECTED by <agent>
   - <objection 1: file:line, why it matters, what would satisfy it>
   - <objection 2 ...>
   ```
2. `move_task_kandev([1] Draft or [4] Implement, prompt="REJECTED round N — see plan section 'Review round N'. Top issues: …")`.

The rejection rationale lives **in the plan document**, which is durable and
survives context resets. The hand-off `prompt` is a pointer, not the payload.

### Round counter & circuit breaker

- The plan document carries `Revision round: N` (spec loop) and `Build round: N`
  (code loop) near the top.
- The originating step (`[1]` Draft, `[4]` Implement) increments its counter each
  time it re-submits.
- Every reviewing step reads the counter first. A rejection that would push the
  counter to **3 or higher** is not sent back to the originating step; instead the
  reviewer calls
  `move_task_kandev([10] Needs Human, prompt="Stalled after 3 rounds. Core disagreement: …")`.
- Not enforceable in pure YAML (Kandev has no loop-counter automation) — enforced
  by prompt discipline plus the durable counter. Transparent and debuggable.

---

## 5. Fresh-context guarantee

Steps `[2]`, `[3]`, `[4]`, `[5]`, `[6]` carry `reset_agent_context` on enter: the
task's conversation history for that agent is wiped before it starts. The agent
begins with only:

- its **step prompt**,
- the **hand-off `prompt`** from the `move_task_kandev` call that routed it here,
- whatever it **fetches** via MCP (`get_task_plan_kandev`, `get_task_document_kandev`)
  or reads from the repo working tree.

It does **not** see prior rounds' discussion, the drafting agent's reasoning, or
earlier review threads — unless that content was written into the plan document.

### The hand-off leak, and how it is controlled

The `move_task_kandev` `prompt` is context the fresh agent cannot escape. To keep
reviews honest, every step that hands off to a review step is constrained by its
own prompt:

> "Your hand-off prompt MUST be ≤2 sentences and purely factual (e.g. 'Spec saved,
> round N, ready for review'). Put all substance in the plan document. Do not
> argue for your approach in the hand-off."

### Why Implement also resets

Claude implements from the approved plan cold — without the Draft session's
rationalisations ("I know I said X, but Y is close enough") in context.

---

## 6. Agent profiles

Kandev auto-creates bare profiles on first probe. Replace with purpose-built ones.
The workflow YAML matches a profile by exact `{agent_name, model, mode}` triple; a
mismatch silently drops the assignment on import.

| Profile name | Agent (`agent_name`) | `model` | `mode` | Used by | Notes |
|---|---|---|---|---|---|
| `claude-draft` | Claude | `sonnet` | `plan` | `[1]` | Plan mode structurally blocks file writes during drafting. |
| `claude-build` | Claude | `sonnet` | `default` | `[4]`, `[5]`, `[6]`, `[8]` | Full tool access. |
| `gemini-review` | Gemini | `gemini-2.5-pro` (pinned, **not** `auto`) | `default` | `[3]` | Pinned model = reproducible reviews. |
| `codex-review` | Codex | TBD | `default` | `[2]` | Created now, unused until Codex installed. |

`reset_agent_context` gives `[5]` and `[6]` independence from `[4]` even though
they share the `claude-build` profile — same config, separate fresh session.

---

## 7. Executor & isolation

- **Worktree executor** (ships with Kandev). Every task runs in its own
  `git worktree` off the repo clone, so an agent's file changes are isolated until
  merge. A rejected task that already touched files does not pollute the next
  round — the worktree is the task's sandbox.
- Set Worktree as the **workspace default executor** so every task in this
  workflow gets it without per-task selection.

---

## 8. Skills

| Step | Skills the agent is told to invoke |
|---|---|
| `[1]` Draft | `clean-code` (light), `architecture-review` |
| `[2]` Review · Codex / `[3]` Review · Gemini | `architecture-review` |
| `[4]` Implement | `clean-code` |
| `[5]` Test | — |
| `[6]` Code Review | `clean-code`, `architecture-review` |

- `clean-code` — already installed at `~/.claude/skills/clean-code`. Available to
  all Claude steps. **Not** present on the Gemini side.
- `architecture-review` — **to be authored** as a compact stub skill (§8.1),
  installed in both `~/.claude/skills/` and `~/.gemini/skills/`. Later replaced by
  a richer `book-to-skill` conversion (§12).

### 8.1 `architecture-review` stub skill — scope

One page. Contents:

- **Architecture characteristics checklist** — does the spec state which qualities
  matter (performance, scalability, security, modifiability, testability…) and
  make deliberate trade-offs between them?
- **Trade-off framing** — "there are no right answers, only trade-offs"; every
  proposed approach must name what it gives up.
- **Coupling / cohesion checks** — does the change respect module boundaries and
  dependency direction? Are new abstractions real boundaries or single-impl wrappers?
- **Systems-thinking prompts** — what are the second-order effects? What feedback
  loops or downstream modules does this touch? What breaks three steps away?
- **Scope check** — does the task spec stay within the approved feature doc?

---

## 9. Workflow YAML structure (reference for authoring)

Kandev workflows import/export as a portable document. Structure:

```yaml
version: 1                    # must be exactly 1
type: kandev_workflow
workflows:
  - name: Feature Delivery    # required; used for dedup on import
    description: ...
    prompt: |                 # optional shared instructions prepended to every step
      ...
    agent_profile:            # optional workflow-level default
      agent_name: Claude
      model: sonnet
      mode: default
    steps:
      - name: Draft
        position: 1           # 0-based, unique within workflow
        color: bg-purple-500  # Tailwind bg class
        prompt: |             # per-step instructions; {{task_prompt}} interpolates the task
          ...
        is_start_step: true
        show_in_command_panel: true
        allow_manual_move: true
        auto_archive_after_hours: 168   # optional
        agent_profile:
          agent_name: Claude
          model: sonnet
          mode: plan
        events:
          on_enter:
            - type: enable_plan_mode
            - type: auto_start_agent
          on_turn_start: []
          on_turn_complete: []
          on_exit:
            - type: disable_plan_mode
```

### Automation types available

`auto_start_agent`, `reset_agent_context`, `move_to_next`, `move_to_previous`,
`move_to_step` (config: `step_position`), `enable_plan_mode`, `disable_plan_mode`,
`set_session_mode` (config: `mode`), `queue_run`, `queue_run_for_each_participant`,
`clear_decisions`, `create_pr`, `archive_task`, `notify`.

### Event families

`on_enter`, `on_exit`, `on_turn_start`, `on_turn_complete`, `on_message`,
`on_stop`, plus a decision family (`on_approval_resolved`, `on_reject`) tied to a
step's `decision_required` flag.

### `move_to_step` portability

`move_to_step` references the target by `step_position`; the importer rewrites it
to a freshly generated `step_id`. Always reference by position, never by ID.

### This workflow's approach

We rely on **agent-driven `move_task_kandev` calls** (§4) rather than
`on_turn_complete: move_to_next` automations, because the agent's verdict
(approve vs reject) determines the target — a static automation cannot branch on it.
`auto_start_agent` on every working step is the only automation each step strictly
needs. `reset_agent_context` is added where §5 requires it.

---

## 10. Open questions — resolve against the workflow-editor UI before authoring YAML

1. **Disabled step for Codex.** How does Kandev represent a step whose agent is
   unavailable? Options to check: omit `agent_profile` and set `allow_manual_move`
   so a human clicks through; a per-step `enabled` flag; or leave `[2]` out of the
   YAML entirely and insert it later (renumbering positions). Preferred: keep it in,
   find the skip mechanism.
2. **`decision_required` / `on_approval_resolved` semantics.** Can an *agent*
   record an approve/reject decision (vs. only a human)? If yes, a decision-gated
   transition may be cleaner than `move_task_kandev`. If no, `move_task_kandev`
   stands.
3. **`step_complete_kandev` vs `move_task_kandev`.** The binary references
   `auto_advance_requires_signal` and a `step_complete_kandev` tool. Determine
   whether steps should be configured "no auto-advance, agent signals completion"
   and whether that changes the reject wiring.
4. **`create_pr` automation vs. agent-run `gh`.** `[8]` could use the `create_pr`
   automation or have `claude-build` run `gh pr create`. The automation is simpler
   if it supports draft/normal and merge; the agent is more flexible for CI fixup.
5. **`notify` target.** Where does `notify` deliver (desktop, webhook, in-app only)?
   Determines whether `[7]` and `[10]` actually reach Sharif when away.
6. **Model IDs.** Confirm the exact `model` string Kandev expects for the pinned
   Gemini profile (`gemini-2.5-pro` vs a Kandev-internal alias) and for Claude
   (`sonnet` vs `claude-sonnet-...`).

---

## 11. Build & test plan

1. **Author `architecture-review` stub skill**; install to `~/.claude/skills/` and
   `~/.gemini/skills/`.
2. **Create the 4 agent profiles** (UI walk-through or `create_agent_profile_kandev`),
   matching §6 exactly.
3. **Attach the test repo** to the default workspace; set Worktree as default executor.
4. **Resolve §10 open questions** against the workflow editor.
5. **Author the workflow YAML** per §9; `import_workflow_kandev`.
6. **Structure dry-run:** create a trivial task ("add a `capitalize(str)` function
   to `src/strings.js`"), move it to Draft, confirm Claude drafts a plan and it
   saves via `create_task_plan_kandev`.
7. **Reject-loop test:** feed a deliberately weak spec; confirm Gemini rejects it,
   the rationale lands in the plan, and the task returns to Draft with an
   incremented `Revision round`.
8. **Happy path:** run one task end-to-end through merge; confirm the worktree,
   the PR, and the archive.
9. **Codex enablement:** separate session, after the ChatGPT-plan / API-key
   decision. Install `codex`, `npm i -g <codex acp adapter>` if the §2.2 failure
   recurs, populate the `codex-review` profile, flip `[2]` on.

---

## 12. Future work

- **Design Doc workflow.** Same control shape (Draft → sequential fresh-context
  reviews → reject-loop → round cap → human), minus Implement/Test/CodeReview/
  Integrate. Output: `docs/specs/<feature>.md` committed after human approval.
  Clone this workflow, delete the code-side steps, re-prompt for doc review.
- **`architecture-review` from a book.** Run `book-to-skill` on a system-design
  text. Current primary candidate: *Fundamentals of Software Architecture, 2e*
  (Richards/Ford). Secondary: *Learning Systems Thinking* (Bellemare). Deferred
  candidates (adopt only if the app becomes data-intensive / distributed):
  *Designing Data-Intensive Applications* (Kleppmann), *Software Architecture: The
  Hard Parts* (Ford/Richards). The chosen book may change — Sharif will confirm.
  Source from local files and public online libraries.
- **Copy `clean-code` into `~/.gemini/skills/`** if Gemini's role expands to code review.
