# Architecture & Developer Guide

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                      Clients                              │
│  WebUI (HTML)  │  Android (Kotlin)  │  Desktop (Tauri)   │
│                │  VS Code Extension │  MCP Clients        │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP/SSE/WebSocket
┌────────────────────────┴─────────────────────────────────┐
│                  FastAPI Server                           │
│  src/web.py — 147 endpoints, rate limiting, CORS, auth   │
└──┬─────┬──────┬──────┬──────┬──────┬─────────────────────┘
   │     │      │      │      │      │
┌──┴──┐ ┌┴───┐ ┌┴───┐ ┌┴────┐┌┴───┐ ┌┴──────────────────┐
│Orch.│ │Tool│ │Task│ │Feat.││Upgr│ │   Integrations    │
│     │ │Exec│ │Eng.│ │     ││    │ │ OAuth, GitHub,    │
│Disp.│ │47  │ │Pers│ │Pins ││RAG │ │ Google, Slack     │
│Plan │ │tool│ │Chkp│ │Sched││FAIS│ │ Discord, MCP      │
│Synth│ │    │ │Queu│ │Pref ││    │ │                   │
└──┬──┘ └────┘ └────┘ └─────┘└────┘ └───────────────────┘
   │
┌──┴──────────────────────────────────┐
│         Agent Framework             │
│  BaseAgent → 7 Specialists          │
│  Tool loops, context compression    │
│  Self-correction, confidence score  │
│  Review-revise, reasoning chain     │
└──┬──────────────┬───────────────────┘
   │              │
┌──┴──┐     ┌─────┴──────┐
│Ollam│     │  BitNet    │
│  a  │     │  (CPU)     │
│(GPU)│     │  Port 8081 │
│11434│     └────────────┘
└─────┘
```

## Module Map

### Core (Always Loaded)

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `web.py` | 2200+ | FastAPI server, all endpoints, middleware |
| `tools.py` | 1400+ | 47 tool implementations, registry, execution |
| `config.py` | 40 | Model config, Ollama/BitNet clients |
| `state.py` | 340 | Session state, global state, metrics tracking |
| `persistence.py` | 540 | SQLite, Fernet encryption, user/session CRUD |

### AI (Agent Framework)

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `agents/orchestrator.py` | 600+ | Dispatch planning, parallel execution, synthesis |
| `agents/base.py` | 470+ | BaseAgent with tool loops, streaming, context compression |
| `agents/specialists.py` | 210 | 7 agent definitions (Reasoner, Coder, Researcher, etc.) |
| `agents/scheduler.py` | 175 | BitNet parallel task scheduler |
| `reasoning.py` | 400+ | RAG (FAISS), review-revise, reasoning chain, code validation |

### Features

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `features.py` | 300+ | Search, pins, schedules, preferences, PDF export |
| `task_engine.py` | 350+ | Multi-phase tasks, checkpoints, queue, git rollback |
| `upgrades.py` | 300+ | Request queue, cache, health checks, quality scoring |
| `experiments.py` | 250+ | A/B testing, fine-tuning data, metrics dashboard |
| `platform.py` | 280+ | Sandbox, WebSocket, MCP server, notifications |

### Multimodal

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `multimodal.py` | 510 | Vision, image gen, TTS, STT |
| `tts_preprocessor.py` | 250+ | Text normalization for natural speech |

### Integrations

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `oauth.py` | 240 | GitHub/Google OAuth2 flows |
| `integrations.py` | 270 | GitHub/Google API wrappers |
| `gpu_client.py` | 330 | GPU worker discovery, E2E encryption |

## Request Flow

### Chat Message (Non-Streaming)

```
Client → POST /chat
  → rate limiting check
  → session resolution
  → request queue lock (per-session)
  → build context:
      → recall agent memory
      → inject pinned messages
      → inject user preferences
      → learn from corrections
      → inject location context
      → detect voice request
  → orchestrator.dispatch():
      → inject RAG context (FAISS search)
      → check for reasoning chain (complex task detection)
      → if complex: understand → plan → implement → verify
      → else: detect fast-route or decompose into subtasks
      → BitNet plans on CPU (if enabled)
      → parallel agent execution
      → review-revise on coder output
      → code validation (syntax, types, tests)
      → synthesize final response
  → persist messages to SQLite (encrypted)
  → auto-title session
  → save session metrics
  → auto-synthesize speech (if voice requested)
  → return response
