# OmniAgent v8.4

**Fully local, autonomous AI agent framework** — 47 tools, 7 specialist agents, multi-phase task execution, running entirely on your hardware with no cloud API keys required.

## Platforms

| Platform | Status | Location |
|----------|--------|----------|
| **WebUI** | Production | `http://localhost:8000` |
| **Android** | Production | `android/app/build/outputs/apk/debug/app-debug.apk` |
| **Linux Desktop** | Production | `desktop/src-tauri/target/release/bundle/deb/OmniAgent_8.4.0_amd64.deb` |
| **GPU Worker** | Optional | `gpu_worker.py` (second PC) |

## Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull models
ollama pull dolphin3:8b
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
docker compose exec ollama ollama pull dolphin3:8b qwen2.5-coder:7b deepseek-r1:8b
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
│              FastAPI Server (147 endpoints)          │
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
| General/Orchestrator | `dolphin3:8b` | Task decomposition, synthesis (uncensored) |
| Coding | `qwen2.5-coder:7b` | Code generation, editing, debugging |
| Reasoning | `deepseek-r1:8b` | Chain-of-thought analysis, planning |
| Security | `dolphin3:8b` | Security research, vulnerability analysis |
| Fast | `bitnet-2b` | Dispatch planning, classification (CPU) |
| Vision | `llama3.2-vision:11b` | Image analysis |

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

### Voice
- **STT** — faster-whisper for speech-to-text
- **TTS** — piper with Amy voice model, smart text preprocessor (100+ abbreviations, symbols, code syntax)
- **Auto-trigger** — Say "speak to me" or "use voice" and the response is spoken aloud

### Collaboration
- **Multi-user sessions** — Shared chat sessions with collaborator invites
- **WebSocket presence** — Real-time typing indicators
- **OAuth2** — One-click connect for GitHub (repo, gist) and Google (Drive, Gmail, Tasks)

### Security
- **bcrypt passwords** with auto-upgrade from legacy hashes
- **Fernet encryption** (AES-128-CBC + HMAC-SHA256) for all chat messages and tokens
- **CORS restricted** to localhost + Cloudflare tunnels
- **Rate limiting** — 60/min default on all 147 endpoints
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
│   ├── web.py             # FastAPI server (147 endpoints)
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
├── vscode-extension/      # VS Code extension scaffold
├── tests/                 # Unit tests (256+ tests)
├── docker-compose.yml     # One-command deployment
├── Dockerfile             # Container image
├── omniagent.service      # systemd auto-start
├── setup-gpu-worker-wsl.ps1  # Windows WSL2 setup script
├── CHANGELOG.md           # Full version history (v7.0 → v8.4)
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
