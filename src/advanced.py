"""
Advanced agent features:
- Sub-agent spawning (agents launch child agents)
- Background tasks (non-blocking execution)
- Permission system (ask/auto/deny per tool)
- Hook system (pre/post tool execution)
- Task cancellation (interruptible execution)
- Git worktree isolation
- Auto-test after code changes
- Project-level context (CLAUDE.md-style)
- Conversation branching
- Conversation search
- Message ratings → memory
- Parallel tool calls
- MCP server support (stub)
"""
import os
import json
import asyncio
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from src.state import state


# ============================================================
# Permission System
# ============================================================

class ToolPermission:
    AUTO = "auto"      # Execute without asking
    ASK = "ask"        # Ask user before executing
    DENY = "deny"      # Never execute

# Default permissions — can be overridden per-session
DEFAULT_PERMISSIONS = {
    "read": ToolPermission.AUTO,
    "write": ToolPermission.ASK,
    "edit": ToolPermission.ASK,
    "shell": ToolPermission.ASK,
    "web": ToolPermission.AUTO,
    "fetch_url": ToolPermission.AUTO,
    "weather": ToolPermission.AUTO,
    "glob": ToolPermission.AUTO,
    "grep": ToolPermission.AUTO,
    "tree": ToolPermission.AUTO,
    "git_status": ToolPermission.AUTO,
    "git_diff": ToolPermission.AUTO,
    "git_log": ToolPermission.AUTO,
    "analyze_file": ToolPermission.AUTO,
    "project_deps": ToolPermission.AUTO,
    "find_symbol": ToolPermission.AUTO,
    "semantic_search": ToolPermission.AUTO,
}

_session_permissions: dict[str, dict[str, str]] = {}
_pending_approvals: dict[str, asyncio.Event] = {}
_approval_results: dict[str, bool] = {}


def get_permission(session_id: str, tool_name: str) -> str:
    perms = _session_permissions.get(session_id, DEFAULT_PERMISSIONS)
    return perms.get(tool_name, ToolPermission.AUTO)


def set_permission(session_id: str, tool_name: str, level: str):
    if session_id not in _session_permissions:
        _session_permissions[session_id] = dict(DEFAULT_PERMISSIONS)
    _session_permissions[session_id][tool_name] = level


def get_all_permissions(session_id: str) -> dict[str, str]:
    return _session_permissions.get(session_id, dict(DEFAULT_PERMISSIONS))


async def request_approval(session_id: str, tool_name: str, args: dict) -> bool:
    """Request user approval for a tool execution. Returns True if approved."""
    approval_id = str(uuid.uuid4())[:8]
    event = asyncio.Event()
    _pending_approvals[approval_id] = event
    # Store the request details for the UI to poll
    state.get_session(session_id).pending_approval = {
        "id": approval_id, "tool": tool_name, "args": args,
        "timestamp": datetime.now().isoformat(),
    }
    # Wait for user response (timeout after 60s)
    try:
        await asyncio.wait_for(event.wait(), timeout=60.0)
        return _approval_results.pop(approval_id, False)
    except asyncio.TimeoutError:
        return False
    finally:
        _pending_approvals.pop(approval_id, None)
        if hasattr(state.get_session(session_id), 'pending_approval'):
            state.get_session(session_id).pending_approval = None


def resolve_approval(approval_id: str, approved: bool):
    """Called by the API when user approves/denies a tool execution."""
    _approval_results[approval_id] = approved
    event = _pending_approvals.get(approval_id)
    if event:
        event.set()


# ============================================================
# Hook System
# ============================================================

@dataclass
class Hook:
    event: str       # "pre_tool", "post_tool", "pre_agent", "post_agent"
    command: str     # Shell command to run
    name: str = ""
    enabled: bool = True


_hooks: list[Hook] = []


def register_hook(event: str, command: str, name: str = ""):
    _hooks.append(Hook(event=event, command=command, name=name or f"hook_{len(_hooks)}"))


def run_hooks(event: str, context: dict) -> list[str]:
    """Run all hooks for an event. Returns list of outputs."""
    outputs = []
    for hook in _hooks:
        if hook.event == event and hook.enabled:
            try:
                env = os.environ.copy()
                env.update({f"OMNI_{k.upper()}": str(v) for k, v in context.items()})
                result = subprocess.run(
                    ["/bin/bash", "-c", hook.command],
                    capture_output=True, text=True, timeout=10, env=env,
                )
                outputs.append(result.stdout.strip())
            except Exception as e:
                outputs.append(f"Hook error ({hook.name}): {e}")
    return outputs


