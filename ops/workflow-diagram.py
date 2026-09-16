#!/usr/bin/env python3
"""Live block-and-line diagram of a Kandev workflow.

Reads ~/.kandev/data/kandev.db directly (read-only, WAL-safe — Kandev's own
writer is never blocked and never blocks us). No pip installs, no CDN, no
build step: stdlib http.server + a workflow sequence and task timeline rendered client-side in
vanilla JS. See docs/specs/live-workflow-diagram.md for the design.

Usage:
    ./ops/workflow-diagram.py [--port 8420] [--poll-interval 3] [--db PATH]

Then open http://localhost:8420/
"""
import argparse
import json
import pathlib
import sqlite3
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_DB = pathlib.Path.home() / ".kandev/data/kandev.db"

EXPECTED_COLUMNS = {
    "workflows": {"id", "name", "workspace_id"},
    "workflow_steps": {"id", "workflow_id", "name", "position", "color"},
    "tasks": {"id", "workflow_id", "workflow_step_id", "title", "archived_at", "description", "state", "created_at", "updated_at"},
    "task_step_transitions": {
        "task_id", "from_workflow_id", "from_workflow_step_id",
        "to_workflow_step_id", "occurred_at",
    },
}


def ro_connect(db_path):
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def check_schema(db_path):
    """Fail loudly (not silently) if Kandev's schema has drifted from what
    this tool expects — reading an internal, unversioned DB is inherently
    fragile (see the design doc's Risks section)."""
    conn = ro_connect(db_path)
    try:
        for table, cols in EXPECTED_COLUMNS.items():
            found = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not found:
                return f"table '{table}' not found in {db_path} — schema mismatch or wrong DB path"
            missing = cols - found
            if missing:
                return f"table '{table}' is missing expected columns {missing} — Kandev's schema may have changed"
    finally:
        conn.close()
    return None


def get_workflows(db_path):
    conn = ro_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, workspace_id FROM workflows ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_state(db_path, workflow_id):
    conn = ro_connect(db_path)
    try:
        steps = [dict(r) for r in conn.execute(
            "SELECT id, name, position, color, is_start_step "
            "FROM workflow_steps WHERE workflow_id = ? ORDER BY position",
            (workflow_id,),
        )]
        if not steps:
            return None

        tasks = [dict(r) for r in conn.execute(
            "SELECT id, title, workflow_step_id, description, state, created_at, updated_at FROM tasks "
            "WHERE workflow_id = ? AND archived_at IS NULL",
            (workflow_id,),
        )]

        edge_rows = conn.execute(
            "SELECT from_workflow_step_id AS from_id, to_workflow_step_id AS to_id, "
            "COUNT(*) AS cnt FROM task_step_transitions "
            "WHERE from_workflow_id = ? "
            "GROUP BY from_workflow_step_id, to_workflow_step_id",
            (workflow_id,),
        ).fetchall()

        pos_by_id = {s["id"]: s["position"] for s in steps}

        def is_backward(from_id, to_id):
            fp, tp = pos_by_id.get(from_id), pos_by_id.get(to_id)
            if fp is None or tp is None:
                return False
            return tp <= fp

        edges = [
            {
                "from": r["from_id"],
                "to": r["to_id"],
                "count": r["cnt"],
                "backward": is_backward(r["from_id"], r["to_id"]),
            }
            for r in edge_rows
            if r["from_id"] in pos_by_id and r["to_id"] in pos_by_id
        ]

        trails = {}
        for t in tasks:
            trans = conn.execute(
                "SELECT from_workflow_step_id AS from_id, to_workflow_step_id AS to_id, "
                "occurred_at FROM task_step_transitions "
                "WHERE task_id = ? ORDER BY occurred_at",
                (t["id"],),
            ).fetchall()
            trails[t["id"]] = [
                {
                    "from": r["from_id"],
                    "to": r["to_id"],
                    "occurred_at": r["occurred_at"],
                    "backward": is_backward(r["from_id"], r["to_id"]),
                }
                for r in trans
                if r["from_id"] in pos_by_id and r["to_id"] in pos_by_id
            ]

        return {"steps": steps, "tasks": tasks, "edges": edges, "trails": trails}
    finally:
        conn.close()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#ffffff">
