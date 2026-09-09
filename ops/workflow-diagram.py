#!/usr/bin/env python3
"""Live block-and-line diagram of a Kandev workflow.

Reads ~/.kandev/data/kandev.db directly (read-only, WAL-safe — Kandev's own
writer is never blocked and never blocks us). No pip installs, no CDN, no
build step: stdlib http.server + hand-rolled SVG rendered client-side in
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
    "tasks": {"id", "workflow_id", "workflow_step_id", "title", "archived_at"},
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
            "SELECT id, title, workflow_step_id FROM tasks "
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
<html>
<head>
<meta charset="utf-8">
<title>Kandev Workflow Diagram</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 0; background: #0b0d10; color: #e6e8eb; }
  header { padding: 12px 16px; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid #23262b; }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; color: #9aa4b2; }
  select { background: #14171c; color: #e6e8eb; border: 1px solid #2a2e35; border-radius: 6px; padding: 6px 10px; font: inherit; }
  #status { margin-left: auto; font-size: 12px; color: #6b7280; }
  #canvas-wrap { overflow: auto; }
  svg { display: block; }
  .step-box { fill-opacity: 0.18; stroke-width: 1.5; rx: 8; }
  .step-label { fill: #e6e8eb; font-size: 12px; font-weight: 600; text-anchor: middle; }
  .edge-forward { fill: none; stroke: #4b5563; stroke-width: 1.5; }
  .edge-backward { fill: none; stroke: #ef4444; stroke-width: 1.5; stroke-dasharray: 5 4; }
  .edge-dim { opacity: 0.15; }
  .edge-highlight { stroke-width: 3; opacity: 1 !important; }
  .task-marker { cursor: pointer; }
  .task-marker rect { fill: #1f6feb; stroke: #58a6ff; stroke-width: 1; rx: 10; }
  .task-marker text { fill: #fff; font-size: 10px; text-anchor: middle; pointer-events: none; }
  .task-marker.selected rect { fill: #f59e0b; stroke: #fbbf24; }
  #empty { padding: 40px; color: #6b7280; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Kandev Workflow Diagram</h1>
  <select id="workflow-picker"></select>
  <span id="status">connecting...</span>
</header>
<div id="canvas-wrap"><svg id="canvas" width="100%" height="500"></svg></div>
<div id="empty" style="display:none">No transition history yet for this workflow — steps will appear once tasks start moving.</div>

<script>
const POLL_MS = __POLL_MS__;
let selectedWorkflow = null;
let selectedTask = null;
let lastState = null;

const NODE_W = 150, NODE_H = 56, NODE_GAP = 90, ROW_Y = 220;

async function loadWorkflows() {
  const r = await fetch('/api/workflows');
  const workflows = await r.json();
  const picker = document.getElementById('workflow-picker');
  picker.innerHTML = workflows.map(w => `<option value="${w.id}">${w.name}</option>`).join('');
  picker.onchange = () => { selectedWorkflow = picker.value; selectedTask = null; poll(); };
  if (workflows.length) { selectedWorkflow = workflows[0].id; picker.value = selectedWorkflow; }
}

function stepX(index) { return 40 + index * (NODE_W + NODE_GAP); }

function edgeKey(e) { return e.from + '->' + e.to; }

function render(state) {
  const svg = document.getElementById('canvas');
  const empty = document.getElementById('empty');
  if (!state) {
    svg.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  const steps = state.steps;
  const xByStep = {};
  steps.forEach((s, i) => xByStep[s.id] = stepX(i));
  const width = Math.max(800, stepX(steps.length));

  svg.setAttribute('width', width);
  svg.setAttribute('height', 480);

  let defs = `<defs>
    <marker id="arrow-fwd" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#4b5563"/></marker>
    <marker id="arrow-back" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#ef4444"/></marker>
  </defs>`;

  // stack multiple edges sharing the same direction+span at increasing arc height
  const spanCounts = {};
  function arcHeight(fromX, toX, backward) {
    const span = Math.abs(toX - fromX);
    const key = (backward ? 'b' : 'f') + ':' + Math.min(fromX, toX) + ':' + Math.max(fromX, toX);
    const n = spanCounts[key] = (spanCounts[key] || 0);
    spanCounts[key] = n + 1;
    const base = 40 + span * 0.25 + n * 30;
    return backward ? base : -base;
  }

  let edgesSvg = '';
  const highlightKeys = new Set();
  if (selectedTask && state.trails[selectedTask]) {
    state.trails[selectedTask].forEach(t => highlightKeys.add(edgeKey(t) + ':' + t.occurred_at));
  }

  state.edges.forEach(e => {
    const fx = xByStep[e.from] + NODE_W / 2, fy = ROW_Y;
    const tx = xByStep[e.to] + NODE_W / 2, ty = ROW_Y;
    const h = arcHeight(fx, tx, e.backward);
    const midX = (fx + tx) / 2;
    const cls = e.backward ? 'edge-backward' : 'edge-forward';
    const marker = e.backward ? 'arrow-back' : 'arrow-fwd';
    const dim = selectedTask ? ' edge-dim' : '';
    edgesSvg += `<path class="${cls}${dim}" d="M${fx},${fy} Q${midX},${fy + h} ${tx},${ty}" marker-end="url(#${marker})"/>`;
    if (e.count > 1) {
      edgesSvg += `<text x="${midX}" y="${fy + h * 0.6}" font-size="10" fill="#6b7280" text-anchor="middle">${e.count}x</text>`;
    }
  });

  // per-task trail highlight, drawn on top
  let trailSvg = '';
  if (selectedTask && state.trails[selectedTask]) {
    const trail = state.trails[selectedTask];
    spanCounts.__reset = 0;
    const localSpan = {};
    trail.forEach((t, idx) => {
      const fx = xByStep[t.from] + NODE_W / 2, fy = ROW_Y;
      const tx = xByStep[t.to] + NODE_W / 2, ty = ROW_Y;
      const span = Math.abs(tx - fx);
      const key = (t.backward ? 'b' : 'f') + ':' + Math.min(fx, tx) + ':' + Math.max(fx, tx);
      const n = localSpan[key] = (localSpan[key] || 0);
      localSpan[key] = n + 1;
      const base = 40 + span * 0.25 + n * 30;
      const h = t.backward ? base : -base;
      const midX = (fx + tx) / 2;
      const cls = t.backward ? 'edge-backward' : 'edge-forward';
      trailSvg += `<path class="${cls} edge-highlight" d="M${fx},${fy} Q${midX},${fy + h} ${tx},${ty}" marker-end="url(#${t.backward ? 'arrow-back' : 'arrow-fwd'})"/>`;
    });
  }

  let nodesSvg = '';
  steps.forEach((s, i) => {
    const x = stepX(i);
    nodesSvg += `<rect class="step-box" x="${x}" y="${ROW_Y - NODE_H/2}" width="${NODE_W}" height="${NODE_H}" style="fill:#3b82f6;stroke:#3b82f6"/>`;
    nodesSvg += `<text class="step-label" x="${x + NODE_W/2}" y="${ROW_Y + 4}">${s.name}</text>`;
  });

  // stack task markers per step
  const stackCount = {};
  let tasksSvg = '';
  state.tasks.forEach(t => {
    const x = xByStep[t.workflow_step_id];
    if (x === undefined) return;
    const n = stackCount[t.workflow_step_id] = (stackCount[t.workflow_step_id] || 0);
    stackCount[t.workflow_step_id] = n + 1;
    const my = ROW_Y + NODE_H/2 + 16 + n * 26;
    const label = t.title.length > 20 ? t.title.slice(0, 19) + '…' : t.title;
    const sel = t.id === selectedTask ? ' selected' : '';
    tasksSvg += `<g class="task-marker${sel}" data-task="${t.id}" transform="translate(${x + NODE_W/2 - 65},${my})">
      <rect width="130" height="20"/>
      <text x="65" y="14">${label}</text>
    </g>`;
  });

  svg.innerHTML = defs + edgesSvg + trailSvg + nodesSvg + tasksSvg;

  svg.querySelectorAll('.task-marker').forEach(el => {
    el.onclick = () => {
      const id = el.getAttribute('data-task');
      selectedTask = selectedTask === id ? null : id;
      render(lastState);
    };
  });
}

async function poll() {
  if (!selectedWorkflow) return;
  const status = document.getElementById('status');
  try {
    const r = await fetch('/api/state?workflow_id=' + encodeURIComponent(selectedWorkflow));
    if (!r.ok) { status.textContent = 'error: ' + (await r.text()); return; }
    const state = await r.json();
    lastState = state;
    render(state);
    status.textContent = 'live · updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    status.textContent = 'connection error: ' + e;
  }
}

loadWorkflows().then(() => { poll(); setInterval(poll, POLL_MS); });
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