def list_hooks() -> list[dict]:
    return [{"name": h.name, "event": h.event, "command": h.command, "enabled": h.enabled} for h in _hooks]


# ============================================================
# Background Tasks
# ============================================================

@dataclass
class BackgroundTask:
    id: str
    session_id: str
    description: str
    status: str = "running"     # running, completed, failed, cancelled
    result: str = ""
    started_at: str = ""
    completed_at: str = ""

_background_tasks: dict[str, BackgroundTask] = {}
_cancel_events: dict[str, asyncio.Event] = {}


def create_background_task(session_id: str, description: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    _background_tasks[task_id] = BackgroundTask(
        id=task_id, session_id=session_id, description=description,
        started_at=datetime.now().isoformat(),
    )
    _cancel_events[task_id] = asyncio.Event()
    return task_id


def complete_background_task(task_id: str, result: str, status: str = "completed"):
    task = _background_tasks.get(task_id)
    if task:
        task.status = status
        task.result = result
        task.completed_at = datetime.now().isoformat()


def cancel_background_task(task_id: str):
    task = _background_tasks.get(task_id)
    if task:
        task.status = "cancelled"
        task.completed_at = datetime.now().isoformat()
    event = _cancel_events.get(task_id)
    if event:
        event.set()


def is_cancelled(task_id: str) -> bool:
    event = _cancel_events.get(task_id)
    return event.is_set() if event else False


def list_background_tasks(session_id: str = None) -> list[dict]:
    tasks = _background_tasks.values()
    if session_id:
        tasks = [t for t in tasks if t.session_id == session_id]
    return [{"id": t.id, "description": t.description, "status": t.status,
             "result": t.result[:200] if t.result else "", "started_at": t.started_at,
             "completed_at": t.completed_at} for t in tasks]


# ============================================================
# Git Worktree Isolation
# ============================================================

def create_worktree(branch_name: str = None) -> dict:
    """Create an isolated git worktree for risky operations."""
    if not branch_name:
        branch_name = f"omni-wt-{uuid.uuid4().hex[:8]}"
    worktree_path = f"/tmp/omni_worktrees/{branch_name}"
    try:
        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, worktree_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return {"path": worktree_path, "branch": branch_name, "ok": True}
        return {"error": result.stderr, "ok": False}
    except Exception as e:
        return {"error": str(e), "ok": False}


def cleanup_worktree(worktree_path: str) -> bool:
    try:
        subprocess.run(["git", "worktree", "remove", worktree_path, "--force"],
                       capture_output=True, timeout=15)
        return True
    except Exception:
        return False


# ============================================================
# Auto-Test After Code Changes
# ============================================================

AUTO_TEST_COMMANDS = {
    "python": ["python3", "-m", "pytest", "-x", "-q", "--tb=short"],
    "javascript": ["npm", "test", "--", "--watchAll=false"],
    "typescript": ["npm", "test", "--", "--watchAll=false"],
    "rust": ["cargo", "test"],
    "go": ["go", "test", "./..."],
}


def detect_project_test_command() -> list[str] | None:
    """Detect the appropriate test command for the project."""
    if os.path.exists("pytest.ini") or os.path.exists("pyproject.toml") or os.path.exists("setup.py"):
        # Use venv python if available, otherwise system python
        venv_python = os.path.join(".venv", "bin", "python")
        if os.path.exists(venv_python):
            return [venv_python, "-m", "pytest", "-x", "-q", "--tb=short"]
        return AUTO_TEST_COMMANDS["python"]
    if os.path.exists("package.json"):
        with open("package.json") as f:
            pkg = json.load(f)
        if "test" in pkg.get("scripts", {}):
            return AUTO_TEST_COMMANDS["javascript"]
    if os.path.exists("Cargo.toml"):
        return AUTO_TEST_COMMANDS["rust"]
    if os.path.exists("go.mod"):
        return AUTO_TEST_COMMANDS["go"]
    # Fallback: check for test directories
    if os.path.exists("tests") or os.path.exists("test"):
        venv_python = os.path.join(".venv", "bin", "python")
        if os.path.exists(venv_python):
            return [venv_python, "-m", "pytest", "-x", "-q", "--tb=short"]
        return AUTO_TEST_COMMANDS["python"]
    return None


def run_auto_test(timeout: int = 120) -> dict:
    """Run the project's test suite. Returns {"passed": bool, "output": str}."""
    cmd = detect_project_test_command()
    if not cmd:
        return {"passed": True, "output": "No test framework detected.", "skipped": True}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        return {"passed": passed, "output": output[-2000:], "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": f"Tests timed out after {timeout}s"}
    except FileNotFoundError:
        return {"passed": True, "output": f"Test runner not found: {cmd[0]}", "skipped": True}


# ============================================================
# Project Context (CLAUDE.md-style)
# ============================================================

PROJECT_CONTEXT_FILES = ["CLAUDE.md", "AGENTS.md", ".omniagent.md", "PROJECT.md"]


def load_project_context(root: str = ".") -> str:
    """Load project-level context from CLAUDE.md or similar files."""
    for filename in PROJECT_CONTEXT_FILES:
        filepath = os.path.join(root, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                return f"PROJECT CONTEXT (from {filename}):\n{content[:3000]}"
            except Exception:
                continue
    return ""


# ============================================================
# Conversation Branching
# ============================================================

def branch_conversation(chat_history: list[dict], branch_from_index: int, new_message: str) -> list[dict]:
    """Create a new conversation branch from a specific message index."""
    if branch_from_index < 0 or branch_from_index >= len(chat_history):
        return chat_history
    # Keep history up to branch point, then add new message
    branched = chat_history[:branch_from_index]
    branched.append({"role": "user", "content": new_message})
    return branched


# ============================================================
# Conversation Search
# ============================================================

def search_conversation(chat_history: list[dict], query: str) -> list[dict]:
    """Search chat history for messages matching the query."""
    query_lower = query.lower()
    results = []
    for i, msg in enumerate(chat_history):
        content = msg.get("content", "")
        if query_lower in content.lower():
            results.append({
                "index": i,
                "role": msg.get("role", ""),
                "content": content[:200],
                "match": True,
            })
    return results


# ============================================================
# Message Ratings → Memory
# ============================================================

def rate_message(user_id: int, message_content: str, rating: str, session_id: str = ""):
    """Rate a message (thumbs_up / thumbs_down) and optionally extract a memory."""
    from src.memory import remember, CATEGORY_PREFERENCE, CATEGORY_CORRECTION

    if rating == "thumbs_down":
        # Store as a correction
        snippet = message_content[:100].strip()
        remember(user_id, CATEGORY_CORRECTION,
                 f"disliked_response_{hash(snippet) % 10000}",
                 f"User disliked this type of response: {snippet}")
    elif rating == "thumbs_up":
        snippet = message_content[:100].strip()
        remember(user_id, CATEGORY_PREFERENCE,
                 f"liked_response_{hash(snippet) % 10000}",
                 f"User liked this type of response: {snippet}")


# ============================================================
# Parallel Tool Calls (parse array of tool calls from LLM)
# ============================================================

def parse_parallel_tools(text: str) -> list[dict] | None:
    """Parse an array of tool calls from LLM output.
    Handles: [{"tool": "read", "args": ...}, {"tool": "grep", "args": ...}]"""
    import re
    # Try to find a JSON array
    start = text.find('[')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                try:
                    result = json.loads(text[start:i+1])
                    if isinstance(result, list) and all(isinstance(x, dict) and "tool" in x for x in result):
                        return result
                except json.JSONDecodeError:
                    pass
                return None
    return None


# ============================================================
# MCP Server Support (stub for future implementation)
# ============================================================

@dataclass
class MCPServer:
    name: str
    url: str
    tools: list[str] = field(default_factory=list)
    connected: bool = False

_mcp_servers: list[MCPServer] = []


def register_mcp_server(name: str, url: str) -> dict:
    """Register an MCP server and discover its tools."""
    server = MCPServer(name=name, url=url)
    try:
        req = urllib.request.Request(f"{url}/tools", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        server.tools = [t.get("name", "") for t in data.get("tools", [])]
        server.connected = True
        _mcp_servers.append(server)
        return {"ok": True, "name": name, "tools": server.tools}
    except Exception as e:
        return {"error": f"Failed to connect to MCP server: {e}"}


def list_mcp_servers() -> list[dict]:
    return [{"name": s.name, "url": s.url, "tools": s.tools, "connected": s.connected} for s in _mcp_servers]


import urllib.request