<title>Kandev Workflow Diagram</title>
<style>
/* Kandev dark-theme values copied from the local app; no runtime dependency. */
:root { color-scheme:light; --background:oklch(100% 0 0); --foreground:oklch(14.5% 0 0); --card:oklch(100% 0 0);
  --border:oklch(92.2% 0 0); --muted:oklch(55.6% 0 0); --primary:oklch(51% .23 277);
  --accent:oklch(68% .18 276); --return:oklch(58% .22 27); --control-border:oklch(80% 0 0);
  --task-surface:oklch(97% 0 0); --task-border:oklch(86% 0 0); }
.dark { color-scheme:dark; --background:#181818; --foreground:#d4d4d4; --card:#1f1f1f;
  --border:#2a2a2a; --muted:#888; --primary:oklch(59% .2 277);
  --accent:oklch(62% .18 276); --return:oklch(70.4% .191 22.216); --control-border:#444;
  --task-surface:#272727; --task-border:#414141; }
* { box-sizing:border-box; }
body { margin:0; background:var(--background); color:var(--foreground); font:14px/1.5 system-ui,sans-serif; }
button,select { font:inherit; color:inherit; }
button { cursor:pointer; }
button:focus-visible,select:focus-visible,a:focus-visible,[tabindex]:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
header { padding:16px 24px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
h1 { font-size:16px; margin:0; font-weight:600; }
select { background:var(--card); border:1px solid var(--control-border); border-radius:6px; padding:7px 10px; max-width:100%; }
#status { margin-left:auto; color:var(--muted); font-size:12px; }
main { width:min(100%, 1920px); margin:auto; padding:clamp(20px, 3vw, 44px); display:grid; grid-template-columns:minmax(360px, .9fr) minmax(0, 1.6fr); gap:clamp(28px, 4vw, 72px); align-items:start; }
h2 { margin:0; font-size:18px; font-weight:600; }
h3 { margin:0; font-size:14px; }
p { margin:8px 0 0; }
.subtle,time { color:var(--muted); font-size:12px; }
.section-head { margin-bottom:24px; }
#workflow-summary { font-variant-numeric:tabular-nums; }
#workflow-steps { list-style:none; padding:0 0 0 28px; margin:0; }
.step { position:relative; padding-bottom:24px; }
.step:not(:last-child)::before { content:''; position:absolute; top:22px; bottom:-22px; left:-19px; border-left:1px solid #555; }
.step::after { content:''; position:absolute; left:-23px; top:23px; width:7px; height:7px; border-radius:50%; background:#777; box-shadow:0 0 0 5px var(--background); }
.step.visited::after { background:var(--accent); }
.step.current::after { background:var(--accent); box-shadow:0 0 0 4px #34304f; }
.step-card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:14px 16px; }
.step.current .step-card { border-color:var(--accent); }
.step-heading { display:flex; align-items:baseline; gap:12px; justify-content:space-between; }
.step-heading h3 { overflow-wrap:anywhere; font-size:15px; }
.count { white-space:nowrap; color:var(--muted); font-size:12px; }
.current-label { color:#bcb5ff; font-size:12px; margin-top:4px; }
.tasks { display:grid; gap:6px; margin-top:12px; }
.task-marker { width:100%; text-align:left; background:var(--task-surface); border:1px solid var(--task-border); border-radius:5px; padding:9px 10px; overflow-wrap:anywhere; font-size:13px; display:flex; align-items:center; gap:8px; }
.task-marker:hover { filter:brightness(.96); border-color:var(--muted); }
.dark .task-marker:hover { filter:brightness(1.15); }
.task-marker.selected { background:color-mix(in srgb, var(--accent) 18%, var(--card)); border-color:var(--accent); }
.task-marker .task-name { min-width:0; flex:1; }
.task-state { flex:0 0 auto; border:1px solid #555; border-radius:999px; padding:2px 7px; color:var(--muted); font-size:10px; line-height:1.2; white-space:nowrap; }
.task-state.running { color:oklch(42% .12 150); border-color:oklch(58% .12 150); background:color-mix(in srgb, oklch(58% .12 150) 15%, var(--card)); }
.task-state.paused { color:oklch(48% .13 78); border-color:oklch(62% .13 78); background:color-mix(in srgb, oklch(62% .13 78) 18%, var(--card)); }
.task-state.attention { color:var(--return); border-color:var(--return); background:color-mix(in srgb, var(--return) 15%, var(--card)); }
.dark .task-state.running { color:#b7f7c3; background:#17351f; }
.dark .task-state.paused { color:#ffe0a3; background:#3b2c13; }
.dark .task-state.attention { color:#ffc0c0; background:#451f23; }
.task-state.done { color:#b8c0c8; border-color:#555; background:#292929; }
.status-dot { width:8px; height:8px; flex:0 0 8px; border-radius:50%; background:#777; }
.status-dot.running { background:#42d467; box-shadow:0 0 0 0 #42d46766; animation:live-pulse 1.8s ease-out infinite; }
.status-dot.paused { background:#e5a52b; }
.status-dot.attention { background:var(--return); box-shadow:0 0 0 3px #7d292933; }
@keyframes live-pulse { 70% { box-shadow:0 0 0 7px transparent; } 100% { box-shadow:0 0 0 0 transparent; } }
@media (prefers-reduced-motion: reduce) { .status-dot.running { animation:none; } }
.routes { margin:12px 0 0; padding:10px 0 0; border-top:1px solid var(--border); list-style:none; font-size:12px; }
.routes li { display:flex; gap:8px; justify-content:space-between; padding:3px 0; }
.routes span:first-child { overflow-wrap:anywhere; }
.routes .return { color:var(--return); }
#inspection { position:sticky; top:24px; min-width:0; max-height:calc(100vh - 48px); overflow:auto; scrollbar-gutter:stable; }
#selection-empty { padding:28px; border:1px dashed #444; border-radius:8px; }
#selection-empty h2 { font-size:17px; }
#selection-empty p { max-width:48ch; color:var(--muted); }
#task-panel[hidden],#selection-empty[hidden] { display:none; }
.inspection-head { display:flex; align-items:start; gap:16px; justify-content:space-between; margin-bottom:20px; }
#task-title { overflow-wrap:anywhere; margin-top:4px; }
#details-close { background:var(--card); border:1px solid #555; border-radius:5px; padding:6px 10px; flex-shrink:0; font-size:12px; }
#details-close:hover { background:#303030; }
.inspection-body { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(280px,.9fr); gap:clamp(24px, 3vw, 56px); }
#task-path,#task-details { min-width:0; }
#task-details { border-left:1px solid var(--border); padding-left:24px; }
#task-facts { display:grid; gap:12px; margin:16px 0 24px; font-size:13px; }
dt { color:var(--muted); font-size:12px; }
dd { margin:2px 0 0; overflow-wrap:anywhere; }
#task-description { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; }
#timeline { list-style:none; margin:20px 0 0; padding:0 0 0 24px; }
.hop { position:relative; padding:0 0 24px 0; overflow-wrap:anywhere; }
.hop:not(:last-child)::before { content:''; position:absolute; left:-18px; top:12px; bottom:-3px; border-left:1px solid #444; }
.hop::after { content:''; position:absolute; left:-21px; top:6px; width:7px; height:7px; background:#999; border-radius:50%; box-shadow:0 0 0 4px var(--background); }
.hop.return::after { background:var(--return); }
.hop.return strong { color:var(--return); }
.hop strong { display:block; font-size:13px; font-weight:600; }
.hop .origin { margin:3px 0; font-size:12px; color:var(--muted); }
time { display:block; font-size:11px; font-variant-numeric:tabular-nums; }
#path-summary { margin-top:4px; }
#empty { margin:12px 0; }
.skip { position:absolute; left:16px; top:-100px; background:var(--card); padding:10px; z-index:2; }
.skip:focus { top:8px; }
@media(max-width:1100px) { main { gap:24px; grid-template-columns:minmax(260px,360px) minmax(0,1fr); }
  .inspection-body { grid-template-columns:1fr; } #task-details { border-left:0; border-top:1px solid var(--border); padding:20px 0 0; } }
@media(max-width:720px) { header { padding:14px 16px; gap:10px; } #status { width:100%; margin:0; }
  main { display:flex; flex-direction:column; padding:20px 16px; gap:24px; } #workflow,#inspection { width:100%; }
  #inspection { position:static; max-height:none; overflow:visible; } .inspection-head { scroll-margin-top:16px; } }
</style>
</head>
<body>
<a class="skip" href="#workflow">Skip to workflow</a>
<header><h1>Workflow</h1><select id="workflow-picker" aria-label="Workflow"></select><span id="status">Connecting…</span></header>
<main>
<section id="workflow" aria-labelledby="workflow-title">
  <div class="section-head"><h2 id="workflow-title">Workflow steps</h2><p id="workflow-summary" class="subtle"></p><p class="subtle">Top to bottom shows step order. Select a task to see its recorded moves.</p></div>
  <ol id="workflow-steps"></ol><p id="empty" class="subtle" hidden>No recorded moves yet.</p>
</section>
<section id="inspection" aria-label="Selected task">
  <div id="selection-empty"><h2>Follow a task</h2><p>Select a task under any step. Its moves will appear here in time order, with returns clearly marked.</p></div>
  <div id="task-panel" hidden>
    <div class="inspection-head" id="inspection-head" tabindex="-1"><div><span class="subtle">Selected task</span><h2 id="task-title"></h2></div><button id="details-close" type="button">Clear</button></div>
    <div class="inspection-body">
      <section id="task-path" aria-labelledby="trace-title"><h3 id="trace-title">Task path</h3><p id="path-summary" class="subtle"></p><ol id="timeline"></ol></section>
      <section id="task-details" aria-labelledby="details-title"><h3 id="details-title">Task details</h3><dl id="task-facts"></dl></section>
    </div>
  </div>
</section>
</main>
<script>
const POLL_MS = __POLL_MS__;
let selectedWorkflow = null, selectedTask = null, lastState = null;
let lastTaskSteps = null;
let audioContext = null;
function unlockAudio() {
  if (!audioContext) {
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) return;
    audioContext = new AudioCtor();
  }
  if (audioContext.state === 'suspended') audioContext.resume();
}
function playStagePing() {
  if (!audioContext || audioContext.state !== 'running') return;
  const now = audioContext.currentTime;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.setValueAtTime(880, now);
  oscillator.frequency.exponentialRampToValueAtTime(1320, now + 0.09);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.linearRampToValueAtTime(0.035, now + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.16);
  oscillator.connect(gain).connect(audioContext.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.17);
}
document.addEventListener('pointerdown', unlockAudio, {passive:true});
document.addEventListener('keydown', unlockAudio, {passive:true});
function preferredTheme() {
  const saved = localStorage.getItem('theme');
  return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system';
}
function resolvedTheme() {
  const preference = preferredTheme();
  return preference === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : preference;
}
function applyTheme() {
  const theme = resolvedTheme();
  document.documentElement.classList.toggle('dark', theme === 'dark');
  document.documentElement.classList.toggle('light', theme === 'light');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#181818' : '#ffffff');
}
applyTheme();
window.addEventListener('storage', event => { if (event.key === 'theme') applyTheme(); });
matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => { if (preferredTheme() === 'system') applyTheme(); });
// Escape all database text before inserting markup. Descriptions remain plain text.
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function date(value) { if (!value) return 'Time not recorded'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString(); }
function timestamp(value) { return `<time>${esc(date(value))}</time>`; }
function stateInfo(value) {
  const raw = String(value || 'UNKNOWN').toUpperCase();
  if (/PAUS|WAIT|HOLD/.test(raw)) return {label: raw, tone:'paused'};
  if (/ATTENTION|FEEDBACK|REVIEW|BLOCK|ERROR|FAIL/.test(raw)) return {label: raw, tone:'attention'};
  if (/DONE|COMPLETE|ARCHIV/.test(raw)) return {label: raw, tone:'done'};
  if (/RUN|PROGRESS|ACTIVE|IN_PROGRESS/.test(raw)) return {label: raw, tone:'running'};
  return {label: raw, tone:'unknown'};
}
function render(state) {
  if (!state) return;
  const focusId = document.activeElement?.dataset.task;
  if (selectedTask && !state.tasks.some(t => t.id === selectedTask)) selectedTask = null;
  const task = state.tasks.find(t => t.id === selectedTask);
  const trail = task ? state.trails[task.id] || [] : [];
  const names = new Map(state.steps.map(s => [s.id,s.name]));
  const visited = new Set(trail.flatMap(t => [t.from,t.to]));
  const tasksByStep = new Map(state.steps.map(s => [s.id,[]]));
  state.tasks.forEach(t => tasksByStep.get(t.workflow_step_id)?.push(t));
  // Collapse repeated routes in the overview only. The timeline retains every move.
  const routes = new Map();
  trail.forEach(t => {
    const key = JSON.stringify([t.from,t.to]);
    if (!routes.has(key)) routes.set(key,{...t,count:0});
    routes.get(key).count++;
  });
  document.getElementById('workflow-summary').textContent = `${state.steps.length} steps · ${state.tasks.length} active tasks`;
  document.getElementById('empty').hidden = state.edges.length > 0;
  document.getElementById('workflow-steps').innerHTML = state.steps.map(s => {
    const tasks = tasksByStep.get(s.id);
    const outgoing = [...routes.values()].filter(t => t.from === s.id);
    return `<li class="step${visited.has(s.id) ? ' visited' : ''}${task?.workflow_step_id === s.id ? ' current' : ''}"><div class="step-card">
      <div class="step-heading"><h3>${esc(s.name)}</h3><span class="count">${tasks.length} ${tasks.length === 1 ? 'task' : 'tasks'}</span></div>
      ${task?.workflow_step_id === s.id ? '<p class="current-label">Selected task is here</p>' : ''}
      ${tasks.length ? `<div class="tasks">${tasks.map(t => { const state = stateInfo(t.state); return `<button type="button" class="task-marker${t.id === selectedTask ? ' selected' : ''}" data-task="${esc(t.id)}" aria-pressed="${t.id === selectedTask}"><span class="status-dot ${state.tone}" aria-hidden="true"></span><span class="task-name">${esc(t.title)}</span><span class="task-state ${state.tone}">${esc(state.label)}</span></button>`; }).join('')}</div>` : ''}
      ${outgoing.length ? `<ul class="routes" aria-label="Selected task moves from this step">${outgoing.map(t => `<li class="${t.backward ? 'return' : ''}"><span>${t.backward ? '↶ Returned to' : '→ Moved to'} ${esc(names.get(t.to) || 'Unknown step')}</span><span class="count">${t.count}×</span></li>`).join('')}</ul>` : ''}
    </div></li>`;
  }).join('');
  document.querySelectorAll('.task-marker').forEach(button => {
    button.onclick = () => {
      const previous = selectedTask;
      selectedTask = previous === button.dataset.task ? null : button.dataset.task;
      render(lastState);
      if (selectedTask !== previous) document.getElementById('inspection').scrollTop = 0;
      if (selectedTask && matchMedia('(max-width:720px)').matches) {
        document.getElementById('inspection-head').focus({preventScroll:true});
        document.getElementById('inspection-head').scrollIntoView({block:'start'});
      }
    };
    if (button.dataset.task === focusId) button.focus({preventScroll:true});
  });
  document.getElementById('task-panel').hidden = !task;
  document.getElementById('selection-empty').hidden = !!task;
  if (!task) return;
  document.getElementById('task-title').textContent = task.title;
  document.getElementById('path-summary').textContent = `${trail.length} moves · ${trail.filter(t => t.backward).length} returns · newest first`;
  // Keep the current location at the top, then walk backward through recorded moves.
  const current = `<li class="hop current-hop"><strong>Current step: ${esc(names.get(task.workflow_step_id) || 'Unknown step')}</strong>${!trail.length ? '<p class="origin">No recorded moves yet.</p>' : ''}</li>`;
  const newestFirst = [...trail].reverse();
  document.getElementById('timeline').innerHTML = current + newestFirst.map((t,i) => `<li class="hop${t.backward ? ' return' : ''}"><strong>${i+1}. ${t.backward ? 'Returned to' : 'Moved to'} ${esc(names.get(t.to) || 'Unknown step')}</strong><p class="origin">From ${esc(names.get(t.from) || 'Unknown step')}</p>${timestamp(t.occurred_at)}</li>`).join('');
  const taskState = stateInfo(task.state);
  const facts = [['Current step',names.get(task.workflow_step_id) || 'Unknown step'],['State',taskState.label],['Last move',date(trail.at(-1)?.occurred_at)],['Created',date(task.created_at)],['Updated',date(task.updated_at)]];
  document.getElementById('task-facts').innerHTML = facts.map(([key,value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('');
}
document.getElementById('details-close').onclick = () => {
  const id = selectedTask;
  selectedTask = null;
  render(lastState);
  [...document.querySelectorAll('.task-marker')].find(b => b.dataset.task === id)?.focus();
};
document.addEventListener('keydown',event => { if (event.key === 'Escape' && selectedTask) document.getElementById('details-close').click(); });
async function poll() {
  if (!selectedWorkflow) return;
  const workflow = selectedWorkflow;
  const status = document.getElementById('status');
  try {
    const response = await fetch('/api/state?workflow_id=' + encodeURIComponent(workflow));
    if (!response.ok) throw new Error(await response.text());
    const state = await response.json();
    if (workflow !== selectedWorkflow) return;
    // Preserve focus, selection, and reading position when a poll has no data changes.
    const nextTaskSteps = new Map(state.tasks.map(task => [task.id, task.workflow_step_id]));
    if (lastTaskSteps) {
      for (const [taskId, stepId] of nextTaskSteps) {
        if (lastTaskSteps.has(taskId) && lastTaskSteps.get(taskId) !== stepId) playStagePing();
      }
    }
    lastTaskSteps = nextTaskSteps;
    if (JSON.stringify(state) !== JSON.stringify(lastState)) { lastState = state; render(state); }
    status.textContent = 'Live · updated ' + new Date().toLocaleTimeString();
  } catch(error) { if (workflow === selectedWorkflow) status.textContent = 'Unable to refresh. Retrying… ' + error.message; }
}
async function loadWorkflows() {
  try {
    const response = await fetch('/api/workflows');
    if (!response.ok) throw new Error(await response.text());
    const workflows = await response.json();
    const picker = document.getElementById('workflow-picker');
    picker.innerHTML = workflows.map(w => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('');
    picker.onchange = () => { selectedWorkflow = picker.value; selectedTask = null; lastState = null; lastTaskSteps = null; document.getElementById('workflow-steps').replaceChildren(); document.getElementById('task-panel').hidden = true; document.getElementById('selection-empty').hidden = false; poll(); };
    if (!workflows.length) { document.getElementById('status').textContent = 'No workflows available'; return; }
    selectedWorkflow = picker.value;
    await poll();
    setInterval(poll,POLL_MS);
  } catch(error) { document.getElementById('status').textContent = 'Unable to load workflows. Reload to retry. ' + error.message; }
}
loadWorkflows();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    db_path = None

    def log_message(self, fmt, *args):
        pass  # quiet — this is a local dev tool, not a server needing access logs

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.replace("__POLL_MS__", str(self.server.poll_ms)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/workflows":
            self._json(get_workflows(self.db_path))
            return
        if parsed.path == "/api/state":
            qs = urllib.parse.parse_qs(parsed.query)
            workflow_id = (qs.get("workflow_id") or [None])[0]
            if not workflow_id:
                self._json({"error": "workflow_id required"}, status=400)
                return
            state = get_state(self.db_path, workflow_id)
            if state is None:
                self._json({"error": f"workflow_id {workflow_id} not found (no steps)"}, status=404)
                return
            self._json(state)
            return
        self.send_response(404)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--poll-interval", type=float, default=3.0)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ns = ap.parse_args()

    db_path = pathlib.Path(ns.db)
    if not db_path.exists():
        print(f"error: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    err = check_schema(db_path)
    if err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    Handler.db_path = db_path
    server = ThreadingHTTPServer(("127.0.0.1", ns.port), Handler)
    server.poll_ms = int(ns.poll_interval * 1000)
    print(f"Kandev workflow diagram: http://localhost:{ns.port}/")
    print(f"Reading (read-only): {db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
