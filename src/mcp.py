"""
MCP (Model Context Protocol) — full implementation.

Supports OmniAgent as both an MCP SERVER (exposing 47 tools to Claude Desktop,
Claude Code, and other MCP clients) and an MCP CLIENT (connecting to external
MCP servers and importing their tools into the agent framework).

Transports:
  - stdio  : JSON-RPC 2.0 over stdin/stdout (for subprocess-based servers)
  - SSE    : Server-Sent Events over HTTP (for web-based servers)

Spec: https://spec.modelcontextprotocol.io/
"""
import json
import sys
import asyncio
import logging
from typing import Any

log = logging.getLogger("mcp")

# ============================================================
# Typed JSON Schemas for all 47 tools
# ============================================================

def _str(desc: str, **kw) -> dict:
    s = {"type": "string", "description": desc}
    s.update(kw)
    return s

def _int(desc: str, default: int | None = None) -> dict:
    s = {"type": "integer", "description": desc}
    if default is not None:
        s["default"] = default
    return s

def _bool(desc: str, default: bool = False) -> dict:
    return {"type": "boolean", "description": desc, "default": default}

TOOL_SCHEMAS: dict[str, dict] = {
    "read": {
        "description": "Read a file's contents. For large files, use offset/limit to read specific line ranges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Absolute or relative path to the file to read"),
                "offset": _int("Line number to start reading from (0-indexed)", 0),
                "limit": _int("Maximum number of lines to read (0 = all)", 0),
            },
            "required": ["path"],
        },
    },
    "write": {
        "description": "Create or overwrite a file. Creates parent directories automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the file to write"),
                "content": _str("Content to write to the file"),
            },
            "required": ["path", "content"],
        },
    },
    "edit": {
        "description": "Surgical text replacement in a file. old_text must match exactly and be unique in the file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the file to edit"),
                "old_text": _str("Exact text to find and replace (must be unique in file)"),
                "new_text": _str("Replacement text"),
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    "shell": {
        "description": "Run a shell command on the host machine. Returns exit code, stdout, and stderr.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": _str("Shell command to execute"),
                "timeout": _int("Timeout in seconds", 60),
            },
            "required": ["cmd"],
        },
    },
    "web": {
        "description": "Search the web via DuckDuckGo. Returns JSON array of results with title, body, and URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("Search query string"),
                "max_results": _int("Maximum number of results to return", 5),
            },
            "required": ["query"],
        },
    },
    "weather": {
        "description": "Get current weather and forecast for a location using Open-Meteo (no API key needed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": _str("City name or location"),
                "forecast_days": _int("Number of forecast days (1-7)", 3),
            },
            "required": ["location"],
        },
    },
    "fetch_url": {
        "description": "Fetch a URL and extract readable text content (strips HTML tags).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": _str("URL to fetch"),
                "max_chars": _int("Maximum characters to return", 8000),
            },
            "required": ["url"],
        },
    },
    "glob": {
        "description": "Find files matching a glob pattern. Use ** for recursive matching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": _str("Glob pattern (e.g. '**/*.py', 'src/*.ts')"),
                "root": _str("Root directory to search from", default="."),
            },
            "required": ["pattern"],
        },
    },
    "grep": {
        "description": "Search file contents using regex. Returns file:line:match format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": _str("Regex pattern to search for"),
                "path": _str("Directory or file to search in", default="."),
                "file_glob": _str("Filter files by glob (e.g. '*.py')", default=""),
                "max_results": _int("Maximum matches to return", 50),
            },
            "required": ["pattern"],
        },
    },
    "tree": {
        "description": "Show project directory structure as a tree. Excludes __pycache__, node_modules, .git.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Root directory", default="."),
                "max_depth": _int("Maximum directory depth to show", 3),
            },
        },
    },
    "git_status": {
        "description": "Show git working tree status in short format.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "git_diff": {
        "description": "Show git diff. Use staged=true for staged changes only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "staged": _bool("Show only staged changes", False),
            },
        },
    },
    "git_log": {
        "description": "Show recent git commits with hash, author, date, and message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": _int("Number of commits to show", 10),
            },
        },
    },
    "git_commit": {
        "description": "Stage all changes and create a git commit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": _str("Commit message"),
            },
            "required": ["message"],
        },
    },
    "git_checkout": {
        "description": "Restore a file to its last committed state (discards uncommitted changes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("File path to restore"),
            },
            "required": ["path"],
        },
    },
    "git_stash": {
        "description": "Git stash operations: push (save work-in-progress), pop (restore), or list stashes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": _str("Stash action: push, pop, or list", default="push"),
            },
        },
    },
    "analyze_file": {
        "description": "Analyze a source file: shows language, imports, function/class definitions, and reverse imports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the source file"),
            },
            "required": ["path"],
        },
    },
    "project_deps": {
        "description": "Show project dependency graph: file counts by language, core modules (most imported).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": _str("Root directory to scan", default="."),
            },
        },
    },
    "find_symbol": {
        "description": "Find all definitions of a function or class name across the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _str("Function or class name to find"),
            },
            "required": ["name"],
        },
    },
    "semantic_search": {
        "description": "Search the codebase semantically using embeddings (requires ChromaDB and indexing).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("Natural language search query"),
            },
            "required": ["query"],
        },
    },
    "vision": {
        "description": "Analyze an image file using a multimodal vision model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": _str("Path to the image file"),
                "prompt": _str("Analysis prompt", default="Describe this image in detail."),
            },
            "required": ["image_path"],
        },
    },
    "generate_image": {
        "description": "Generate an image from a text prompt using Stable Diffusion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": _str("Text description of the image to generate"),
                "negative_prompt": _str("Things to avoid in the image", default=""),
                "width": _int("Image width in pixels", 512),
                "height": _int("Image height in pixels", 512),
            },
            "required": ["prompt"],
        },
    },
    "run_tests": {
        "description": "Run the project's test suite (auto-detects pytest/unittest/npm test).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "spawn_agent": {
        "description": "Launch a specialist sub-agent for a task. Types: reasoner, coder, researcher, planner, tool_user, security, fast.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": _str("Agent type: reasoner, coder, researcher, planner, tool_user, security, or fast"),
                "task": _str("Task description for the sub-agent"),
            },
            "required": ["agent", "task"],
        },
    },
    "speak": {
        "description": "Convert text to speech audio. Returns URL to the generated WAV file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": _str("Text to convert to speech"),
            },
            "required": ["text"],
        },
    },
    "python_eval": {
        "description": "Evaluate a Python expression safely (math, string ops, list comprehensions). No file/network access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": _str("Python expression to evaluate"),
            },
            "required": ["expression"],
        },
    },
    "http_request": {
        "description": "Make an HTTP request (GET/POST/PUT/DELETE). Returns status code and response body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": _str("Request URL"),
                "method": _str("HTTP method: GET, POST, PUT, or DELETE", default="GET"),
                "body": _str("Request body (for POST/PUT)", default=""),
            },
            "required": ["url"],
        },
    },
    "list_dir": {
        "description": "List directory contents with file sizes. Lighter than tree for quick checks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Directory path", default="."),
            },
        },
    },
    "file_info": {
        "description": "Get file metadata: size, modified date, permissions, line count, type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the file"),
            },
            "required": ["path"],
        },
    },
    "diff_preview": {
        "description": "Preview what an edit would look like as a unified diff, without applying it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the file"),
                "old_text": _str("Text to find"),
                "new_text": _str("Replacement text"),
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    "screenshot": {
        "description": "Capture a screenshot of the desktop.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "database": {
        "description": "Execute a read-only SQL query against a SQLite database. Blocks INSERT/UPDATE/DELETE/DROP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("SQL query to execute (SELECT only)"),
                "db_path": _str("Path to SQLite database file", default=""),
            },
            "required": ["query"],
        },
    },
    "docker": {
        "description": "Run read-only Docker commands: ps, images, logs, inspect, stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": _str("Docker command (e.g. 'ps -a', 'logs mycontainer --tail 50')"),
            },
            "required": ["cmd"],
        },
    },
    "pdf_read": {
        "description": "Extract text from a PDF file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the PDF file"),
                "max_pages": _int("Maximum pages to read", 10),
            },
            "required": ["path"],
        },
    },
    "archive": {
        "description": "Work with zip/tar archives: list contents, extract, or create.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": _str("Action: list, extract, or create"),
                "path": _str("Path to the archive file"),
                "dest": _str("Destination directory for extract", default="."),
            },
            "required": ["action", "path"],
        },
    },
    "sandbox_run": {
        "description": "Run code in a Docker sandbox (no network, 256MB RAM limit). Safe for untrusted code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": _str("Code to execute"),
                "language": _str("Programming language: python, node, bash", default="python"),
                "timeout": _int("Timeout in seconds", 30),
            },
            "required": ["code"],
        },
    },
    "deep_research": {
        "description": "Multi-step web research: search, read top results, extract key facts. Better than 'web' for complex questions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _str("Research question"),
                "max_depth": _int("How many levels of follow-up to do", 2),
            },
            "required": ["query"],
        },
    },
    "multi_search": {
        "description": "Run multiple search queries in parallel and combine unique results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of search query strings",
                },
            },
            "required": ["queries"],
        },
    },
    "json_extract": {
        "description": "Extract data from JSON using dot-notation path (e.g. 'data.0.name').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": _str("JSON string to parse"),
                "path": _str("Dot-notation path to extract (e.g. 'users.0.name')", default=""),
            },
            "required": ["data"],
        },
    },
    "env_get": {
        "description": "Get the value of an environment variable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _str("Environment variable name"),
            },
            "required": ["name"],
        },
    },
    "env_set": {
        "description": "Set an environment variable for the current process.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": _str("Environment variable name"),
                "value": _str("Value to set"),
            },
            "required": ["name", "value"],
        },
    },
    "regex_replace": {
        "description": "Find-and-replace with regex in a file. count=0 means replace all occurrences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": _str("Path to the file"),
                "pattern": _str("Regex pattern to match"),
                "replacement": _str("Replacement string (supports \\1 backrefs)"),
                "count": _int("Max replacements (0 = all)", 0),
            },
            "required": ["path", "pattern", "replacement"],
        },
    },
    "batch_edit": {
        "description": "Apply multiple edits to one or more files in a single call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "description": "List of edits, each with path, old_text, new_text",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                },
            },
            "required": ["edits"],
        },
    },
    "process_list": {
        "description": "List running processes sorted by memory usage. Shows PID, name, CPU%, MEM%.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "kill_process": {
        "description": "Send a signal to a process. Default is SIGTERM (15), use 9 for SIGKILL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": _int("Process ID"),
                "signal": _int("Signal number (15=SIGTERM, 9=SIGKILL)", 15),
            },
            "required": ["pid"],
        },
    },
    "network_info": {
        "description": "Show network interfaces and IP addresses.",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


# ============================================================
# JSON-RPC 2.0 helpers
# ============================================================

def _jsonrpc_result(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}

def _jsonrpc_error(id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": err}

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ============================================================
# MCP Server — handles JSON-RPC messages
# ============================================================

SERVER_INFO = {
    "name": "omniagent",
    "version": "8.5.0",
}

SERVER_CAPABILITIES = {
    "tools": {},           # We support tools/list and tools/call
    "resources": {},       # We support resources/list and resources/read
    "prompts": {},         # We support prompts/list and prompts/get
}


class MCPProtocolHandler:
    """Stateful handler for one MCP session (one client connection)."""

    def __init__(self):
        self.initialized = False
        self.client_info: dict = {}

    def handle_message(self, msg: dict) -> dict | None:
        """Process a JSON-RPC message and return a response (or None for notifications)."""
        method = msg.get("method", "")
        id_ = msg.get("id")  # None for notifications
        params = msg.get("params", {})

        # Notifications (no id) — no response expected
        if id_ is None:
            if method == "notifications/initialized":
                self.initialized = True
                log.info("MCP client confirmed initialization")
            elif method == "notifications/cancelled":
                log.info(f"MCP client cancelled request: {params}")
            return None

        # Requests (have id) — must respond
        handler = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
            "completion/complete": self._handle_completion,
        }.get(method)

        if handler is None:
            return _jsonrpc_error(id_, METHOD_NOT_FOUND, f"Unknown method: {method}")

        try:
            result = handler(params)
            return _jsonrpc_result(id_, result)
        except Exception as e:
            log.error(f"MCP handler error for {method}: {e}")
            return _jsonrpc_error(id_, INTERNAL_ERROR, str(e))

    # --- Protocol methods ---

    def _handle_initialize(self, params: dict) -> dict:
        self.client_info = params.get("clientInfo", {})
        log.info(f"MCP initialize from: {self.client_info.get('name', 'unknown')} {self.client_info.get('version', '')}")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": SERVER_INFO,
        }

    def _handle_ping(self, params: dict) -> dict:
        return {}

    def _handle_tools_list(self, params: dict) -> dict:
        tools = []
        for name, schema in TOOL_SCHEMAS.items():
            tools.append({
                "name": name,
                "description": schema["description"],
                "inputSchema": schema["inputSchema"],
            })
        return {"tools": tools}

    def _handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in TOOL_SCHEMAS:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        from src.tools import execute_tool
        result = execute_tool(tool_name, arguments)
        is_error = "ERROR" in str(result)

        return {
            "content": [{"type": "text", "text": str(result)}],
            "isError": is_error,
        }

    def _handle_resources_list(self, params: dict) -> dict:
        """Expose key OmniAgent resources."""
        return {
            "resources": [
                {
                    "uri": "omniagent://config",
                    "name": "OmniAgent Configuration",
                    "description": "Current model config, enabled tools, and system state",
                    "mimeType": "application/json",
                },
                {
                    "uri": "omniagent://metrics",
                    "name": "Live Metrics",
                    "description": "Tasks completed, LLM calls, tokens, GPU stats",
                    "mimeType": "application/json",
                },
                {
                    "uri": "omniagent://agents",
                    "name": "Agent Registry",
                    "description": "Available specialist agents with roles and capabilities",
                    "mimeType": "application/json",
                },
                {
                    "uri": "omniagent://tools",
                    "name": "Tool Registry",
                    "description": "All 47 registered tools with descriptions",
                    "mimeType": "application/json",
                },
            ],
        }

    def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if uri == "omniagent://config":
            from src.config import EXPERTS, BITNET_ENABLED
            from src.state import state
            content = json.dumps({
                "models": EXPERTS,
                "bitnet_enabled": BITNET_ENABLED,
                "enabled_tools": state.enabled_tools,
                "execution_mode": state.execution_mode,
                "model_override": state.model_override,
            }, indent=2)
        elif uri == "omniagent://metrics":
            from src.state import state
            content = json.dumps({
                "tasks_completed": state.tasks_completed,
                "total_llm_calls": state.total_llm_calls,
                "tokens_in": state.session.total_tokens_in,
                "tokens_out": state.session.total_tokens_out,
                "active_model": state.active_model,
            }, indent=2)
        elif uri == "omniagent://agents":
            from src.agents.specialists import SPECIALIST_REGISTRY
            agents = {}
            for name, cls in SPECIALIST_REGISTRY.items():
                agents[name] = {
                    "role": cls.role,
                    "model_key": cls.model_key,
                    "max_tool_steps": cls.max_tool_steps,
                }
            content = json.dumps(agents, indent=2)
        elif uri == "omniagent://tools":
            from src.tools import TOOL_REGISTRY
            tools = {n: {"description": i["description"], "args": i["args"]} for n, i in TOOL_REGISTRY.items()}
            content = json.dumps(tools, indent=2)
        else:
            return {"contents": [{"uri": uri, "text": f"Unknown resource: {uri}", "mimeType": "text/plain"}]}

        return {"contents": [{"uri": uri, "text": content, "mimeType": "application/json"}]}

    def _handle_prompts_list(self, params: dict) -> dict:
        """Expose OmniAgent system presets as MCP prompts."""
        return {
            "prompts": [
                {
                    "name": "code_review",
                    "description": "Review code for bugs, security issues, and improvements",
                    "arguments": [
                        {"name": "file_path", "description": "Path to the file to review", "required": True},
                    ],
                },
                {
                    "name": "explain_code",
                    "description": "Explain what a piece of code does in detail",
                    "arguments": [
                        {"name": "file_path", "description": "Path to the file to explain", "required": True},
                    ],
                },
                {
                    "name": "write_tests",
                    "description": "Generate test cases for existing code",
                    "arguments": [
                        {"name": "file_path", "description": "Path to the file to test", "required": True},
                    ],
                },
                {
                    "name": "debug",
                    "description": "Debug an error or issue in the code",
                    "arguments": [
                        {"name": "error_message", "description": "The error message or symptom", "required": True},
                    ],
                },
                {
                    "name": "refactor",
                    "description": "Refactor code for better structure, readability, or performance",
                    "arguments": [
                        {"name": "file_path", "description": "Path to the file to refactor", "required": True},
                        {"name": "goal", "description": "What to improve (e.g. 'extract method', 'simplify')", "required": False},
                    ],
                },
                {
                    "name": "security_audit",
                    "description": "Perform a security audit on a file or project",
                    "arguments": [
                        {"name": "target", "description": "File path or 'project' for full audit", "required": True},
                    ],
                },
            ],
        }

    def _handle_prompts_get(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        prompts = {
            "code_review": lambda a: f"Review this file for bugs, security vulnerabilities, performance issues, and code quality: {a.get('file_path', '')}",
            "explain_code": lambda a: f"Explain what this code does in detail, including the control flow, data structures, and design decisions: {a.get('file_path', '')}",
            "write_tests": lambda a: f"Write comprehensive tests for this file. Cover edge cases, error paths, and boundary conditions: {a.get('file_path', '')}",
            "debug": lambda a: f"Debug this error. Find the root cause and provide a fix:\n\n{a.get('error_message', '')}",
            "refactor": lambda a: f"Refactor this file{' to ' + a['goal'] if a.get('goal') else ' for better structure and readability'}: {a.get('file_path', '')}",
            "security_audit": lambda a: f"Perform a thorough security audit on {a.get('target', 'the project')}. Check for OWASP Top 10, injection vulnerabilities, auth issues, and data exposure.",
        }

        builder = prompts.get(name)
        if not builder:
            return {"messages": [{"role": "user", "content": {"type": "text", "text": f"Unknown prompt: {name}"}}]}

        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": builder(arguments)}},
            ],
        }

    def _handle_completion(self, params: dict) -> dict:
        """Auto-completion for tool names and argument values."""
        ref = params.get("ref", {})
        ref_type = ref.get("type", "")

        if ref_type == "ref/tool":
            # Complete tool names
            prefix = params.get("argument", {}).get("value", "")
            matches = [n for n in TOOL_SCHEMAS if n.startswith(prefix)]
            return {"completion": {"values": matches[:20], "hasMore": len(matches) > 20}}

        if ref_type == "ref/resource":
            prefix = params.get("argument", {}).get("value", "")
            uris = ["omniagent://config", "omniagent://metrics", "omniagent://agents", "omniagent://tools"]
            matches = [u for u in uris if u.startswith(prefix)]
            return {"completion": {"values": matches}}

        if ref_type == "ref/prompt":
            prefix = params.get("argument", {}).get("value", "")
            names = ["code_review", "explain_code", "write_tests", "debug", "refactor", "security_audit"]
            matches = [n for n in names if n.startswith(prefix)]
            return {"completion": {"values": matches}}

        return {"completion": {"values": []}}


