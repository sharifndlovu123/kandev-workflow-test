#!/usr/bin/env python3
"""Minimal Kandev MCP client — call any kandev tool from the shell.

Kandev's headless backend exposes an MCP server (streamable HTTP). This wraps the
initialize / notifications/initialized / tools/call handshake so you can poke a
task without a full MCP client.

Usage:
    ./kandev-mcp.py <tool_name> '<args-json>'
    ./kandev-mcp.py list_tasks_kandev '{"workflow_id": "..."}'
    ./kandev-mcp.py --url http://127.0.0.1:PORT list_workspaces_kandev

The backend picks a free port on each `kandev run`; find it in the run log
("[kandev] open: http://localhost:PORT") or pass --url. Default: 38429.
"""
import argparse
import json
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:38429/mcp"
_HEADERS = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}


def _post(url, body, sid=None, timeout=180):
    headers = dict(_HEADERS)
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _session(url):
    r = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "kandev-mcp.py", "version": "1"}}}, timeout=30)
    sid = r.headers.get("Mcp-Session-Id")
    r.read()
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid, timeout=15).read()
    return sid


def call(tool, args, url=DEFAULT_URL):
    """Call a kandev MCP tool. Returns the parsed result (dict), or {'_raw': ...}."""
    sid = _session(url)
    resp = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}, sid).read().decode()
    payload = None
    # backend replies either as bare JSON or as an SSE stream (event: / data: lines)
    try:
        obj = json.loads(resp.strip())
        if obj.get("id") == 2:
            payload = obj
    except ValueError:
        for line in resp.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if obj.get("id") == 2:
                    payload = obj
    if not payload:
        return {"_raw": resp[:800]}
    if "error" in payload:
        return {"_error": payload["error"]}
    text = payload["result"]["content"][0]["text"]
    try:
        return json.loads(text)
    except ValueError:
        return {"_text": text}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tool")
    ap.add_argument("args", nargs="?", default="{}")
    ap.add_argument("--url", default=DEFAULT_URL)
    ns = ap.parse_args()
    url = ns.url if ns.url.endswith("/mcp") else ns.url.rstrip("/") + "/mcp"
    print(json.dumps(call(ns.tool, json.loads(ns.args), url), indent=2))


if __name__ == "__main__":
    sys.exit(main())
