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