# ============================================================
# Stdio Transport — reads JSON-RPC from stdin, writes to stdout
# ============================================================

class StdioTransport:
    """MCP server over stdin/stdout for subprocess-based usage (Claude Desktop, Claude Code)."""

    def __init__(self):
        self.handler = MCPProtocolHandler()

    def run(self):
        """Blocking main loop — reads from stdin line by line."""
        log.info("MCP stdio server starting...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                resp = _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON")
                self._send(resp)
                continue

            response = self.handler.handle_message(msg)
            if response is not None:
                self._send(response)

    def _send(self, msg: dict):
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


# ============================================================
# MCP Client — connect to external MCP servers
# ============================================================

class MCPClient:
    """Connect to an external MCP server and use its tools."""

    def __init__(self, name: str, transport: str = "stdio", **kwargs):
        self.name = name
        self.transport = transport
        self.kwargs = kwargs
        self.tools: list[dict] = []
        self.resources: list[dict] = []
        self.prompts: list[dict] = []
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    # --- Stdio client ---

    async def connect_stdio(self, command: list[str], env: dict | None = None):
        """Launch an MCP server as a subprocess and connect via stdio."""
        import os
        merged_env = {**os.environ, **(env or {})}
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        self._connected = True
        log.info(f"MCP client: launched subprocess {command}")

        # Initialize
        init_result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "omniagent", "version": "8.5.0"},
        })
        log.info(f"MCP client: connected to {init_result.get('serverInfo', {}).get('name', 'unknown')}")

        # Send initialized notification
        await self._notify("notifications/initialized", {})

        # Discover tools
        tools_result = await self._request("tools/list", {})
        self.tools = tools_result.get("tools", [])
        log.info(f"MCP client: discovered {len(self.tools)} tools from {self.name}")

        # Discover resources (optional)
        try:
            res_result = await self._request("resources/list", {})
            self.resources = res_result.get("resources", [])
        except Exception:
            pass

        # Discover prompts (optional)
        try:
            prompts_result = await self._request("prompts/list", {})
            self.prompts = prompts_result.get("prompts", [])
        except Exception:
            pass

    async def connect_sse(self, url: str):
        """Connect to an MCP server via SSE transport."""
        import urllib.request
        self._sse_url = url
        self._connected = True

        # Initialize via POST
        init_result = await self._sse_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "omniagent", "version": "8.5.0"},
        })
        log.info(f"MCP client (SSE): connected to {init_result.get('serverInfo', {}).get('name', 'unknown')}")

        # Discover tools
        tools_result = await self._sse_request("tools/list", {})
        self.tools = tools_result.get("tools", [])
        log.info(f"MCP client (SSE): discovered {len(self.tools)} tools from {self.name}")

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the remote MCP server."""
        if not self._connected:
            return f"ERROR: MCP client '{self.name}' not connected"

        params = {"name": tool_name, "arguments": arguments}

        if self.transport == "stdio":
            result = await self._request("tools/call", params)
        else:
            result = await self._sse_request("tools/call", params)

        # Extract text from content array
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(result)

    async def read_resource(self, uri: str) -> str:
        """Read a resource from the remote MCP server."""
        if self.transport == "stdio":
            result = await self._request("resources/read", {"uri": uri})
        else:
            result = await self._sse_request("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        return contents[0].get("text", "") if contents else ""

    async def disconnect(self):
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
        self._connected = False

    # --- Internal transport methods ---

    async def _request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request via stdio and wait for response."""
        req = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        self._process.stdin.write((json.dumps(req) + "\n").encode())
        await self._process.stdin.drain()

        line = await asyncio.wait_for(self._process.stdout.readline(), timeout=30)
        resp = json.loads(line.decode())

        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error'].get('message', 'unknown')}")
        return resp.get("result", {})

    async def _notify(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._process.stdin.write((json.dumps(msg) + "\n").encode())
        await self._process.stdin.drain()

    async def _sse_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request via HTTP POST to SSE MCP server."""
        import urllib.request
        req_body = json.dumps({
            "jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params,
        }).encode()
        req = urllib.request.Request(
            self._sse_url,
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        def _do():
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        result = await loop.run_in_executor(None, _do)
        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error'].get('message', 'unknown')}")
        return result.get("result", {})


# ============================================================
# MCP Client Registry — manages connections to external servers
# ============================================================

_mcp_clients: dict[str, MCPClient] = {}


async def register_mcp_server_stdio(name: str, command: list[str], env: dict | None = None) -> dict:
    """Register and connect to an MCP server via stdio transport."""
    client = MCPClient(name, transport="stdio")
    try:
        await client.connect_stdio(command, env)
        _mcp_clients[name] = client
        return {"ok": True, "name": name, "tools": [t["name"] for t in client.tools],
                "resources": len(client.resources), "prompts": len(client.prompts)}
    except Exception as e:
        return {"error": f"Failed to connect: {e}"}


async def register_mcp_server_sse(name: str, url: str) -> dict:
    """Register and connect to an MCP server via SSE/HTTP transport."""
    client = MCPClient(name, transport="sse")
    try:
        await client.connect_sse(url)
        _mcp_clients[name] = client
        return {"ok": True, "name": name, "tools": [t["name"] for t in client.tools]}
    except Exception as e:
        return {"error": f"Failed to connect: {e}"}


def list_mcp_clients() -> list[dict]:
    """List all registered MCP client connections."""
    result = []
    for name, client in _mcp_clients.items():
        result.append({
            "name": name,
            "transport": client.transport,
            "connected": client._connected,
            "tools": [t["name"] for t in client.tools],
            "resources": [r.get("uri") for r in client.resources],
            "prompts": [p.get("name") for p in client.prompts],
        })
    return result


def get_all_mcp_tools() -> list[dict]:
    """Get all tools from all connected MCP servers, prefixed with server name."""
    tools = []
    for name, client in _mcp_clients.items():
        for tool in client.tools:
            tools.append({
                "name": f"{name}__{tool['name']}",
                "server": name,
                "original_name": tool["name"],
                "description": f"[{name}] {tool.get('description', '')}",
                "inputSchema": tool.get("inputSchema", {}),
            })
    return tools


async def call_mcp_tool(server_name: str, tool_name: str, arguments: dict) -> str:
    """Call a tool on a specific MCP server."""
    client = _mcp_clients.get(server_name)
    if not client:
        return f"ERROR: MCP server '{server_name}' not found. Available: {list(_mcp_clients.keys())}"
    return await client.call_tool(tool_name, arguments)


async def disconnect_mcp_server(name: str) -> dict:
    """Disconnect from an MCP server."""
    client = _mcp_clients.pop(name, None)
    if not client:
        return {"error": f"Server '{name}' not found"}
    await client.disconnect()
    return {"ok": True, "name": name}
