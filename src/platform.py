"""
Platform features — auto model selection, sandboxed execution, WebSocket,
notifications, MCP server support.
"""
import os
import json
import time
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("platform")


# ============================================================
# 1. Auto Model Selection — benchmark installed models
# ============================================================

_model_benchmarks: dict[str, dict] = {}

async def benchmark_models() -> dict:
    """Benchmark installed Ollama models. Returns {model: {speed, quality, size}}."""
    global _model_benchmarks
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        models = json.loads(resp.read().decode()).get("models", [])
    except Exception:
        return {}

    test_prompt = "Write a Python function that sorts a list of integers using quicksort. Include docstring."

    for m in models:
        name = m["name"]
        size_gb = m.get("size", 0) / 1e9
        if name in _model_benchmarks:
            continue

        try:
            from openai import OpenAI
            client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
            start = time.time()
            response = client.chat.completions.create(
                model=name,
                messages=[{"role": "user", "content": test_prompt}],
                max_tokens=200,
            )
            elapsed = time.time() - start
            reply = response.choices[0].message.content or ""
            tokens = getattr(response.usage, 'completion_tokens', len(reply) // 4)
            speed = tokens / elapsed if elapsed > 0 else 0

            # Quality heuristics
            quality = 0.5
            if "def " in reply and "quicksort" in reply.lower():
                quality += 0.2
            if '"""' in reply or "'''" in reply:
                quality += 0.1
            if "return" in reply:
                quality += 0.1
            if len(reply) > 100:
                quality += 0.1

            _model_benchmarks[name] = {
                "speed_tok_s": round(speed, 1),
                "quality": round(min(quality, 1.0), 2),
                "size_gb": round(size_gb, 1),
                "latency_s": round(elapsed, 1),
            }
            log.info(f"Benchmark: {name} — {speed:.0f} tok/s, quality={quality:.1f}, {elapsed:.1f}s")
        except Exception as e:
            log.debug(f"Benchmark failed for {name}: {e}")

    return _model_benchmarks


def get_best_model(role: str = "coding") -> Optional[str]:
    """Get the best model for a role based on benchmarks."""
    if not _model_benchmarks:
        return None
    # Weight quality more for coding/reasoning, speed more for general
    candidates = list(_model_benchmarks.items())
    if role in ("coding", "reasoning", "security"):
        candidates.sort(key=lambda x: x[1]["quality"] * 0.7 + (x[1]["speed_tok_s"] / 100) * 0.3, reverse=True)
    else:
        candidates.sort(key=lambda x: x[1]["quality"] * 0.4 + (x[1]["speed_tok_s"] / 100) * 0.6, reverse=True)
    return candidates[0][0] if candidates else None


# ============================================================
# 2. Sandboxed Code Execution
# ============================================================

def run_sandboxed(code: str, language: str = "python", timeout: int = 30) -> dict:
    """Run code in a Docker container sandbox. Falls back to direct execution if Docker unavailable."""
    # Check if Docker is available
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"sandbox": False, "note": "Docker not available — running directly", "output": _run_direct(code, language, timeout)}

    image = "python:3.13-slim" if language == "python" else "node:20-slim" if language in ("javascript", "js") else "ubuntu:22.04"

    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--network=none",
             "--memory=256m", "--cpus=1", "--pids-limit=50",
             "-i", image, _get_exec_cmd(language)],
            input=code, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "sandbox": True,
            "exit_code": result.returncode,
            "stdout": result.stdout[:5000],
            "stderr": result.stderr[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"sandbox": True, "exit_code": -1, "error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"sandbox": False, "error": str(e), "output": _run_direct(code, language, timeout)}


def _get_exec_cmd(language: str) -> str:
    if language == "python":
        return "python3"
    elif language in ("javascript", "js"):
        return "node"
    elif language == "bash":
        return "bash"
    return "sh"


def _run_direct(code: str, language: str, timeout: int) -> str:
    """Fallback: run directly without sandbox."""
    cmd = _get_exec_cmd(language)
    try:
        result = subprocess.run([cmd], input=code, capture_output=True, text=True, timeout=timeout)
        return f"EXIT:{result.returncode}\n{result.stdout}\n{result.stderr}".strip()
    except Exception as e:
        return f"ERROR: {e}"


# ============================================================
# 3. WebSocket Collaboration (foundation)
# ============================================================

# Connected WebSocket clients per session
_ws_clients: dict[str, list] = {}  # session_id → list of WebSocket connections

async def ws_broadcast(session_id: str, message: dict):
    """Broadcast a message to all WebSocket clients in a session."""
    clients = _ws_clients.get(session_id, [])
    dead = []
    for ws in clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)


async def ws_handler(websocket, session_id: str):
    """Handle a WebSocket connection for real-time collaboration."""
    if session_id not in _ws_clients:
        _ws_clients[session_id] = []
    _ws_clients[session_id].append(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Broadcast to all other clients
            await ws_broadcast(session_id, data)
    except Exception:
        pass
    finally:
        if websocket in _ws_clients.get(session_id, []):
            _ws_clients[session_id].remove(websocket)


# ============================================================
# 4. Notification Integrations
# ============================================================

def send_discord_webhook(webhook_url: str, message: str, title: str = "OmniAgent"):
    """Send a notification to a Discord channel."""
    if not webhook_url:
        return
    try:
        import urllib.request
        body = json.dumps({
            "embeds": [{
                "title": title,
                "description": message[:2000],
                "color": 5814783,  # Blue
                "timestamp": __import__('datetime').datetime.now().isoformat(),
            }]
        }).encode()
        req = urllib.request.Request(webhook_url, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning(f"Discord webhook failed: {e}")


def send_slack_webhook(webhook_url: str, message: str):
    """Send a notification to a Slack channel."""
    if not webhook_url:
        return
    try:
        import urllib.request
        body = json.dumps({"text": f"*OmniAgent*: {message}"}).encode()
        req = urllib.request.Request(webhook_url, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning(f"Slack webhook failed: {e}")


def notify_task_complete(session_id: str, task_summary: str):
    """Send notifications to all configured channels."""
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if discord_url:
        send_discord_webhook(discord_url, task_summary)
    if slack_url:
        send_slack_webhook(slack_url, task_summary)


# ============================================================
# 5. MCP Server Support (Model Context Protocol)
# ============================================================

class MCPServer:
    """Basic MCP server implementation for tool exposure."""

    def __init__(self, name: str = "omniagent", version: str = None):
        self.name = name
        if version is None:
            from src.config import VERSION
            version = VERSION
        self.version = version

    def get_manifest(self) -> dict:
        """Return the MCP server manifest with available tools."""
        from src.tools import TOOL_REGISTRY
        tools = []
        for name, info in TOOL_REGISTRY.items():
            if name == "done":
                continue
            args = info.get("args", "")
            params = {}
            for arg in args.split(","):
                arg = arg.strip().strip("[]")
                if arg:
                    params[arg] = {"type": "string", "description": f"Parameter: {arg}"}
            tools.append({
                "name": name,
                "description": info["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": params,
                },
            })
        return {
            "name": self.name,
            "version": self.version,
            "protocol": "mcp/1.0",
            "tools": tools,
        }

    def execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool via MCP protocol."""
        from src.tools import execute_tool
        result = execute_tool(tool_name, args)
        return {
            "tool": tool_name,
            "result": result,
            "isError": "ERROR" in result,
        }


mcp_server = MCPServer()