```

### SSE Status Stream

```
Client → GET /stream?session_id=X
  → 2KB padding flush (anti-tunnel-buffering)
  → loop every 0.3s (active) or 1.5s (idle):
      → session tracking snapshot
      → GPU telemetry
      → global counters
      → latest progress log entry
      → GPU worker count
      → yield as SSE data event
```

### Android Polling Fallback

```
When SSE blocked by Cloudflare tunnel:
  → 6s timeout on SSE attempt
  → auto-switch to polling GET /api/metrics every 2s
  → same data, different transport
```

## Database Schema

```sql
-- 14 tables in omni_data.db

users (id, username, password_hash, github_token, google_token, system_prompt, ...)
sessions (id, user_id, title, is_shared, is_archived, last_active, ...)
chat_messages (id, session_id, user_id, role, content[encrypted], created_at)
session_collaborators (session_id, user_id)
session_metrics (session_id, tasks_completed, tokens_in, tokens_out, ...)
user_settings (user_id, settings_json)
agent_memory (id, user_id, category, key, value)
global_state (key, value)  -- OAuth config, global counters
tasks (id, session_id, title, phases[json], checkpoints[json], file_manifest, git_branch, ...)
task_queue (id, session_id, task_description, priority, status)
pinned_messages (id, session_id, message_index, content, note)
scheduled_tasks (id, session_id, description, cron_expr, next_run, ...)
user_preferences (id, user_id, category, key, value, confidence)
```

## Security Model

```
Authentication: bcrypt (cost 12) + auto-upgrade from legacy SHA-256
Encryption: Fernet (AES-128-CBC + HMAC-SHA256) for messages, tokens
Session: 128-bit random hex tokens (32 chars)
CORS: Regex whitelist (localhost + trycloudflare.com)
Rate Limiting: 60/min default, 5/min register, 10/min login
Lockout: 10 failed logins = 5 min lockout
Audit: logs/audit.log — shell, write, edit, git, kill_process
Path Safety: Block /etc/shadow, ~/.ssh, ~/.aws, /proc, /sys
SSRF: Block private IPs, localhost, cloud metadata endpoints
Android: EncryptedSharedPreferences (AES-256-GCM)
GPU Worker: Fernet E2E encryption (PBKDF2 key derivation)
```

## Adding a New Tool

1. Add the function to `src/tools.py`:
```python
def my_tool(arg1: str, arg2: int = 0) -> str:
    """Tool description."""
    return f"Result: {arg1} {arg2}"
```

2. Register in `TOOL_REGISTRY`:
```python
"my_tool": {"fn": "my_tool", "description": "What it does", "args": "arg1, [arg2]"},
```

3. Add timeout in `TOOL_TIMEOUTS`:
```python
"my_tool": 15,
```

4. If toggleable, add to `_tool_toggle_map` in `base.py`:
```python
"my_tool": "shell",  # or "file_read", "web_search", etc.
```

## Adding a New Agent

1. Create a class in `src/agents/specialists.py`:
```python
class MyAgent(BaseAgent):
    name = "my_agent"
    role = "what this agent does"
    model_key = "coding"  # or "reasoning", "general", "security", "fast"
    max_tool_steps = 10
    system_prompt = "Your instructions..."
```

2. It auto-registers via `SPECIALIST_REGISTRY` at the bottom of the file.

## Adding a New API Endpoint

```python
# In src/web.py
class MyReq(BaseModel):
    field: str

@app.post("/api/my-endpoint")
async def my_endpoint(req: MyReq):
    return JSONResponse({"result": req.field})
```

All endpoints automatically get the default 60/min rate limit.

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_integration.py -v

# Run a single test
python -m pytest tests/test_integration.py::TestToolExecution::test_shell -v
```

## Development Mode

```bash
# Hot reload — auto-restarts on Python/template changes
DEV=1 python omni_agent.py
```
