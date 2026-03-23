# OmniAgent Changelog

## v8.4.1 — 2026-03-23 (Current)

### NPU Full Pipeline Integration

- **Fixed NPU preprocessing** — `processedText` was assigned but never sent to server; both streaming and fallback API calls now use the NPU-processed message
- **Post-response NPU summarization** — Long server responses (>500 chars) automatically get an on-device TL;DR appended via Gemini Nano `summarize()`
- **Server-side NPU hint parsing** — `[npu:intent=X,mood=Y]` prefix stripped from messages and injected as routing context; server skips redundant classification
- **NPU fast-route in orchestrator** — When NPU pre-classifies intent (code→coder, debug→coder, question→researcher, summarize→reasoner, greeting→fast), orchestrator routes instantly without LLM planning step
- **End-to-end NPU pipeline**: Query rewrite → intent classify → sentiment → server hint → fast route → response summarize → smart replies — all on-device via Gemini Nano

---

## v8.4.0 — 2026-03-23

### Gemini Nano On-Device LLM
- Real LLM inference on the Galaxy S24 Ultra's Hexagon NPU via Google AI Core
- Replaces all heuristic functions with actual Gemini Nano prompts (intent classification, smart replies, sentiment, Q&A)
- New: `summarize()` — compress long responses on-device before display
- New: `rewriteQuery()` — clarify vague queries before sending to server
- Handles 30-40% of queries locally (general knowledge, greetings, summaries) without server round-trip
- Graceful fallback to heuristics on devices without Gemini Nano
- Uses reflection — no hard compile-time dependency, works on all Android devices

### Quality of Life (18 improvements)
- **Stop generating button** — Red "Stop" replaces "GO" during generation, aborts request instantly
- **Message timestamps** — Every bubble shows time (e.g. "2:15 PM")
- **Copy entire response** — "Copy All" button on hover in assistant messages
- **Auto-scroll toggle** — Pause auto-scroll while reading during generation
- **Settings persistence** — Model choice, tool toggles saved to localStorage across sessions
- **Server status page** — `GET /api/status` shows all subsystems (Ollama, BitNet, GPU workers, capabilities)
- **requirements.txt** — Generated from actual imports, organized by category

