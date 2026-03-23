# OmniAgent v8.6.0

**Fully local, autonomous AI agent framework** — 47 tools, 7 specialist agents, multi-phase task execution, running entirely on your hardware with no cloud API keys required.

## Platforms

| Platform | Status | Location |
|----------|--------|----------|
| **WebUI** | Production | `http://localhost:8000` |
| **Android** | Production | `android/app/build/outputs/apk/debug/app-debug.apk` |
| **Linux Desktop** | Production | `desktop/src-tauri/target/release/bundle/deb/` |
| **GPU Worker** | Optional | `gpu_worker.py` (second PC) |
| **Smart Hub** | Production | `smarthub/` (native C, 90KB, OrangePi/any Linux) |
| **MCP Server** | Production | `mcp_server.py` (stdio for Claude Desktop/Code) |

## Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull models
ollama pull qwen3:8b
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:8b

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Start OmniAgent
python omni_agent.py

# Open http://localhost:8000 in your browser
```

### Docker

```bash
docker compose up -d
docker compose exec ollama ollama pull qwen3:8b qwen2.5-coder:7b deepseek-r1:8b
# Open http://localhost:8000
```

### Development Mode (hot reload)

```bash
DEV=1 python omni_agent.py
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Clients                           │
│  WebUI  │  Android  │  Desktop (Tauri)  │  VS Code  │
└────────────────────┬────────────────────────────────┘
                     │ REST/SSE/WebSocket
┌────────────────────┴────────────────────────────────┐
│              FastAPI Server (155 endpoints)           │
│  Auth │ Chat │ Tools │ Tasks │ OAuth │ Scheduler     │
└──┬──────┬──────┬──────┬──────┬──────────────────────┘
   │      │      │      │      │
┌──┴──┐ ┌─┴──┐ ┌┴───┐ ┌┴───┐ ┌┴────────────┐
│Orch.│ │RAG │ │47  │ │Task│ │ Integrations │
│     │ │FAIS│ │Tool│ │Eng.│ │ GitHub/Google│
│7 AI │ │    │ │    │ │    │ │ Slack/Discord│
│Agent│ │    │ │    │ │    │ │              │
└──┬──┘ └────┘ └────┘ └────┘ └──────────────┘
   │
