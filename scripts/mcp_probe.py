#!/usr/bin/env python3
"""Quick stdio MCP client to list calendar events."""
import json, subprocess, sys, os, time, datetime, threading, queue

TIMEZONE = os.environ.get("TZ", "Europe/London")

class MCPSession:
    def __init__(self, command, env=None):
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **(env or {})}
        )
        self.req_id = 0
        self.lock = threading.Lock()
        self.out_q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self._initialize()

    def _reader(self):
        for line in self.proc.stdout:
            self.out_q.put(json.loads(line))

    def _send(self, msg):
        raw = json.dumps(msg) + "\n"
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def _call(self, method, params=None):
        with self.lock:
            self.req_id += 1
            rid = self.req_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            msg = self.out_q.get(timeout=30)
            if msg.get("id") == rid:
                return msg

    def _initialize(self):
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "kensei-calendar-brief", "version": "1.0.0"}
        })

    def list_tools(self):
        resp = self._call("tools/list")
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name, arguments):
        resp = self._call("tools/call", {"name": name, "arguments": arguments})
        return resp.get("result", {}).get("content", [])

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

# --- config from ~/.hermes/config.yaml ---
import yaml
with open("/home/kensei/.hermes/config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

servers = cfg.get("mcp_servers", {})
results = []

# Google Workspace
if servers.get("google_workspace", {}).get("enabled"):
    gs = servers["google_workspace"]
    env = gs.get("env", {})
    cmd = [gs["command"], *gs.get("args", [])]
    try:
        client = MCPSession(cmd, env=env)
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        cal_tools = [t for t in tool_names if "calendar" in t.lower() or "event" in t.lower()]
        results.append({"server": "google_workspace", "tools": tool_names, "calendar_tools": cal_tools})
        client.close()
    except Exception as e:
        results.append({"server": "google_workspace", "error": str(e)})

# Outlook
if servers.get("outlook", {}).get("enabled"):
    osrv = servers["outlook"]
    env = osrv.get("env", {})
    cmd = [osrv["command"], *osrv.get("args", [])]
    try:
        client = MCPSession(cmd, env=env)
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        cal_tools = [t for t in tool_names if "calendar" in t.lower() or "event" in t.lower()]
        results.append({"server": "outlook", "tools": tool_names, "calendar_tools": cal_tools})
        client.close()
    except Exception as e:
        results.append({"server": "outlook", "error": str(e)})

print(json.dumps(results, indent=2))
