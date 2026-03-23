# OmniAgent Changelog

## v8.1.0 — 2026-03-23 (Current)

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