┌──┴─────────────────────────────┐
│        LLM Backends            │
│ Ollama │ BitNet │ GPU Worker   │
│ (GPU)  │ (CPU)  │ (Remote PC)  │
└────────────────────────────────┘
```

## Models

| Role | Default Model | Purpose |
|------|--------------|---------|
| General/Orchestrator | `qwen3:8b` | Task decomposition, synthesis |
| Coding | `qwen2.5-coder:7b` | Code generation, editing, debugging |
| Reasoning | `deepseek-r1:8b` | Chain-of-thought analysis, planning |
| Security | `dolphin3:8b` | Security research, vulnerability analysis |
| Fast | `bitnet-2b` | Dispatch planning, classification (CPU) |
| On-Device | Gemini Nano | Query rewrite, intent, sentiment, summarize (NPU) |
| Vision | `qwen3-vl:8b` | Image analysis |

## Key Features

### AI Intelligence
- **7 specialist agents** — Reasoner, Coder, Researcher, Planner, ToolUser, Security, Fast
- **47 tools** — File I/O, shell, web search, git, vision, TTS/STT, image gen, sandboxed execution
- **Multi-phase task engine** — Break complex tasks into phases with checkpointing, git rollback, approval gates
- **RAG with FAISS** — Automatic codebase indexing, semantic vector search for relevant context
- **Review-revise pipeline** — Reasoning model checks coder output before returning
- **Structured reasoning chain** — understand → plan → implement → verify for complex tasks
- **Code validation** — Syntax check, type check (mypy), test runner after every file edit
- **Model A/B testing** — Compare two models side-by-side on the same prompt
- **BitNet** — 1.58-bit 2B model runs on CPU for dispatch planning, freeing GPU
- **On-device NPU** — Galaxy S24 Ultra Snapdragon 8 Gen 3 Hexagon NPU for local inference
- **Gemini Nano** — On-device LLM via Google AI Core for query rewriting, intent classification, sentiment, summarization, and smart replies — all without server round-trip

### MCP (Model Context Protocol)

- **MCP Server** — Expose all 47 tools to Claude Desktop, Claude Code, or any MCP client via stdio or HTTP
- **MCP Client** — Connect to external MCP servers (stdio subprocess or SSE/HTTP) and auto-import their tools
- **46 typed schemas** — Proper JSON Schema with integer/boolean/array types, required fields, defaults
- **Resources** — 4 queryable resources (config, metrics, agents, tools)
- **Prompts** — 6 reusable prompts (code review, debug, refactor, etc.)
- **Auto-completion** — Tool names, resource URIs, prompt names

### Voice
- **STT** — faster-whisper for speech-to-text
- **TTS** — piper with Amy voice model, smart text preprocessor (100+ abbreviations, symbols, code syntax)
- **Auto-trigger** — Say "speak to me" or "use voice" and the response is spoken aloud

### Collaboration
- **Multi-user sessions** — Shared chat sessions with collaborator invites
- **WebSocket presence** — Real-time typing indicators
- **OAuth2** — One-click connect for GitHub (repo, gist) and Google (Drive, Gmail, Tasks)

### Security
- **PBKDF2 password hashing** with auto-upgrade from older hashes
- **Fernet encryption** (AES-128-CBC + HMAC-SHA256) for all chat messages and tokens
- **CORS restricted** to localhost + Cloudflare tunnels
- **Rate limiting** — 60/min default on all 155 endpoints
- **Login lockout** — 10 failed attempts = 5 min lockout
- **Audit log** — All shell commands, file writes, logins logged
- **Sandboxed execution** — Run untrusted code in Docker containers
- **EncryptedSharedPreferences** on Android

### Long-Running Tasks
- **Task persistence** in SQLite — survives server restarts
- **Multi-phase plans** — LLM decomposes complex tasks into 2-6 phases
- **Approval gates** — Pause before destructive phases, user approves to continue
- **Git branch/rollback** — Creates `task/XXXXXXXX` branch, rollback on failure
- **File manifest** — Tracks every file created, modified, deleted
- **Task queue** — "Do X, then Y, then Z" with priorities
- **Scheduled tasks** — Cron-style: "daily", "hourly", "30m", "weekly"

## MCP (Model Context Protocol)

OmniAgent is a full MCP server **and** client — it can expose its 47 tools to Claude Desktop/Code, and connect to external MCP servers to import their tools.

### As MCP Server (expose tools to Claude)

**stdio transport** (Claude Desktop / Claude Code):

```bash
# Claude Code:
claude mcp add omniagent python /path/to/OmniAgent/mcp_server.py

# Claude Desktop (~/.config/claude/claude_desktop_config.json):
{
  "mcpServers": {
    "omniagent": {
      "command": "python",
      "args": ["/path/to/OmniAgent/mcp_server.py"]
    }
  }
}
```

**HTTP transport** (web-based MCP clients):

```bash
# JSON-RPC endpoint:
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### As MCP Client (import external tools)

```bash
# Connect to an external MCP server via stdio:
curl -X POST http://localhost:8000/api/mcp/register/stdio \
  -d '{"name": "filesystem", "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}'

# Connect via SSE/HTTP:
curl -X POST http://localhost:8000/api/mcp/register/sse \
  -d '{"name": "remote", "url": "http://other-server:3000/mcp"}'
```

External tools are automatically available to all agents via `server__tool` naming.

## GPU Worker (Second PC)

Offload image generation, video generation, and result verification to a second machine.

```bash
# On the second PC:
python gpu_worker.py

# With E2E encryption:
WORKER_SECRET=mykey python gpu_worker.py
```