### Tool Reliability
- Fixed `regex_replace` — missing `Path` import caused all regex operations to fail
- Fixed `ToolErrorKind.IO` → `ToolErrorKind.EXECUTION` (IO kind didn't exist)
- **Tool dedup cache** — 22 read-only tools cached for 60s, prevents parallel agents from running identical commands

### Testing
- **88 integration tests** — All passing across tools, persistence, state, config, reasoning, tasks, features, platform, TTS, upgrades, OAuth, experiments
- **319 total tests** across all test files

### Documentation
- `docs/INDEX.md` — Documentation hub
- `docs/SETUP.md` — Installation for all platforms, Docker, systemd, troubleshooting
- `docs/USER_GUIDE.md` — Every feature explained with examples
- `docs/ARCHITECTURE.md` — System design, module map, request flow, security model, developer guide
- `docs/TOOLS.md` — All 47 tools with JSON usage examples
- `docs/API.md` — All 147 endpoints auto-generated from source
- `docs/GPU_WORKER.md` — Second PC setup, E2E encryption, WSL2

---

## v8.3.0 — 2026-03-23

### AI Intelligence
- **Streaming reasoning chain** — Complex tasks now stream phase-by-phase through the chat. RAG context injected into streaming path
- **FAISS vector search** — Upgraded from trigram matching to FAISS IndexFlatIP for fast nearest-neighbor semantic code search
- **Model A/B testing** — `POST /api/models/compare` runs same prompt through two models side-by-side with speed/quality metrics
- **Fine-tuning data collection** — Collect training samples from user feedback. Export as Alpaca or ShareGPT format for LoRA training

### Platform
- **VS Code extension** — Scaffold with Ask, Explain Selection, Fix Selection, Review File commands. Right-click context menu integration
- **Plugin marketplace** — Browse and install community plugins from a registry URL. `GET /api/plugins/marketplace`, `POST /api/plugins/install`
- **Metrics dashboard** — Per-minute GPU temp, VRAM, tasks, LLM calls recorded. `GET /api/dashboard?hours=1` for chart data
- **Conversation fork tree** — `GET /api/chat/tree/{session_id}` returns message tree structure for visualization

### Reliability
- **147 API endpoints** — up from 140
- **47 tools** — added `sandbox_run` for Docker-containerized code execution
- **FAISS index** — built automatically after RAG indexing for sub-millisecond code search

---

## v8.2.0 — 2026-03-23

### Platform Features
- **Auto model selection** — Benchmarks installed Ollama models on demand (speed, quality, latency). `GET /api/models/benchmark`, `GET /api/models/best?role=coding`
- **Sandboxed code execution** — Run untrusted code in Docker containers (no network, 256MB RAM limit, PID limit). Falls back to direct execution if Docker unavailable. New tool: `sandbox_run`
- **WebSocket collaboration** — Real-time endpoint `ws://{host}/ws/{session_id}` for multi-user live chat
- **MCP server support** — Model Context Protocol at `/mcp/manifest` and `/mcp/execute`. Exposes all 47 tools via MCP/1.0
- **Discord/Slack notifications** — Configure webhook URLs via `POST /api/notifications/config`. Auto-notifies on task completion
- **Swagger UI** — Interactive API docs at `/docs` and `/redoc` with all 140+ endpoints documented

### Conversation Intelligence
- **Cross-session search** — `GET /api/search/global?q=` searches across ALL conversations, decrypts and matches
- **Pinned messages** — Pin important messages that persist in context even after compression. Injected into every prompt
- **PDF export** — `GET /api/export/pdf` generates formatted HTML document
- **User preference learning** — Auto-detects coding style from corrections ("use tabs", "snake_case"). Persists per-user
- **Scheduled tasks** — Cron-style automation: "daily", "hourly", "weekly", "30m". Background thread checks every minute

### Performance & Reliability
- **DB connection pooling** — Thread-local SQLite pool replaces open/close per query. Eliminates WAL contention
- **Non-blocking auth** — `authenticate_user()` and `create_user()` wrapped in `run_in_executor` for async handlers
- **47 tools** — Added `sandbox_run` for safe code execution

### UI/UX
- **Dark/Light theme toggle** — ☼ button in WebUI header. Persists in localStorage
- **Image paste in chat** — Paste screenshots/images directly into the text input. Auto-uploads and prompts vision analysis
- **Smart reply chips** — Context-aware suggestion buttons on WebUI (parity with Android)
- **Conversation branching** — ⌥ button on user messages to fork the conversation

### DevOps
- **CI/CD pipeline** — GitHub Actions workflow: Python lint + pytest, Android APK build + artifact upload
- **Docker health checks** — Both Ollama and OmniAgent containers have health check endpoints
- **systemd service** — Updated with 32K context env var

---

## v8.1.0 — 2026-03-23

### Reasoning / Thinking History
- Historical reasoning log viewable on both WebUI and Android
- `GET /api/reasoning/history` endpoint returns all thinking entries for a session
- WebUI: "Reasoning / Thinking Log" button in Settings → History section
- Android: Full-screen scrollable log with color-coded entries (BitNet=blue, NPU=purple, errors=red, reviews=orange, success=green)
- Entries include BitNet dispatch, NPU classification, review-revise, reasoning chain phases

### On-Device NPU Logging
- All NPU actions now logged with `⚡ NPU:` prefix in activity log
- Intent classification, sentiment analysis, smart replies, local responses all tracked
- NPU thinking steps shown in collapsible thinking block when queries handled on-device
- Logs include: "Classifying intent on Snapdragon 8 Gen 3", "Intent: greeting", "Handling greeting on-device", "Smart replies: ..."

### Reliability & Performance (v8.0.2)
- All 46 tools now have explicit timeouts (was 14) — `generate_image: 180s`, `speak: 60s`, `deep_research: 60s`, etc.
- Global rate limiting: all 109 endpoints default to `60/minute`
- Tool execution audit log: shell, write, edit, git_commit, kill_process logged to `logs/audit.log`
- `os.popen` replaced with `subprocess.run` (shell injection fix)
- RAG index capped at 5000 files to prevent memory explosion
- Request queuing prevents concurrent chat corruption per session

### WebUI Features (v8.0.3)
- Browser notifications when tasks complete in background tabs
- Smart reply suggestion chips (context-aware, same as Android)
- Conversation branching buttons on user messages (⌥ icon)
- Remember device checkbox on login page
- Message editing (double-click user bubble)
- Drag-and-drop file upload

### Voice Improvements (v8.0.1)
- TTS text preprocessor: 100+ tech abbreviations, symbols, file paths, units, markdown stripping
- STT (faster-whisper) and TTS (piper) installed and verified working
- Voice model preference: tries high quality first, falls back to medium

### BitNet Always-On
- Auto-detected on config import (no longer requires `omni_agent.py` startup)
- Server correctly reports `enabled: true` when BitNet process is running
- 7 logging points visible in thinking dialogue with ⚡ prefix

---

## v8.0 — 2026-03-22

### OAuth2 Integration
- One-click "Connect with GitHub" / "Connect with Google" via OAuth2
- Server-side OAuth module (`src/oauth.py`) with authorization URL generation, code-for-token exchange, Google refresh token support
- Callback endpoints: `/api/oauth/callback/github`, `/api/oauth/callback/google`
- Popup/Custom Tab flow on WebUI and Android — auto-closes after authorization
- Falls back to manual token entry when OAuth client credentials aren't configured
- Google scopes: Drive, Gmail, Tasks, user info
- GitHub scopes: repo, gist, read:user

### GPU Worker System
- Standalone GPU worker server (`gpu_worker.py`) for offloading to a second PC
- Auto-discovery via UDP broadcast (port 5199) on LAN
- Manual worker registration for WSL2/non-broadcast setups (`WORKER_URL` env var)
- E2E encryption between main server and worker (Fernet/AES-128-CBC, PBKDF2 key derivation)
- Image generation offloaded to worker GPU (pipeline cached in VRAM)
- Video generation via AnimateDiff on worker
- Result verification — worker runs independent LLM check on another model
- First-time auto-installer for all dependencies (PyTorch CUDA, diffusers, FastAPI)
- WSL2 compatible (real LAN IP detection, broadcast workarounds)
- API: `GET /api/workers`, `POST /api/workers/add`, `POST /api/verify`
- Worker count shown in SSE stream, metrics bar, and settings

### On-Device AI (Galaxy S24 Ultra NPU)
- Snapdragon 8 Gen 3 Hexagon NPU detection via `Build.SOC_MODEL`
- TFLite with NNAPI delegate for NPU inference, GPU delegate for Adreno fallback
- On-device intent classification, sentiment analysis, smart reply generation
- Simple queries handled locally without server (greetings, time, device info)
- Smart reply suggestion chips above input (purple-bordered, context-aware)
- On-Device NPU toggle in Tools popup under Acceleration
- NPU status in Settings metrics

### Security Hardening
- **Password hashing upgraded**: SHA-256 → bcrypt (cost 12) with PBKDF2-SHA256 fallback (600k iterations)
- **Auto-upgrade legacy hashes**: Old SHA-256 passwords migrated to bcrypt on next login
- **Timing-safe comparison**: `hmac.compare_digest()` for all password verification
- **CORS restricted**: `allow_origins=["*"]` → regex whitelist (localhost + trycloudflare.com)
- **Security headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`
- **Android EncryptedSharedPreferences**: Session/token storage encrypted with AES-256-GCM
- **Android network security config**: Cleartext only for LAN IPs, HTTPS required for all others
- **android:allowBackup=false**: Prevents ADB backup credential extraction
- **Session ID entropy**: 8-char UUID → 32-char hex (128 bits)
- **Upload delete auth check**: Validates session before allowing file deletion
- **Upload path traversal guard**: `filepath.resolve().parent == UPLOAD_DIR.resolve()`
- **Legacy XOR decrypt removed**: No fallback to weak cipher

### Media Rendering & Context Menus
- `/uploads/` references auto-detected and rendered inline as media cards
- Images: inline `<img>` with click-to-fullscreen
- Audio: `<audio>` player with controls
- Video: `<video>` player with controls
- Files: card with icon, name, type badge, download button
- Right-click / long-press context menu on all media: Download, Share, Reference in Chat, Delete
- Android `MediaCardView` composable with `DownloadManager` integration
- Backend: `POST /api/uploads/delete`, `GET /api/uploads/list`

### Voice & TTS Auto-Trigger
- Voice keyword detection: "read aloud", "use voice", "speak to me", etc.
- Server auto-synthesizes speech from reply when voice requested
- `audio_url` returned in both streaming and non-streaming responses
- WebUI: auto-plays WAV + embeds `<audio>` player in message bubble
- Android: `MediaPlayer.prepareAsync()` for non-blocking audio playback
- Model receives `VOICE NOTE` context to give conversational (non-markdown) responses

### Location-Aware Queries
- Location keyword detection (weather, nearby, directions, etc.)
- Proactive location request before sending location-dependent messages
- WebUI: `ensureLocation()` triggers Geolocation API on keyword match
- Android: `sendLocation()` via GPS/Network/Passive provider chain
- Android runtime permission request on first ChatScreen launch
- Server fallback: if no location stored, model asks user to enable location

### Live Metrics & SSE Fix
- **SSE → Polling fallback**: Tries SSE for 6s, auto-falls back to `/api/metrics` polling (2s) when Cloudflare tunnel buffers
- Metrics bar always visible: tasks, LLM calls, messages, tokens in/out, GPU workers
- GPU temperature/VRAM in TopBar yellow chip
- Thinking dialogue from SSE `log` field during task execution
- `/api/metrics` endpoint now returns full snapshot (GPU, workers, log)
- Streaming endpoint (`/chat/stream`) now persists messages to DB + auto-titles sessions

### Presets & Templates
- 7 system presets: default, code_reviewer, tutor, writer, devops, data_analyst, security, concise
- 6 conversation templates: Code Review, Explain Code, Write Tests, Debug, Refactor, Project Setup
- Presets section in Android SettingsSheet — horizontal scrollable chips
- Templates section — tap to fill chat input
- API: `GET /api/presets`, `POST /api/presets/apply`, `GET /api/templates`

### Android Tunnel Retry
- Auto-resolves stale Cloudflare tunnel URLs via saved pairing code
- Login failure on tunnel → re-pairs via ntfy.sh → retries login with new URL
- Shows "Tunnel expired, re-pairing..." status during reconnection

### Changelog Viewer
- `GET /api/changelog` endpoint serves CHANGELOG.md
- WebUI: Changelog button in settings panel with rendered markdown popup
- Android: Changelog section in SettingsSheet with full markdown rendering

---

## v7.12 — 2026-03-21

### Feature Parity (WebUI + Android)
- Added session history drawer (left sidebar) to Android with new/switch/delete
- Added BitNet toggle chip to Android bottom bar
- Added token count metrics (Tokens In/Out) to Android settings
- Added collaboration invite to Android
- Added Clear Current Chat to Android session drawer
- Fixed `startSSE` → `startStatusStream` reference in Android ViewModel

### Session Sidebar (WebUI)
- Slidable left panel with full chat history
- New/rename/delete/switch sessions
- Last message preview and message count
- Shared session badges
- Collaboration invite panel with username input

### Collaboration
- Multi-user shared sessions — invite collaborators by username
- `session_collaborators` DB table for many-to-many user↔session
- Access control: `can_access_session()` checks ownership + collaborator
- API: `/api/collab/share`, `/api/collab/invite`, `/api/collab/members`

---

## v7.11 — 2026-03-21

### User Accounts + Persistence
- SQLite database (`omni_data.db`) for users, sessions, messages
- Encrypted storage for tokens and chat content (per-installation Fernet key)
- Login/Register/Guest auth flow on both WebUI and Android
- Chat history persists across server restarts
- Integration tokens (GitHub/Google) persist per-user

### Per-User Data Isolation
- All user-specific data moved from GlobalState to SessionState
- `enabled_tools`, `model_override`, `system_prompt`, `execution_mode` — per-session
- Integration tokens scoped to session, not global

---

## v7.10 — 2026-03-21

### Environment-Aware System Prompt
- Every LLM call includes current date/time, host info, OmniAgent self-knowledge
- Models know OS, tools, network IP
- System/tool queries route to `tool_user` for actual system inspection

### Token Count Metrics
- `total_tokens_in` and `total_tokens_out` tracked per session
- Displayed in Live Metrics on both platforms

---

## v7.9 — 2026-03-21

### Uncensored Orchestrator
- General model switched to dolphin3:8b (uncensored)
- Security agent with 75+ keywords, no refusal directives

### BitNet Integration
- BitNet b1.58-2B model (37 tok/s on CPU)
- `FastAgent` for lightweight parallel tasks
- `ParallelScheduler` for concurrent CPU+GPU execution

---

## v7.5–v7.8 — 2026-03-21

### Core Agent Features
- Streaming chat, multi-step tool loops, large file handling
- Codebase exploration (glob, grep, tree), diff editing
- Dangerous command detection, Git tools, URL fetching
- Execute/Teach mode toggle, model upgrades
- Per-session state isolation, SSE streams
- Markdown rendering, collapsible thinking blocks
- Tool toggles, model selector, export system

---

## v7.1–v7.4 — 2026-03-21

### Foundation
- Modularization from monolith to 11 focused modules
- Parallel agentic framework with 5 specialist agents
- Status pill, hamburger menu, live metrics
- Markdown + syntax highlighting, keyboard shortcuts

---

## v7.0 — 2026-03-21

### Initial Release
- FastAPI server with Ollama backend
- GPU monitoring via nvidia-smi
- Chat with session persistence
- Dark theme WebUI
- Android app (Kotlin + Jetpack Compose)
- Server discovery + manual connect
