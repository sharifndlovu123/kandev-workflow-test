# Notes: converting the workflow-diagram tool into a Kandev Canvas

Working notes for `feature/canvas-conversion` — not the submission itself. See
`docs/kandev-upstream-contribution-notes.md` for the original PR-vs-issue-first
research; this file picks up after the maintainer (`carlosflorencio`, on
[kdlbs/kandev#3583](https://github.com/kdlbs/kandev/issues/3583)) pointed us at
Canvas instead of a Go/web PR.

## Design decision (2026-09-27): stay task-scoped, don't chase promotion

Per `docs/public/canvases.md`: "A task canvas can read only its own task." A
canvas only gets workspace-wide reads (task list, `workflows/{id}/transition-
groups`) after a human promotes it, and promotion + the wider permission grant
is a bigger step (manual, one-way-ish, needs explicit review).

Decided (Sharif): don't build toward promotion. Keep the canvas honestly
task-scoped, matching the platform's own boundary, and get the "any task"
experience a different way — export the finished canvas as an installable
bundle (`canvases.md`'s Share/install section: `export-defaults` →
`exports` → `.tar.gz`, installed per-task via Settings → Plugins → Canvases →
upload) so any task gets the same view without a new agent build and without
a new permission story.

**Trade-off, stated plainly:** this drops the old tool's one-page "birds-eye
view of every task in a workflow, click any to see its path." You now open
the task you're already looking at. Accepted as the right shape for now
because it doesn't fight the platform's stated boundary.

## Built so far (dummy/test task `1ad02362-c417-4e1a-bba7-9b3cec2d2b1d`, Development workflow, Default Workspace — not a real feature task)

Canvas `81f8af2e-53e2-4fa3-b66d-5ffcee60fb47`, "Step History":
- Round 1: chronological history for the task's own recorded step transitions,
  newest first, FORWARD/BACKWARD/ENTRY badges (derived from step `position`,
  not timestamps), current step flagged by comparing the newest transition's
  destination against the task's live `workflow_step_id`.
- Round 2: added "Visits per step" — a tally of how many times the task was
  moved onto each step, ordered by board position (not frequency). Handles a
  ledger that omits the creation-entry row (some tasks' ledgers may not retain
  it) with a documented fallback.
- Both rounds published clean, `permission_required: false` — declared reads
  are `tasks` + `workflows` only, unchanged from the first release.
- Verified twice independently: once by the building agent (opened the live
  canvas in a real browser, hand-tallied raw transitions against the
  rendered summary), once by us doing the same from this session.

Round 3 (next, pending Sharif's go-ahead): package for export/install rather
than requesting wider access.

## For the eventual PR/submission (do NOT forget this)

Sharif (2026-09-27): when we do the real submission — to `kdlbs/kandev` or
wherever the marketplace/registry PR actually lands, on its own fresh
fork+branch, not this local branch — **add an explicit ask about the
workflow-level / cross-task view we originally wanted and couldn't build**:
being able to pick any task under any step in a workflow and see its full
path + visit counts, not just the task you're currently in. Mention plainly
that we scoped down to per-task because a task canvas can only read its own
task, and ask the maintainers whether a supported path for that exists or is
planned (something short of "promote every task's canvas individually and
grant broad reads by hand") — not a demand, a question about whether it's
possible or already on their roadmap.

## Export/install experiment (2026-10-02) — settled, don't pursue further

Ran the real flow instead of trusting doc wording:
1. `Share canvas` on task 1's canvas → filled License (MIT) → `Prepare downloads`
   → produced a verified, checksummed bundle (`canvas-81f8af2e53e2-1.0.0.tar.gz`,
   7 files: manifest.yaml, index.html, script.js, styles.css, appearance.js,
   README.md, checksums.txt). Also offers "Download source" and "Copy registry
   example" (the marketplace-submission snippet).
2. `Settings → Plugins → Canvases → Install canvas` → uploaded that exact bundle
   → review screen confirmed: same declared permissions (`api_read: tasks,
   workflows`, no writes/events/external origins/shared state) — **but
   `Destination` is always `Default Workspace`, with no field to bind it to one
   task.** Cancelled before confirming (would have created a real workspace
   canvas with workspace-wide reads — not something to commit to mid-experiment).

**Conclusion:** installing a shared bundle always creates a *workspace* canvas,
never a task-scoped one. It's the right mechanism for sharing the design with
other people/workspaces (and for the marketplace), but it is NOT a way to get
"the same canvas on many tasks without a new permission story" inside one
workspace — it hits the exact same scope-widening as Promote. Our script also
has no "which task" picker logic, so even confirming the install wouldn't have
produced something useful today.

**Standardized on reference-copy** (tell a new task's agent to read an
existing, working canvas's files and adapt them) as the real "same design,
any task" path — validated twice now (task 1 → task 2), both published clean
with unchanged, task-scoped permissions, both independently verified live in
the browser.

## Screenshots for the PR

`docs/screenshots/canvas/step-history-task1.png` — task 1 after a second
bounce round: "In Progress: 3 visits", "Review: 3 visits · CURRENT", clean
layout (sidebar/side-panes collapsed).
`docs/screenshots/canvas/step-history-task2.png` — task 2, same design,
independently correct data: "In Progress: 2 visits", "Review: 2 visits ·
CURRENT". Demonstrates the reference-copy result on a second task.

## Prepped for sharing (2026-10-02)

Per Carlos's original pitch ("build yours and share with others" + the
upcoming marketplace), prepped the v2 design canvas for real sharing rather
than leaving it as an internal-only proof:

- `Share canvas` on task 3's canvas, filled in proper package details:
  Author "Sharif Ndlovu" (was the generic "Kandev task agent" default),
  License MIT, Repository URL pointing at this repo, description kept
  accurate to what it actually does.
- Downloaded the installable bundle: `docs/canvas-bundle/step-history-1.0.0.tar.gz`
  (7 files, 6,821 bytes, checksummed). Verified the manifest reflects the
  details above and declares nothing beyond `api_read: tasks, workflows`.
- The "Copy registry example" snippet is a template with placeholder repo/
  preview-image values (`your-org/my-canvas`, `cdn.example.com`) — would need
  real values (and an actual preview image hosted somewhere) before it's
  usable in a real registry submission. Not done yet — that's the actual
  "submit to the marketplace" step, a separate decision from prepping the
  bundle itself.
- Reminder: installing this bundle anywhere (via Settings → Plugins →
  Canvases) always creates a *workspace* canvas, never task-scoped — see the
  export/install experiment above. Anyone installing it gets a workspace-wide
  instance, not bound to one task, even though it only reads `tasks`/
  `workflows` (same scope as ours, just a different instance type).