### WSL2 Setup (Windows)
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\setup-gpu-worker-wsl.ps1
```

## Project Structure

```
OmniAgent/
├── omni_agent.py          # Entry point — starts all services
├── gpu_worker.py          # Standalone GPU worker for second PC
├── src/
│   ├── web.py             # FastAPI server (155 endpoints)
│   ├── tools.py           # 47 tool implementations
│   ├── config.py          # Model configuration
│   ├── state.py           # Session state management
│   ├── persistence.py     # SQLite + Fernet encryption
│   ├── reasoning.py       # RAG, review-revise, reasoning chain
│   ├── task_engine.py     # Multi-phase task persistence + queue
│   ├── upgrades.py        # Reliability + performance systems
│   ├── features.py        # Search, pins, scheduling, preferences
│   ├── experiments.py     # A/B testing, fine-tuning, dashboard
│   ├── platform.py        # Sandbox, WebSocket, MCP, notifications
│   ├── multimodal.py      # Vision, image gen, TTS, STT
│   ├── tts_preprocessor.py# Text normalization for natural speech
│   ├── oauth.py           # GitHub/Google OAuth2 flows
│   ├── mcp.py             # MCP protocol (server + client, stdio + SSE)
│   ├── gpu_client.py      # GPU worker discovery + E2E encryption
│   ├── memory.py          # Agent long-term memory
│   ├── code_intel.py      # Symbol extraction, dependency graphs
│   ├── integrations.py    # GitHub/Google API wrappers
│   ├── plugins.py         # Plugin auto-loader
│   ├── advanced.py        # Permissions, hooks, background tasks
│   └── agents/
│       ├── base.py        # BaseAgent with tool loops + context compression
│       ├── specialists.py # 7 specialist agent definitions
│       ├── orchestrator.py# Parallel dispatch + synthesis
│       └── scheduler.py   # BitNet parallel task scheduler
├── templates/
│   └── index.html         # WebUI (single file, 2K+ lines)
├── android/               # Android app (Kotlin + Jetpack Compose)
├── desktop/               # Linux desktop app (Tauri + Rust)
├── smarthub/              # OrangePi RV2 Smart Hub (touch kiosk UI)
├── vscode-extension/      # VS Code extension scaffold
├── tests/                 # 396 tests (all passing)
├── docker-compose.yml     # One-command deployment
├── Dockerfile             # Container image
├── omniagent.service      # systemd auto-start
├── setup-gpu-worker-wsl.ps1  # Windows WSL2 setup script
├── mcp_server.py          # MCP stdio server (for Claude Desktop/Code)
├── CHANGELOG.md           # Full version history (v7.0 → v8.5)
└── .gitignore             # Comprehensive exclusions
```

## API Documentation

Interactive Swagger UI available at `http://localhost:8000/docs` when the server is running.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_NUM_CTX` | `32768` | Context window size for Ollama models |
| `BITNET_PORT` | `8081` | BitNet llama-server port |
| `WORKER_SECRET` | _(empty)_ | Shared secret for GPU worker E2E encryption |
| `WORKER_URL` | _(empty)_ | Manual GPU worker URL (for WSL2) |
| `GITHUB_CLIENT_ID` | _(empty)_ | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | _(empty)_ | GitHub OAuth client secret |
| `GOOGLE_CLIENT_ID` | _(empty)_ | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | _(empty)_ | Google OAuth client secret |
| `SESSION_TTL_HOURS` | `72` | Session expiry (hours) |
| `MAX_UPLOAD_DIR_MB` | `500` | Upload directory size limit |
| `DISCORD_WEBHOOK_URL` | _(empty)_ | Discord notification webhook |
| `SLACK_WEBHOOK_URL` | _(empty)_ | Slack notification webhook |
| `DEV` | _(empty)_ | Set to `1` for hot reload |

## License

Private project. All rights reserved.
