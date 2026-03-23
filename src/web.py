import json
import asyncio
import tempfile
import os
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from src.config import EXPERTS, BITNET_ENABLED
import src.config as config
from src.state import ChatReq, state
from src.coordinator import Coordinator
from src.supervisor import Supervisor
from src.agents.orchestrator import Orchestrator
from src.agents.specialists import SPECIALIST_REGISTRY
from src.tools import (
    ollama_list_models, ollama_pull_model, ollama_delete_model, ollama_model_info,
    export_chat_json, export_chat_markdown, export_chat_text, export_chat_csv, export_chat_html,
    TOOL_REGISTRY,
)

from contextlib import asynccontextmanager
from src.monitor import gpu_monitor

@asynccontextmanager
async def lifespan(application):
    # Start GPU monitor as background task
    task = asyncio.create_task(gpu_monitor())
    yield
    task.cancel()

app = FastAPI(
    title="OmniAgent",
    version="8.2.0",
    description="Autonomous AI Agent Framework — Local LLM orchestration with 46 tools, 7 agents, multi-phase task execution",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": "Rate limit exceeded. Slow down."}, status_code=429)

# CORS — restrict origins. Wildcard + credentials is a dangerous combination.
# Allow localhost variants for LAN access and trycloudflare for tunnel.
from fastapi.middleware.cors import CORSMiddleware
_CORS_ORIGINS = [
    "http://localhost:8000", "http://127.0.0.1:8000",
    "http://localhost:3000", "http://127.0.0.1:3000",
]
# Dynamically allow the tunnel origin if one is active
import re as _cors_re
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.trycloudflare\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=(self)"
        return response
app.add_middleware(SecurityHeadersMiddleware)

coordinator = Coordinator()
supervisor = Supervisor(coordinator)
orchestrator = Orchestrator()

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "index.html"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.get("/")
async def home():
    html = TEMPLATE_PATH.read_text()
    # Prevent browser caching stale versions
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})


# --- User Accounts ---
from src.persistence import (
    create_user, authenticate_user, get_user, create_session,
    get_session_user, update_user_tokens, update_user_settings,
    save_message, get_chat_history, clear_chat_history, list_user_sessions,
    rename_session, delete_session, share_session,
    add_collaborator, remove_collaborator, get_session_collaborators, can_access_session,
    archive_session, unarchive_session, save_session_metrics, get_session_metrics,
    get_last_session, save_global_counters, load_global_counters,
)

class AuthReq(BaseModel):
    username: str
    password: str

@app.post("/api/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, req: AuthReq):
    # Input validation
    if not req.username or len(req.username) < 3 or len(req.username) > 50:
        return JSONResponse({"error": "Username must be 3-50 characters"}, status_code=400)
    if not req.password or len(req.password) < 6:
        return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)
    if not all(c.isalnum() or c in '_-.' for c in req.username):
        return JSONResponse({"error": "Username must be alphanumeric (with _-. allowed)"}, status_code=400)
    import asyncio
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, create_user, req.username, req.password)
    if not user:
        return JSONResponse({"error": "Username already taken"}, status_code=400)
    sid = create_session(user["id"])
    return JSONResponse({"ok": True, "session_id": sid, "user_id": user["id"], "username": user["username"]})

@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, req: AuthReq):
    from src.upgrades import check_login_lockout, record_failed_login, clear_login_attempts, audit_log
    if check_login_lockout(req.username):
        return JSONResponse({"error": "Account locked — too many failed attempts. Try again in 5 minutes."}, status_code=429)
    import asyncio
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, authenticate_user, req.username, req.password)
    if not user:
        record_failed_login(req.username)
        audit_log("", "login_failed", f"username={req.username}")
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    clear_login_attempts(req.username)
    # Resume last session if one exists, otherwise create new
    sid = get_last_session(user["id"])
    if not sid:
        sid = create_session(user["id"])
    # Restore everything into the SESSION
    session = state.get_session(sid)
    state.set_active_session(sid)
    if user.get("github_token"):
        session.github_token = user["github_token"]
    if user.get("google_token"):
        session.google_token = user["google_token"]
    if user.get("system_prompt"):
        session.user_system_prompt = user["system_prompt"]
    if user.get("execution_mode"):
        session.execution_mode = user["execution_mode"]
    # Load persisted chat history into memory
    session.chat_history = get_chat_history(sid)
    # Restore metrics for this session
    metrics = get_session_metrics(sid)
    if metrics:
        session.total_tokens_in = metrics.get("tokens_in", 0)
        session.total_tokens_out = metrics.get("tokens_out", 0)
    return JSONResponse({
        "ok": True, "session_id": sid, "user_id": user["id"], "username": user["username"],
        "has_github": bool(user.get("github_token")),
        "has_google": bool(user.get("google_token")),
    })

@app.get("/api/auth/user")
async def get_current_user(session_id: str = "default"):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"authenticated": False})
    # Ensure session state is loaded into memory (for restarts/reconnects)
    sess = state.get_session(session_id)
    state.set_active_session(session_id)
    if not sess.chat_history:
        sess.chat_history = get_chat_history(session_id)
    # Restore metrics if not already loaded
    if sess.total_tokens_in == 0 and sess.total_tokens_out == 0:
        metrics = get_session_metrics(session_id)
        if metrics:
            sess.total_tokens_in = metrics.get("tokens_in", 0)
            sess.total_tokens_out = metrics.get("tokens_out", 0)
    return JSONResponse({
        "authenticated": True,
        "user_id": user["id"],
        "username": user["username"],
        "has_github": bool(user.get("github_token")),
        "has_google": bool(user.get("google_token")),
    })

@app.get("/api/auth/sessions")
async def get_user_sessions(session_id: str = "default"):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"sessions": []})
    sessions = list_user_sessions(user["id"])
    return JSONResponse({"sessions": sessions})

class NewChatReq(BaseModel):
    session_id: str  # Current session for auth
    title: str = "New Chat"

@app.post("/api/auth/sessions/new")
async def create_new_chat(req: NewChatReq):
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    new_sid = create_session(user["id"], req.title)
    return JSONResponse({"ok": True, "session_id": new_sid})

class RenameReq(BaseModel):
    session_id: str
    target_session: str
    title: str

@app.post("/api/auth/sessions/rename")
async def rename_chat(req: RenameReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    rename_session(req.target_session, req.title)
    return JSONResponse({"ok": True})

class DeleteReq(BaseModel):
    session_id: str
    target_session: str

@app.post("/api/auth/sessions/delete")
async def delete_chat(req: DeleteReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    delete_session(req.target_session)
    return JSONResponse({"ok": True})

class ArchiveReq(BaseModel):
    session_id: str
    target_session: str

@app.post("/api/auth/sessions/archive")
async def archive_chat(req: ArchiveReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    archive_session(req.target_session)
    return JSONResponse({"ok": True})

@app.post("/api/auth/sessions/unarchive")
async def unarchive_chat(req: ArchiveReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    unarchive_session(req.target_session)
    return JSONResponse({"ok": True})

@app.get("/api/auth/sessions/archived")
async def get_archived_sessions(session_id: str = "default"):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"sessions": []})
    sessions = list_user_sessions(user["id"], include_archived=True)
    archived = [s for s in sessions if s.get("is_archived") in (1, "1", True)]
    return JSONResponse({"sessions": archived})

class LoadSessionReq(BaseModel):
    session_id: str
    target_session: str

@app.post("/api/auth/sessions/load")
async def load_chat_session(req: LoadSessionReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    history = get_chat_history(req.target_session)
    session = state.get_session(req.target_session)
    session.chat_history = history
    # Fully restore all metrics for this session
    metrics = get_session_metrics(req.target_session)
    if metrics:
        session.total_tokens_in = metrics.get("tokens_in", 0)
        session.total_tokens_out = metrics.get("tokens_out", 0)
        # Restore cmd_history length approximation
        cmds = metrics.get("commands_run", 0)
        while len(session.cmd_history) < cmds:
            session.cmd_history.append("(restored)")
    return JSONResponse({
        "ok": True, "session_id": req.target_session,
        "messages": history,
        "metrics": metrics or {},
        "tasks_completed": state.tasks_completed,
        "total_llm_calls": state.total_llm_calls,
    })

# --- Collaboration ---

class CollabReq(BaseModel):
    session_id: str
    target_session: str
    username: str = ""

@app.post("/api/collab/share")
async def share_chat(req: CollabReq):
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    share_session(req.target_session)
    return JSONResponse({"ok": True, "share_id": req.target_session})

@app.post("/api/collab/invite")
async def invite_collaborator(req: CollabReq):
    user = get_session_user(req.session_id)
    if not user or not can_access_session(req.target_session, user["id"]):
        return JSONResponse({"error": "Access denied"}, status_code=403)
    if not req.username:
        return JSONResponse({"error": "Username required"}, status_code=400)
    ok = add_collaborator(req.target_session, req.username)
    if not ok:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse({"ok": True})

class SessionMetricsReq(BaseModel):
    session_id: str

@app.post("/api/auth/sessions/metrics/save")
async def save_metrics(req: SessionMetricsReq):
    """Persist current live metrics for a session."""
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    sess = state.get_session(req.session_id)
    save_session_metrics(
        req.session_id,
        tasks_completed=state.tasks_completed,
        total_llm_calls=state.total_llm_calls,
        tokens_in=sess.total_tokens_in,
        tokens_out=sess.total_tokens_out,
        commands_run=len(sess.cmd_history),
    )
    return JSONResponse({"ok": True})

@app.get("/api/auth/sessions/metrics")
async def get_metrics_for_session(session_id: str, target_session: str):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    metrics = get_session_metrics(target_session)
    return JSONResponse({"metrics": metrics or {}})

@app.get("/api/collab/members")
async def get_collab_members(session_id: str, target_session: str):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    members = get_session_collaborators(target_session)
    return JSONResponse({"members": members})


# --- Memory API ---

@app.get("/api/memory")
async def get_memories(session_id: str = "default"):
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"memories": []})
    from src.memory import recall
    memories = recall(user["id"])
    return JSONResponse({"memories": memories})

class MemoryReq(BaseModel):
    session_id: str
    category: str
    key: str
    value: str = ""

@app.post("/api/memory/add")
async def add_memory(req: MemoryReq):
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from src.memory import remember
    remember(user["id"], req.category, req.key, req.value)
    return JSONResponse({"ok": True})

@app.post("/api/memory/forget")
async def forget_memory(req: MemoryReq):
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from src.memory import forget
    forget(user["id"], req.category, req.key)
    return JSONResponse({"ok": True})


# --- Pairing / Remote Discovery ---

@app.get("/api/pairing")
async def get_pairing_info():
    """Return the current pairing code and tunnel URL (if active)."""
    try:
        from omni_agent import PAIRING_CODE, TUNNEL_URL
        return JSONResponse({
            "pairing_code": PAIRING_CODE,
            "tunnel_url": TUNNEL_URL,
            "service": "OmniAgent",
        })
    except ImportError:
        return JSONResponse({"pairing_code": None, "tunnel_url": None})


@app.get("/api/pairing/resolve/{code}")
async def resolve_pairing_code(code: str):
    """Resolve a pairing code to a tunnel URL via ntfy.sh.
    This endpoint can be called from anywhere — doesn't need LAN."""
    # Validate pairing code
    code = code.strip().lower()
    if not code.isalnum() or len(code) < 4 or len(code) > 20:
        return JSONResponse({"ok": False, "error": "Invalid pairing code format"}, status_code=400)
    import urllib.request
    import json as _json
    topic = f"omniagent-{code}"
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}/json?poll=1&since=2h",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lines = resp.read().decode().strip().split('\n')
        # Get the last message that looks like a URL
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                msg = _json.loads(line)
                message = msg.get("message", "")
                if message.startswith("https://"):
                    return JSONResponse({"ok": True, "url": message, "code": code})
            except _json.JSONDecodeError:
                continue
        return JSONResponse({"ok": False, "error": "No tunnel URL found for this code. Is the server running?"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Failed to resolve: {e}"})


# --- System Prompt Presets ---

SYSTEM_PRESETS = {
    "default": "",
    "code_reviewer": "You are a senior code reviewer. Analyze code for bugs, security issues, performance problems, and style. Be specific and suggest fixes.",
    "tutor": "You are a patient programming tutor. Explain concepts step by step. Use analogies. Ask the student questions to check understanding.",
    "writer": "You are a skilled writer. Help with articles, emails, documentation. Match the user's tone and style. Be concise.",
    "devops": "You are a DevOps engineer. Help with Docker, CI/CD, infrastructure, monitoring, deployment. Give working commands.",
    "data_analyst": "You are a data analyst. Help with data processing, SQL queries, pandas, visualization. Always show working code.",
    "security": "You are a security researcher. Analyze code and systems for vulnerabilities. Provide proof-of-concept code when relevant.",
    "concise": "Be extremely concise. One-line answers when possible. No preamble. No disclaimers.",
}

@app.get("/api/presets")
async def get_presets():
    return JSONResponse({"presets": {k: v[:80] + "..." if len(v) > 80 else v for k, v in SYSTEM_PRESETS.items()}})

class PresetReq(BaseModel):
    preset: str

@app.post("/api/presets/apply")
async def apply_preset(req: PresetReq):
    if req.preset not in SYSTEM_PRESETS:
        return JSONResponse({"error": "Unknown preset"}, status_code=400)
    state.user_system_prompt = SYSTEM_PRESETS[req.preset]
    return JSONResponse({"ok": True, "prompt": SYSTEM_PRESETS[req.preset]})


# --- Share Conversation ---

@app.get("/api/chat/share/{session_id}")
async def share_conversation(session_id: str):
    """Get a read-only view of a shared conversation."""
    from src.persistence import get_db
    conn = get_db()
    row = conn.execute("SELECT is_shared FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or row["is_shared"] not in (1, "1"):
        conn.close()
        return JSONResponse({"error": "Session not shared or not found"}, status_code=404)
    conn.close()
    messages = get_chat_history(session_id)
    return JSONResponse({"messages": messages, "session_id": session_id})


# --- Multi-Model Comparison ---

class CompareReq(BaseModel):
    message: str
    models: list[str]  # e.g. ["dolphin3:8b", "deepseek-r1:8b"]
    session_id: str = "default"

@app.post("/api/chat/compare")
async def compare_models(req: CompareReq):
    """Send the same prompt to multiple models and return all responses."""
    import asyncio as _aio
    from src.config import CLIENT
    loop = _aio.get_event_loop()

    async def query_model(model: str) -> dict:
        try:
            response = await loop.run_in_executor(
                None,
                lambda: CLIENT.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": req.message}],
                ),
            )
            return {"model": model, "reply": response.choices[0].message.content, "ok": True}
        except Exception as e:
            return {"model": model, "reply": f"Error: {e}", "ok": False}

    results = await _aio.gather(*[query_model(m) for m in req.models[:4]])  # Max 4 models
    return JSONResponse({"results": results})


# --- Conversation Templates ---

CONVERSATION_TEMPLATES = {
    "code_review": {"title": "Code Review", "message": "Review this code for bugs, security issues, and improvements:\n\n```\n{paste code here}\n```"},
    "explain_code": {"title": "Explain Code", "message": "Explain what this code does, step by step:\n\n```\n{paste code here}\n```"},
    "write_tests": {"title": "Write Tests", "message": "Write comprehensive tests for this code:\n\n```\n{paste code here}\n```"},
    "debug": {"title": "Debug", "message": "This code has a bug. Here's the error:\n\n```\n{paste error}\n```\n\nHere's the code:\n\n```\n{paste code}\n```"},
    "refactor": {"title": "Refactor", "message": "Refactor this code to be cleaner and more maintainable:\n\n```\n{paste code here}\n```"},
    "project_setup": {"title": "Project Setup", "message": "Help me set up a new {language} project with {framework}. Include directory structure, dependencies, and initial config."},
}

@app.get("/api/templates")
async def get_templates():
    return JSONResponse({"templates": CONVERSATION_TEMPLATES})


# --- Location ---

_user_location: dict = {}

import re as _re
_LOCATION_KEYWORDS = _re.compile(
    r'\b(weather|forecast|temperature|temp outside|rain|snow|humidity|wind|'
    r'near me|nearby|closest|around here|local|in my area|my area|'
    r'directions to|navigate to|how far|distance to|drive to|walk to|'
    r'restaurants?|stores?|shops?|gas station|pharmacy|hospital|'
    r'sunrise|sunset|time zone|what time is it|'
    r'air quality|pollen|uv index|'
    r'where am i|my location|my city|my town)\b',
    _re.IGNORECASE
)

def _is_location_query(message: str) -> bool:
    return bool(_LOCATION_KEYWORDS.search(message))

_VOICE_KEYWORDS = _re.compile(
    r'\b(read.{0,10}(aloud|out\s*loud|to me|this)|speak.{0,10}(this|it|that|to me)|'
    r'say.{0,10}(this|it|that|out\s*loud)|tell me.{0,10}(aloud|out\s*loud)|'
    r'use.{0,10}(voice|tts|text.to.speech|speech|audio)|'
    r'voice\s*(mode|output|response)|audio\s*(mode|output|response)|'
    r'(can you|please)\s*(speak|say|read|talk)|talk to me|speak to me)\b',
    _re.IGNORECASE
)

def _is_voice_request(message: str) -> bool:
    return bool(_VOICE_KEYWORDS.search(message))

class LocationReq(BaseModel):
    latitude: float
    longitude: float
    session_id: str = "default"

@app.post("/api/location")
async def set_location(req: LocationReq):
    """Store user's location (from browser Geolocation or Android GPS)."""
    _user_location[req.session_id] = {"lat": req.latitude, "lon": req.longitude}
    # Reverse geocode via Open-Meteo
    try:
        import urllib.request as _ur
        url = f"https://geocoding-api.open-meteo.com/v1/search?name=&count=1&latitude={req.latitude}&longitude={req.longitude}"
        # Use nominatim for reverse geocoding
        url = f"https://nominatim.openstreetmap.org/reverse?lat={req.latitude}&lon={req.longitude}&format=json&zoom=10"
        r = _ur.Request(url, headers={"User-Agent": "OmniAgent/8.0"})
        with _ur.urlopen(r, timeout=5) as resp:
            import json as _j
            data = _j.loads(resp.read().decode())
            city = data.get("address", {}).get("city") or data.get("address", {}).get("town") or data.get("address", {}).get("village") or "Unknown"
            state_name = data.get("address", {}).get("state", "")
            _user_location[req.session_id]["city"] = f"{city}, {state_name}".strip(", ")
    except Exception:
        _user_location[req.session_id]["city"] = f"{req.latitude:.2f}, {req.longitude:.2f}"
    return JSONResponse({"ok": True, "location": _user_location[req.session_id]})

@app.get("/api/location")
async def get_location(session_id: str = "default"):
    loc = _user_location.get(session_id, {})
    return JSONResponse({"location": loc})


@app.get("/api/identify")
async def identify():
    """Identification endpoint for network discovery by mobile apps."""
    return JSONResponse({
        "service": "OmniAgent",
        "version": "8.0",
        "capabilities": list(TOOL_REGISTRY.keys()),
        "agents": list(SPECIALIST_REGISTRY.keys()),
        "models": dict(EXPERTS),
    })


@app.get("/api/session/new")
async def new_session():
    """Create a new session and return its ID."""
    import uuid
    sid = str(uuid.uuid4())[:8]
    state.get_session(sid)
    return JSONResponse({"session_id": sid})


@app.get("/api/sessions")
async def list_sessions():
    return JSONResponse({"sessions": state.list_sessions()})


def _resolve_session(session_id: str | None) -> str:
    """Resolve session ID — use provided, or default."""
    sid = session_id or "default"
    state.set_active_session(sid)
    return sid


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "X-Accel-Buffering": "no",  # Disable nginx/cloudflare buffering
    "Connection": "keep-alive",
}

@app.get("/stream")
async def stream(request: Request, session_id: str = "default"):
    """SSE stream scoped to a specific session. Works over tunnels with anti-buffering."""
    sess = state.get_session(session_id)
    async def event_generator():
        # Padding to force proxy/tunnel flush (Cloudflare buffers small chunks)
        yield ": " + " " * 2048 + "\n\n"
        idx = 0
        tick = 0
        while True:
            if await request.is_disconnected():
                break
            log_entry = sess.progress_log[idx] if len(sess.progress_log) > idx else None
            if log_entry:
                idx += 1
            snapshot = sess.tracking_snapshot()
            snapshot["gpu"] = state.gpu_telemetry
            snapshot["tasks_completed"] = state.tasks_completed
            snapshot["total_llm_calls"] = state.total_llm_calls
            snapshot["log"] = log_entry
            # Include GPU worker count
            try:
                from src.gpu_client import pool
                ws = pool.get_status()
                snapshot["gpu_workers"] = ws["worker_count"]
            except Exception:
                snapshot["gpu_workers"] = 0
            yield f"data: {json.dumps(snapshot)}\n\n"
            # Adaptive polling: fast during tasks, slow when idle
            is_active = snapshot.get("task_started_at") is not None
            await asyncio.sleep(0.3 if is_active else 1.5)
            tick += 1
            if tick % 20 == 0:
                yield ": keepalive\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# --- Chat (standard) ---

MAX_MESSAGE_SIZE = 100_000  # 100KB

@app.post("/chat")
@limiter.limit("20/minute")
async def chat_api(request: Request, req: ChatReq):
    if len(req.message) > MAX_MESSAGE_SIZE:
        return JSONResponse({"error": "Message too large (max 100KB)"}, status_code=413)
    sid = _resolve_session(req.session_id)
    # Request queuing — prevent concurrent processing per session
    from src.upgrades import request_queue, audit_log
    lock = request_queue.get_lock(sid)
    if not lock.acquire(blocking=False):
        return JSONResponse({"error": "A request is already processing. Please wait."}, status_code=429)
    audit_log(sid, "chat", f"len={len(req.message)}")
    try:
        return await _process_chat(request, req, sid)
    finally:
        lock.release()

async def _process_chat(request: Request, req: ChatReq, sid: str):
    if req.tool_flags:
        for k, v in req.tool_flags.items():
            if k in state.enabled_tools:
                state.enabled_tools[k] = bool(v)
    if req.model_override is not None:
        state.model_override = req.model_override
    # Tier 3: Build memory context (without mutating session state)
    memory_context = ""
    user = get_session_user(sid)
    if user:
        # Inject pinned messages
        try:
            from src.features import get_pinned_context
            pins_ctx = get_pinned_context(sid)
            if pins_ctx:
                memory_context += pins_ctx + "\n\n"
        except Exception:
            pass
        # Inject user preferences
        try:
            from src.features import get_preference_context
            prefs_ctx = get_preference_context(user["id"])
            if prefs_ctx:
                memory_context += prefs_ctx + "\n\n"
        except Exception:
            pass
        # Learn from corrections
        try:
            from src.features import learn_from_correction
            learn_from_correction(user["id"], req.message)
        except Exception:
            pass
        try:
            from src.memory import recall_as_context
            memory_context += recall_as_context(user["id"])
        except Exception:
            pass

    # Inject location context if available — or flag that it's needed
    loc = _user_location.get(sid, {})
    location_ctx = ""
    location_needed = False
    if loc.get("city"):
        location_ctx = f"\nUSER LOCATION: {loc['city']} (lat:{loc.get('lat','?')}, lon:{loc.get('lon','?')})\n"
    elif _is_location_query(req.message):
        location_needed = True
        location_ctx = "\nLOCATION NOTE: The user's question requires their location but none is available yet. Ask the user to enable location access or share their location so you can help them.\n"

    # Detect voice requests — auto-synthesize speech from the reply
    voice_requested = _is_voice_request(req.message) and state.enabled_tools.get("voice", True)
    voice_ctx = ""
    if voice_requested:
        voice_ctx = "\nVOICE NOTE: The user wants a spoken response. Give a concise, natural-language answer suitable for speech (no markdown, no code blocks, no bullet lists). Keep it conversational.\n"

    full_context = (memory_context + location_ctx + voice_ctx).strip()
    result = await orchestrator.dispatch(req.message, context=full_context)
    if location_needed:
        result["location_needed"] = True

    # Auto-synthesize speech if voice was requested
    if voice_requested:
        try:
            from src.multimodal import synthesize_speech
            reply_text = result.get("reply", "")
            if reply_text:
                tts_result = synthesize_speech(reply_text)
                if "url" in tts_result:
                    result["audio_url"] = tts_result["url"]
        except Exception:
            pass

    # Persist to SQLite if user is logged in
    if user:
        save_message(sid, user["id"], "user", req.message)
        reply = result.get("reply", "")
        save_message(sid, user["id"], "assistant", reply)
        # Auto-title the session from the first message
        try:
            from src.persistence import auto_title_session
            auto_title_session(sid, req.message)
        except Exception:
            pass
        # Auto-save metrics per session
        sess = state.get_session(sid)
        save_session_metrics(
            sid,
            tasks_completed=state.tasks_completed,
            total_llm_calls=state.total_llm_calls,
            tokens_in=sess.total_tokens_in,
            tokens_out=sess.total_tokens_out,
            commands_run=len(sess.cmd_history),
        )
        # Tier 3: Auto-extract memories from conversation
        try:
            from src.memory import extract_memories_from_conversation
            extract_memories_from_conversation(user["id"], req.message, reply)
        except Exception:
            pass
    return result


# --- Chat (streaming) ---

@app.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(request: Request, req: ChatReq):
    """Stream the response token-by-token via SSE."""
    sid = _resolve_session(req.session_id)
    if req.tool_flags:
        for k, v in req.tool_flags.items():
            if k in state.enabled_tools:
                state.enabled_tools[k] = bool(v)
    if req.model_override is not None:
        state.model_override = req.model_override

    # Check if location is needed but missing — tell client before streaming
    loc = _user_location.get(sid, {})
    location_needed = not loc.get("city") and _is_location_query(req.message)
    voice_requested = _is_voice_request(req.message) and state.enabled_tools.get("voice", True)

    async def generate():
        if location_needed:
            yield f"data: {json.dumps({'location_needed': True})}\n\n"
        full_reply = ""
        async for token in orchestrator.dispatch_streaming(req.message):
            full_reply += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        # Auto-synthesize speech after streaming completes
        if voice_requested and full_reply.strip():
            try:
                from src.multimodal import synthesize_speech
                tts_result = synthesize_speech(full_reply)
                if "url" in tts_result:
                    yield f"data: {json.dumps({'audio_url': tts_result['url']})}\n\n"
            except Exception:
                pass
        # Persist messages to DB (same as non-streaming endpoint)
        user = get_session_user(sid)
        if user and full_reply.strip():
            save_message(sid, user["id"], "user", req.message)
            save_message(sid, user["id"], "assistant", full_reply)
            try:
                from src.persistence import auto_title_session
                auto_title_session(sid, req.message)
            except Exception:
                pass
            sess = state.get_session(sid)
            save_session_metrics(
                sid, tasks_completed=state.tasks_completed,
                total_llm_calls=state.total_llm_calls,
                tokens_in=sess.total_tokens_in, tokens_out=sess.total_tokens_out,
                commands_run=len(sess.cmd_history),
            )
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/chat/legacy")
async def chat_legacy(req: ChatReq):
    return await supervisor.run(req.message)


# --- File Upload ---

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

@app.post("/api/upload")
@limiter.limit("10/minute")
async def upload_file(request: Request, file: UploadFile = File(...)):
    # Check upload directory size limit
    from src.upgrades import check_upload_dir_size
    if not check_upload_dir_size():
        return JSONResponse({"error": "Upload storage full. Delete some files first."}, status_code=507)
    # Sanitize filename — strip path separators and dangerous chars
    import re as _re
    raw_name = os.path.basename(file.filename or "upload").replace("..", "").strip()
    safe_name = _re.sub(r'[^a-zA-Z0-9._\-]', '_', raw_name)
    if not safe_name or safe_name.startswith('.'):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return JSONResponse({"error": f"File too large (max {MAX_UPLOAD_SIZE // 1024 // 1024}MB)"}, status_code=413)
    dest = UPLOAD_DIR / safe_name
    with open(dest, "wb") as f:
        f.write(content)
    return JSONResponse({
        "ok": True,
        "path": str(dest),
        "filename": safe_name,
        "size": len(content),
    })


# --- System Prompt ---

class SystemPromptUpdate(BaseModel):
    prompt: str

@app.get("/api/system-prompt")
async def get_system_prompt():
    return JSONResponse({"prompt": state.user_system_prompt})

@app.post("/api/system-prompt")
async def set_system_prompt(req: SystemPromptUpdate):
    state.user_system_prompt = req.prompt
    return JSONResponse({"ok": True})


# --- BitNet Toggle + Parallel Scheduler ---

from src.agents.scheduler import ParallelScheduler

class BitNetToggle(BaseModel):
    enabled: bool

@app.get("/api/bitnet")
async def get_bitnet():
    # Auto-detect running BitNet if not already enabled
    if not config.BITNET_ENABLED:
        try:
            import urllib.request as _ur
            port = int(os.environ.get("BITNET_PORT", "8081"))
            with _ur.urlopen(f"http://localhost:{port}/v1/models", timeout=1):
                config.BITNET_ENABLED = True
        except Exception:
            pass
    return JSONResponse({
        "enabled": config.BITNET_ENABLED,
        "model": config.BITNET_MODEL,
        "available": ParallelScheduler.is_available(),
    })

@app.post("/api/bitnet")
async def set_bitnet(req: BitNetToggle):
    config.BITNET_ENABLED = req.enabled
    return JSONResponse({"ok": True, "enabled": config.BITNET_ENABLED})

class ParallelTasksReq(BaseModel):
    tasks: list[dict]  # [{"task": "...", "system_prompt": "...", "name": "..."}]

@app.post("/api/bitnet/parallel")
async def run_parallel_bitnet(req: ParallelTasksReq):
    """Run multiple tasks on BitNet in parallel."""
    if not config.BITNET_ENABLED:
        return JSONResponse({"error": "BitNet is not enabled"}, status_code=400)
    results = await ParallelScheduler.run_parallel_bitnet(req.tasks)
    return JSONResponse({
        "results": [
            {"name": r.agent_name, "status": r.status.value, "output": r.output, "error": r.error}
            for r in results
        ]
    })

@app.post("/api/bitnet/classify")
async def bitnet_classify(req: ChatReq):
    """Quick classification using BitNet."""
    result = await ParallelScheduler.quick_classify(req.message)
    return JSONResponse({"classification": result})

@app.post("/api/bitnet/summarize")
async def bitnet_summarize(req: ChatReq):
    """Quick summarization using BitNet."""
    result = await ParallelScheduler.quick_summarize(req.message)
    return JSONResponse({"summary": result})


# --- Advanced Reasoning (Tiers 1-5) ---

@app.get("/api/reasoning")
async def get_reasoning_config():
    from src.reasoning import LARGE_MODEL_ROUTING, LARGE_MODEL_NAME, _file_index
    return JSONResponse({
        "large_model_routing": LARGE_MODEL_ROUTING,
        "large_model": LARGE_MODEL_NAME,
        "rag_indexed_files": len(_file_index),
        "review_revise": True,  # Always active for coder agent outputs
        "code_validation": True,  # Always active for write/edit
        "reasoning_chain": True,  # Active for complex tasks
    })

class ReasoningToggle(BaseModel):
    large_model_routing: bool | None = None

@app.post("/api/reasoning")
async def set_reasoning_config(req: ReasoningToggle):
    from src.reasoning import set_large_model_routing
    if req.large_model_routing is not None:
        set_large_model_routing(req.large_model_routing)
    return JSONResponse({"ok": True})

@app.post("/api/reasoning/index")
async def index_codebase_endpoint():
    """Trigger RAG codebase indexing."""
    from src.reasoning import index_codebase
    count = index_codebase()
    return JSONResponse({"ok": True, "files_indexed": count})


# --- Execution Mode ---

class ModeUpdate(BaseModel):
    mode: str

@app.get("/api/mode")
async def get_mode():
    return JSONResponse({"mode": state.execution_mode})

@app.post("/api/mode")
async def set_mode(req: ModeUpdate):
    if req.mode not in ("execute", "teach"):
        return JSONResponse({"error": "Mode must be 'execute' or 'teach'"}, status_code=400)
    state.execution_mode = req.mode
    return JSONResponse({"ok": True, "mode": state.execution_mode})


# --- Metrics ---

@app.get("/api/metrics")
async def get_metrics(session_id: str = "default"):
    """Metrics scoped to a session, includes global counters. Used as polling fallback when SSE is blocked by tunnels."""
    sid = _resolve_session(session_id)
    sess = state.get_session(sid)
    snapshot = sess.tracking_snapshot()
    snapshot["gpu"] = state.gpu_telemetry
    snapshot["tasks_completed"] = state.tasks_completed
    snapshot["total_llm_calls"] = state.total_llm_calls
    # Latest log entry
    snapshot["log"] = sess.progress_log[-1] if sess.progress_log else None
    try:
        from src.gpu_client import pool
        snapshot["gpu_workers"] = pool.get_status()["worker_count"]
    except Exception:
        snapshot["gpu_workers"] = 0
    return JSONResponse(snapshot)


# --- Settings ---

@app.get("/api/settings")
async def get_settings(session_id: str = "default"):
    """Settings scoped to a session."""
    _resolve_session(session_id)
    return JSONResponse({
        "experts": dict(EXPERTS),
        "enabled_tools": dict(state.enabled_tools),
        "model_override": state.model_override,
        "user_system_prompt": state.user_system_prompt,
        "execution_mode": state.execution_mode,
        "bitnet_enabled": config.BITNET_ENABLED,
        "session_messages": len(state.chat_history),
        "commands_run": len(state.cmd_history),
    })


class SettingsUpdate(BaseModel):
    reasoning: str | None = None
    coding: str | None = None
    general: str | None = None
    security: str | None = None

@app.post("/api/settings")
async def update_settings(update: SettingsUpdate):
    if update.reasoning:
        EXPERTS["reasoning"] = update.reasoning
    if update.coding:
        EXPERTS["coding"] = update.coding
    if update.general:
        EXPERTS["general"] = update.general
    if update.security:
        EXPERTS["security"] = update.security
    return JSONResponse({"ok": True, "experts": dict(EXPERTS)})


@app.post("/api/clear-session")
async def clear_session():
    state.chat_history.clear()
    state.progress_log.clear()
    state.cmd_history.clear()
    state.save_session()
    return JSONResponse({"ok": True})


# --- Tool Toggles ---

class ToolToggle(BaseModel):
    tool: str
    enabled: bool

@app.post("/api/tools/toggle")
async def toggle_tool(req: ToolToggle):
    if req.tool in state.enabled_tools:
        state.enabled_tools[req.tool] = req.enabled
        return JSONResponse({"ok": True, "enabled_tools": state.enabled_tools})
    return JSONResponse({"error": f"Unknown tool: {req.tool}"}, status_code=400)

@app.get("/api/tools")
async def list_tools():
    return JSONResponse({
        "tools": {name: {"description": info["description"], "args": info["args"]} for name, info in TOOL_REGISTRY.items()},
        "enabled": state.enabled_tools,
    })


# --- Plugin Management ---

from src.plugins import list_plugins, reload_plugins as _reload_plugins

@app.get("/api/plugins")
async def api_list_plugins():
    """List all currently loaded user plugins."""
    return JSONResponse({"plugins": list_plugins()})

@app.post("/api/plugins/reload")
async def api_reload_plugins():
    """Unload all plugins and re-scan ~/.omniagent/tools/."""
    try:
        loaded = _reload_plugins()
        return JSONResponse({"ok": True, "loaded": loaded, "count": len(loaded)})
    except Exception as e:
        return JSONResponse({"error": f"Plugin reload failed: {e}"}, status_code=500)


# --- Model Override ---

class ModelOverride(BaseModel):
    model: str

@app.post("/api/model-override")
async def set_model_override(req: ModelOverride):
    # Validate model name — must be 'auto' or match pattern 'name:tag'
    model = req.model.strip()
    if model != "auto" and not all(c.isalnum() or c in ".-_:/" for c in model):
        return JSONResponse({"error": "Invalid model name"}, status_code=400)
    if len(model) > 100:
        return JSONResponse({"error": "Model name too long"}, status_code=400)
    state.model_override = model
    return JSONResponse({"ok": True, "model_override": state.model_override})


# --- Model Management ---

@app.get("/api/models")
async def list_models():
    return JSONResponse({"models": ollama_list_models()})

class ModelPull(BaseModel):
    name: str

@app.post("/api/models/pull")
async def pull_model(req: ModelPull):
    async def stream_pull():
        proc = ollama_pull_model(req.name)
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, proc.stdout.readline)
            if not line and proc.poll() is not None:
                break
            if line:
                yield f"data: {json.dumps({'line': line.strip()})}\n\n"
        rc = proc.wait()
        yield f"data: {json.dumps({'done': True, 'success': rc == 0})}\n\n"
    return StreamingResponse(stream_pull(), media_type="text/event-stream", headers=SSE_HEADERS)

class ModelDelete(BaseModel):
    name: str

@app.post("/api/models/delete")
async def delete_model(req: ModelDelete):
    return JSONResponse({"result": ollama_delete_model(req.name)})

@app.get("/api/models/{model_name:path}/info")
async def model_info(model_name: str):
    return JSONResponse(ollama_model_info(model_name))


# --- Agent Registry ---

@app.get("/api/agents")
async def list_agents():
    agents = []
    for name, cls in SPECIALIST_REGISTRY.items():
        agents.append({
            "name": name, "role": cls.role, "model_key": cls.model_key,
            "model": EXPERTS.get(cls.model_key, EXPERTS["general"]),
            "has_tools": cls.max_tool_steps > 0,
            "max_steps": cls.max_tool_steps,
        })
    return JSONResponse({"agents": agents})


# --- Export ---

@app.get("/api/export/{fmt}")
async def export_chat(fmt: str, session_id: str = ""):
    history = get_chat_history(session_id) if session_id else state.chat_history
    exporters = {
        "json": (export_chat_json, "application/json", "omni_export.json"),
        "md": (export_chat_markdown, "text/markdown", "omni_export.md"),
        "markdown": (export_chat_markdown, "text/markdown", "omni_export.md"),
        "txt": (export_chat_text, "text/plain", "omni_export.txt"),
        "text": (export_chat_text, "text/plain", "omni_export.txt"),
        "csv": (export_chat_csv, "text/csv", "omni_export.csv"),
        "html": (export_chat_html, "text/html", "omni_export.html"),
    }
    if fmt not in exporters:
        return JSONResponse({"error": f"Unknown format: {fmt}"}, status_code=400)
    fn, media, filename = exporters[fmt]
    return PlainTextResponse(fn(history), media_type=media, headers={"Content-Disposition": f"attachment; filename={filename}"})


# --- Integrations (GitHub, Google Drive, Google Keep/Tasks) ---

from src.integrations import (
    tokens as integration_tokens,
    github_user, github_repos, github_list_gists, github_create_gist,
    github_repo_contents, github_read_file, github_search_code,
    gdrive_list_files, gdrive_read_file, gdrive_upload_file,
    gtasks_list_tasklists, gtasks_list_tasks, gtasks_create_task,
    save_to_github_gist, save_to_drive, save_to_tasks,
)

class TokenUpdate(BaseModel):
    service: str  # "github" or "google"
    token: str
    session_id: str | None = None

from src.oauth import (
    is_configured as oauth_configured,
    get_authorize_url, exchange_code, refresh_google_token,
    save_oauth_config, get_oauth_status,
    CALLBACK_SUCCESS_HTML, CALLBACK_ERROR_HTML,
)

@app.get("/api/integrations")
async def get_integrations(session_id: str = ""):
    data = integration_tokens.to_dict()
    # Provide OAuth authorize URLs if configured, else fallback to manual token URLs
    data["oauth"] = {
        "github": oauth_configured("github"),
        "google": oauth_configured("google"),
    }
    data["auth_urls"] = {}
    if session_id:
        base = _get_base_url()
        if oauth_configured("github"):
            url = get_authorize_url("github", f"{base}/api/oauth/callback/github", state=session_id)
            if url:
                data["auth_urls"]["github"] = url
        else:
            data["auth_urls"]["github"] = "https://github.com/settings/tokens/new?scopes=repo,gist,read:user&description=OmniAgent"
        if oauth_configured("google"):
            url = get_authorize_url("google", f"{base}/api/oauth/callback/google", state=session_id)
            if url:
                data["auth_urls"]["google"] = url
        else:
            data["auth_urls"]["google"] = "https://developers.google.com/oauthplayground/"
    return JSONResponse(data)


# --- OAuth Setup ---

class OAuthConfigReq(BaseModel):
    service: str  # "github" or "google"
    client_id: str
    client_secret: str

@app.post("/api/oauth/config")
async def set_oauth_config(req: OAuthConfigReq):
    """Save OAuth client credentials (one-time setup per service)."""
    if req.service not in ("github", "google"):
        return JSONResponse({"error": "Service must be 'github' or 'google'"}, status_code=400)
    if not req.client_id or not req.client_secret:
        return JSONResponse({"error": "Client ID and secret required"}, status_code=400)
    save_oauth_config(req.service, req.client_id.strip(), req.client_secret.strip())
    return JSONResponse({"ok": True, "configured": True})

@app.get("/api/oauth/status")
async def get_oauth_config_status():
    """Check which OAuth services are configured."""
    return JSONResponse(get_oauth_status())


def _get_base_url() -> str:
    """Get the server's externally-reachable base URL for OAuth callbacks."""
    # Prefer tunnel URL if available
    try:
        from omni_agent import TUNNEL_URL
        if TUNNEL_URL:
            return TUNNEL_URL.rstrip("/")
    except Exception:
        pass
    return "http://localhost:8000"


# --- OAuth Callback Endpoints ---

@app.get("/api/oauth/callback/github")
async def oauth_callback_github(code: str = "", state: str = "", error: str = ""):
    from starlette.responses import HTMLResponse
    if error:
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error=error))
    if not code:
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error="No authorization code received"))
    base = _get_base_url()
    result = exchange_code("github", code, f"{base}/api/oauth/callback/github")
    if not result.get("ok"):
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error=result.get("error", "Unknown error")))
    token = result["access_token"]
    # Store the token for the session
    session_id = state
    integration_tokens.github_token = token
    if session_id:
        try:
            _resolve_session(session_id)
            db_user = get_session_user(session_id)
            if db_user:
                update_user_tokens(db_user["id"], github_token=token)
        except Exception:
            pass
    return HTMLResponse(CALLBACK_SUCCESS_HTML.format(service="GitHub", service_lower="github"))


@app.get("/api/oauth/callback/google")
async def oauth_callback_google(code: str = "", state: str = "", error: str = ""):
    from starlette.responses import HTMLResponse
    if error:
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error=error))
    if not code:
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error="No authorization code received"))
    base = _get_base_url()
    result = exchange_code("google", code, f"{base}/api/oauth/callback/google")
    if not result.get("ok"):
        return HTMLResponse(CALLBACK_ERROR_HTML.format(error=result.get("error", "Unknown error")))
    token = result["access_token"]
    refresh = result.get("refresh_token", "")
    session_id = state
    integration_tokens.google_token = token
    if session_id:
        try:
            _resolve_session(session_id)
            db_user = get_session_user(session_id)
            if db_user:
                # Store both access and refresh tokens (refresh_token:access_token format)
                stored = f"{refresh}|{token}" if refresh else token
                update_user_tokens(db_user["id"], google_token=stored)
        except Exception:
            pass
    return HTMLResponse(CALLBACK_SUCCESS_HTML.format(service="Google", service_lower="google"))


@app.post("/api/oauth/refresh/google")
async def oauth_refresh_google(session_id: str = ""):
    """Refresh an expired Google access token using the stored refresh token."""
    if not session_id:
        return JSONResponse({"error": "No session"}, status_code=400)
    db_user = get_session_user(session_id)
    if not db_user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    stored = db_user.get("google_token", "")
    if "|" in stored:
        refresh_tok = stored.split("|", 1)[0]
    else:
        return JSONResponse({"error": "No refresh token available"}, status_code=400)
    result = refresh_google_token(refresh_tok)
    if result.get("ok"):
        new_token = result["access_token"]
        integration_tokens.google_token = new_token
        update_user_tokens(db_user["id"], google_token=f"{refresh_tok}|{new_token}")
        return JSONResponse({"ok": True})
    return JSONResponse({"error": result.get("error", "Refresh failed")}, status_code=400)


# --- Manual Token Connect (fallback when OAuth not configured) ---

@app.post("/api/integrations/connect")
async def connect_integration(req: TokenUpdate):
    if req.session_id:
        _resolve_session(req.session_id)
    if req.service == "github":
        integration_tokens.github_token = req.token
        try:
            gh_user = github_user()
            if req.session_id:
                db_user = get_session_user(req.session_id)
                if db_user:
                    update_user_tokens(db_user["id"], github_token=req.token)
            return JSONResponse({"ok": True, "user": gh_user.get("login", "connected")})
        except Exception as e:
            integration_tokens.github_token = ""
            return JSONResponse({"error": f"Invalid token: {e}"}, status_code=400)
    elif req.service == "google":
        integration_tokens.google_token = req.token
        if req.session_id:
            db_user = get_session_user(req.session_id)
            if db_user:
                update_user_tokens(db_user["id"], google_token=req.token)
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Unknown service"}, status_code=400)

@app.post("/api/integrations/disconnect")
async def disconnect_integration(req: TokenUpdate):
    if req.service == "github":
        integration_tokens.github_token = ""
    elif req.service == "google":
        integration_tokens.google_token = ""
    return JSONResponse({"ok": True})

# GitHub endpoints
@app.get("/api/github/repos")
async def api_github_repos():
    try: return JSONResponse({"repos": github_repos()})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/api/github/gists")
async def api_github_gists():
    try: return JSONResponse({"gists": github_list_gists()})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

class GistCreate(BaseModel):
    description: str
    filename: str = "omni_export.md"
    content: str

@app.post("/api/github/gists")
async def api_create_gist(req: GistCreate):
    try:
        result = github_create_gist(req.description, {req.filename: req.content})
        return JSONResponse({"url": result.get("html_url", ""), "id": result.get("id", "")})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

# Google Drive endpoints
@app.get("/api/drive/files")
async def api_drive_files(q: str = ""):
    try: return JSONResponse(gdrive_list_files(q))
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

class DriveUpload(BaseModel):
    name: str
    content: str
    mime_type: str = "text/plain"

@app.post("/api/drive/upload")
async def api_drive_upload(req: DriveUpload):
    try:
        result = gdrive_upload_file(req.name, req.content, req.mime_type)
        return JSONResponse({"id": result.get("id", ""), "link": result.get("webViewLink", "")})
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

# Google Tasks (Keep alternative) endpoints
@app.get("/api/tasks/lists")
async def api_task_lists():
    try: return JSONResponse(gtasks_list_tasklists())
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

class TaskCreate(BaseModel):
    title: str
    notes: str = ""

@app.post("/api/tasks/create")
async def api_create_task(req: TaskCreate):
    try:
        result = gtasks_create_task(req.title, req.notes)
        return JSONResponse(result)
    except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)

# Quick save — export chat to any connected service
class QuickSave(BaseModel):
    service: str  # "gist", "drive", "tasks"
    title: str = "OmniAgent Chat Export"

@app.post("/api/integrations/save-chat")
async def save_chat_to_service(req: QuickSave):
    content = export_chat_markdown(state.chat_history)
    if req.service == "gist":
        result = save_to_github_gist(req.title, content)
    elif req.service == "drive":
        result = save_to_drive(f"{req.title}.md", content)
    elif req.service == "tasks":
        result = save_to_tasks(req.title, content[:8000])  # Tasks has a size limit
    else:
        return JSONResponse({"error": "Unknown service"}, status_code=400)
    return JSONResponse({"result": result if isinstance(result, str) else result})


# ============================================================
# Advanced Features API
# ============================================================

from src.multimodal import (
    analyze_image, analyze_image_base64, generate_image, generate_video,
    transcribe_audio_bytes, synthesize_speech, detect_capabilities,
)
from src.advanced import (
    get_permission, set_permission, get_all_permissions,
    request_approval, resolve_approval,
    register_hook, list_hooks, run_hooks,
    create_background_task, complete_background_task, cancel_background_task,
    list_background_tasks, is_cancelled,
    create_worktree, cleanup_worktree,
    run_auto_test, load_project_context,
    branch_conversation, search_conversation, rate_message,
    list_mcp_servers, register_mcp_server,
)

# --- Multimodal Capabilities ---

# --- Long-Running Tasks ---

class TaskCreateReq(BaseModel):
    description: str
    session_id: str = ""

class TaskApproveReq(BaseModel):
    task_id: str
    session_id: str = ""

class QueueReq(BaseModel):
    description: str
    priority: int = 1
    session_id: str = ""

@app.post("/api/tasks/plan")
async def api_plan_task(req: TaskCreateReq):
    """Plan a complex task into phases."""
    from src.task_engine import plan_long_task
    sid = req.session_id or "default"
    result = await plan_long_task(req.description, sid)
    return JSONResponse(result)

@app.post("/api/tasks/execute")
async def api_execute_task(req: TaskApproveReq):
    """Execute or resume a planned task."""
    from src.task_engine import execute_task
    result = await execute_task(req.task_id, req.session_id or "default")
    return JSONResponse(result)

@app.post("/api/tasks/resume")
async def api_resume_task(req: TaskApproveReq):
    """Resume a paused task (approve and continue)."""
    from src.task_engine import resume_task
    result = await resume_task(req.task_id, req.session_id or "default")
    return JSONResponse(result)

@app.get("/api/tasks/list")
async def api_list_tasks(session_id: str = "default", status: str = ""):
    """List all tasks for a session."""
    from src.task_engine import list_tasks
    return JSONResponse({"tasks": list_tasks(session_id, status)})

@app.get("/api/tasks/detail/{task_id}")
async def api_task_detail(task_id: str):
    """Get full task details including phases, checkpoints, manifest."""
    from src.task_engine import get_task
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(task)

@app.post("/api/tasks/rollback")
async def api_rollback_task(req: TaskApproveReq):
    """Rollback all changes made by a task."""
    from src.task_engine import rollback_task
    result = rollback_task(req.task_id)
    return JSONResponse({"result": result})

@app.get("/api/tasks/diff/{task_id}")
async def api_task_diff(task_id: str):
    """Get a diff summary of task changes."""
    from src.task_engine import get_task_diff
    return JSONResponse({"diff": get_task_diff(task_id)})

@app.post("/api/tasks/queue")
async def api_enqueue(req: QueueReq):
    """Add a task to the queue."""
    from src.task_engine import enqueue_task
    sid = req.session_id or "default"
    pos = enqueue_task(sid, req.description, req.priority)
    return JSONResponse({"ok": True, "position": pos})

@app.get("/api/tasks/queue")
async def api_get_queue(session_id: str = "default"):
    """Get the task queue."""
    from src.task_engine import get_queue
    return JSONResponse({"queue": get_queue(session_id)})

@app.post("/api/tasks/queue/process")
async def api_process_queue(session_id: str = "default"):
    """Start processing the task queue."""
    from src.task_engine import process_queue
    asyncio.create_task(process_queue(session_id))
    return JSONResponse({"ok": True, "message": "Queue processing started"})


# --- Conversation Search (cross-session) ---

@app.get("/api/search/global")
async def global_search(q: str = "", session_id: str = "default"):
    """Search across ALL conversations for the user."""
    from src.features import search_all_conversations
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"results": []})
    results = search_all_conversations(user["id"], q)
    return JSONResponse({"results": results, "query": q})


# --- Pinned Messages ---

class PinReq(BaseModel):
    session_id: str
    message_index: int
    content: str
    role: str = "assistant"
    note: str = ""

@app.post("/api/pins")
async def api_pin_message(req: PinReq):
    from src.features import pin_message
    pin_message(req.session_id, req.message_index, req.content, req.role, req.note)
    return JSONResponse({"ok": True})

@app.get("/api/pins")
async def api_get_pins(session_id: str = "default"):
    from src.features import get_pinned_messages
    return JSONResponse({"pins": get_pinned_messages(session_id)})

@app.delete("/api/pins/{pin_id}")
async def api_unpin(pin_id: int):
    from src.features import unpin_message
    unpin_message(pin_id)
    return JSONResponse({"ok": True})


# --- Scheduled Tasks ---

class ScheduleReq(BaseModel):
    session_id: str = "default"
    description: str
    interval: str = "daily"  # "hourly", "daily", "weekly", "30m", "6h", "2d"

@app.post("/api/schedules")
async def api_create_schedule(req: ScheduleReq):
    from src.features import create_schedule
    sid = create_schedule(req.session_id, req.description, req.interval)
    return JSONResponse({"ok": True, "schedule_id": sid})

@app.get("/api/schedules")
async def api_list_schedules(session_id: str = "default"):
    from src.features import list_schedules
    return JSONResponse({"schedules": list_schedules(session_id)})

@app.delete("/api/schedules/{schedule_id}")
async def api_delete_schedule(schedule_id: int):
    from src.features import delete_schedule
    delete_schedule(schedule_id)
    return JSONResponse({"ok": True})


# --- User Preferences ---

@app.get("/api/preferences")
async def api_get_preferences(session_id: str = "default"):
    from src.features import get_preferences
    user = get_session_user(session_id)
    if not user:
        return JSONResponse({"preferences": []})
    return JSONResponse({"preferences": get_preferences(user["id"])})

class PrefReq(BaseModel):
    session_id: str = "default"
    category: str
    key: str
    value: str

@app.post("/api/preferences")
async def api_set_preference(req: PrefReq):
    from src.features import set_preference
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    set_preference(user["id"], req.category, req.key, req.value)
    return JSONResponse({"ok": True})


# --- PDF Export ---

@app.get("/api/export/pdf")
async def export_pdf(session_id: str = ""):
    from src.features import export_chat_pdf
    history = get_chat_history(session_id) if session_id else state.chat_history
    pdf_bytes = export_chat_pdf(history, title=f"OmniAgent Chat — {session_id[:8] if session_id else 'default'}")
    from starlette.responses import Response
    return Response(content=pdf_bytes, media_type="text/html",
                   headers={"Content-Disposition": "attachment; filename=omni_chat_export.html"})


# --- Auto Model Selection ---

@app.get("/api/models/benchmark")
async def api_benchmark_models():
    """Benchmark installed models for auto-selection."""
    from src.platform import benchmark_models
    results = await benchmark_models()
    return JSONResponse({"benchmarks": results})

@app.get("/api/models/best")
async def api_best_model(role: str = "coding"):
    from src.platform import get_best_model
    model = get_best_model(role)
    return JSONResponse({"role": role, "recommended": model})


# --- Sandboxed Execution ---

class SandboxReq(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 30

@app.post("/api/sandbox/run")
async def api_sandbox_run(req: SandboxReq):
    from src.platform import run_sandboxed
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_sandboxed, req.code, req.language, req.timeout)
    return JSONResponse(result)


# --- WebSocket Collaboration ---

from fastapi import WebSocket

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    from src.platform import ws_handler
    await ws_handler(websocket, session_id)


# --- MCP Server ---

@app.get("/mcp/manifest")
async def mcp_manifest():
    from src.platform import mcp_server
    return JSONResponse(mcp_server.get_manifest())

class MCPToolReq(BaseModel):
    tool: str
    args: dict = {}

@app.post("/mcp/execute")
async def mcp_execute(req: MCPToolReq):
    from src.platform import mcp_server
    result = mcp_server.execute_tool(req.tool, req.args)
    return JSONResponse(result)


# --- Notification Config ---

class NotifyConfigReq(BaseModel):
    discord_webhook: str = ""
    slack_webhook: str = ""

@app.post("/api/notifications/config")
async def set_notification_config(req: NotifyConfigReq):
    if req.discord_webhook:
        os.environ["DISCORD_WEBHOOK_URL"] = req.discord_webhook
    if req.slack_webhook:
        os.environ["SLACK_WEBHOOK_URL"] = req.slack_webhook
    return JSONResponse({"ok": True})

@app.get("/api/notifications/test")
async def test_notifications():
    from src.platform import notify_task_complete
    notify_task_complete("test", "This is a test notification from OmniAgent")
    return JSONResponse({"ok": True})


# --- Model A/B Testing ---

class ABTestReq(BaseModel):
    prompt: str
    model_a: str
    model_b: str
    context: str = ""

@app.post("/api/models/compare")
async def api_compare_models(req: ABTestReq):
    from src.experiments import compare_models
    result = await compare_models(req.prompt, req.model_a, req.model_b, req.context)
    return JSONResponse(result)


# --- Fine-Tuning Data ---

class FeedbackReq(BaseModel):
    user_message: str
    good_response: str
    bad_response: str = ""
    correction: str = ""

@app.post("/api/finetune/collect")
async def api_collect_training(req: FeedbackReq):
    from src.experiments import collect_training_sample
    collect_training_sample(req.user_message, req.good_response, req.bad_response, req.correction)
    return JSONResponse({"ok": True})

@app.get("/api/finetune/stats")
async def api_finetune_stats():
    from src.experiments import get_training_stats
    return JSONResponse(get_training_stats())

@app.get("/api/finetune/export")
async def api_finetune_export(format: str = "alpaca"):
    from src.experiments import export_training_data
    return JSONResponse(json.loads(export_training_data(format)))


# --- Metrics Dashboard ---

@app.get("/api/dashboard")
async def api_dashboard(hours: int = 1):
    from src.experiments import get_metrics_history
    return JSONResponse({"history": get_metrics_history(hours)})


# --- Plugin Marketplace ---

@app.get("/api/plugins/marketplace")
async def api_plugin_marketplace():
    from src.experiments import fetch_plugin_registry
    return JSONResponse({"plugins": fetch_plugin_registry()})

class PluginInstallReq(BaseModel):
    url: str
    name: str

@app.post("/api/plugins/install")
async def api_install_plugin(req: PluginInstallReq):
    from src.experiments import install_plugin
    result = install_plugin(req.url, req.name)
    return JSONResponse({"result": result})


# --- Conversation Tree ---

@app.get("/api/chat/tree/{session_id}")
async def api_conversation_tree(session_id: str):
    from src.experiments import get_conversation_tree
    return JSONResponse(get_conversation_tree(session_id))


# --- Reasoning / Thinking History ---

@app.get("/api/reasoning/history")
async def get_reasoning_history(session_id: str = "default"):
    """Get the full reasoning/thinking log for a session."""
    sid = _resolve_session(session_id)
    sess = state.get_session(sid)
    return JSONResponse({
        "session_id": sid,
        "entries": sess.progress_log,
        "count": len(sess.progress_log),
    })

@app.delete("/api/reasoning/history")
async def clear_reasoning_history(session_id: str = "default"):
    """Clear the reasoning log for a session."""
    sid = _resolve_session(session_id)
    sess = state.get_session(sid)
    sess.progress_log.clear()
    return JSONResponse({"ok": True})


@app.get("/api/capabilities")
async def get_capabilities():
    return JSONResponse(detect_capabilities())


# --- Changelog ---

@app.get("/api/changelog")
async def get_changelog():
    """Serve CHANGELOG.md as JSON with raw markdown content."""
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    if changelog_path.exists():
        content = changelog_path.read_text(encoding="utf-8")
        return JSONResponse({"ok": True, "content": content, "version": "8.0"})
    return JSONResponse({"ok": False, "content": "Changelog not found.", "version": "8.0"})


# --- GPU Workers ---

@app.get("/api/workers")
async def get_workers():
    """Get status of connected GPU workers."""
    try:
        from src.gpu_client import pool
        return JSONResponse(pool.get_status())
    except Exception:
        return JSONResponse({"worker_count": 0, "workers": []})

class AddWorkerReq(BaseModel):
    url: str

@app.post("/api/workers/add")
async def add_worker(req: AddWorkerReq):
    """Manually register a GPU worker (for WSL2 or non-broadcast setups)."""
    try:
        from src.gpu_client import add_worker_manually
        ok = add_worker_manually(req.url)
        if ok:
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Could not reach worker"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

class VerifyReq2(BaseModel):
    prompt: str
    result: str
    check: str = ""

@app.post("/api/verify")
async def verify_result_api(req: VerifyReq2):
    """Send a result to a GPU worker for independent verification."""
    try:
        from src.gpu_client import pool
        result = pool.verify_result(req.prompt, req.result, req.check)
        if result:
            return JSONResponse(result)
        return JSONResponse({"error": "No verification worker available"}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Vision ---

class VisionReq(BaseModel):
    image_path: str = ""
    image_base64: str = ""
    prompt: str = "Describe this image in detail."

@app.post("/api/vision/analyze")
async def api_analyze_image(req: VisionReq):
    if req.image_base64:
        result = analyze_image_base64(req.image_base64, req.prompt)
    elif req.image_path:
        result = analyze_image(req.image_path, req.prompt)
    else:
        return JSONResponse({"error": "Provide image_path or image_base64"}, status_code=400)
    return JSONResponse({"analysis": result})


# --- Image Generation ---

class ImageGenReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20

@app.post("/api/image/generate")
async def api_generate_image(req: ImageGenReq):
    result = generate_image(req.prompt, req.negative_prompt, req.width, req.height, req.steps)
    return JSONResponse(result)


# --- Video Generation ---

class VideoGenReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    frames: int = 16
    width: int = 512
    height: int = 512

@app.post("/api/video/generate")
async def api_generate_video(req: VideoGenReq):
    result = generate_video(req.prompt, req.negative_prompt, req.frames, req.width, req.height)
    return JSONResponse(result)


# --- Voice STT ---

@app.post("/api/voice/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    fmt = (file.filename or "audio.webm").rsplit(".", 1)[-1]
    text = transcribe_audio_bytes(audio_bytes, fmt)
    return JSONResponse({"text": text})


# --- Voice TTS ---

class TTSReq(BaseModel):
    text: str
    voice: str = "en_US-lessac-medium"

@app.post("/api/voice/speak")
async def api_speak(req: TTSReq):
    result = synthesize_speech(req.text, req.voice)
    return JSONResponse(result)


# --- Permissions ---

@app.get("/api/permissions")
async def api_get_permissions(session_id: str = "default"):
    return JSONResponse({"permissions": get_all_permissions(session_id)})

class PermissionReq(BaseModel):
    session_id: str = "default"
    tool: str
    level: str  # auto, ask, deny

@app.post("/api/permissions")
async def api_set_permission(req: PermissionReq):
    if req.level not in ("auto", "ask", "deny"):
        return JSONResponse({"error": "Level must be auto, ask, or deny"}, status_code=400)
    set_permission(req.session_id, req.tool, req.level)
    return JSONResponse({"ok": True})

class ApprovalReq(BaseModel):
    approval_id: str
    approved: bool

@app.post("/api/permissions/approve")
async def api_approve(req: ApprovalReq):
    resolve_approval(req.approval_id, req.approved)
    return JSONResponse({"ok": True})

@app.get("/api/permissions/pending")
async def api_pending_approval(session_id: str = "default"):
    sess = state.get_session(session_id)
    pending = getattr(sess, 'pending_approval', None)
    return JSONResponse({"pending": pending})


# --- Background Tasks ---

@app.get("/api/tasks/background")
async def api_list_bg_tasks(session_id: str = "default"):
    return JSONResponse({"tasks": list_background_tasks(session_id)})

class CancelTaskReq(BaseModel):
    task_id: str

@app.post("/api/tasks/cancel")
async def api_cancel_task(req: CancelTaskReq):
    cancel_background_task(req.task_id)
    return JSONResponse({"ok": True})


# --- Hooks ---

@app.get("/api/hooks")
async def api_list_hooks():
    return JSONResponse({"hooks": list_hooks()})

class HookReq(BaseModel):
    event: str
    command: str
    name: str = ""

@app.post("/api/hooks/register")
async def api_register_hook(req: HookReq):
    register_hook(req.event, req.command, req.name)
    return JSONResponse({"ok": True})


# --- Auto-Test ---

@app.post("/api/test/run")
async def api_run_tests():
    result = run_auto_test()
    return JSONResponse(result)


# --- Project Context ---

@app.get("/api/project/context")
async def api_project_context():
    ctx = load_project_context()
    return JSONResponse({"context": ctx})


# --- Conversation Branching ---

class BranchReq(BaseModel):
    session_id: str
    branch_from_index: int
    new_message: str

@app.post("/api/chat/branch")
async def api_branch_chat(req: BranchReq):
    sess = state.get_session(req.session_id)
    sess.chat_history = branch_conversation(sess.chat_history, req.branch_from_index, req.new_message)
    return JSONResponse({"ok": True, "history_length": len(sess.chat_history)})


# --- Conversation Search ---

@app.get("/api/chat/search")
async def api_search_chat(session_id: str = "default", q: str = ""):
    if not q:
        return JSONResponse({"results": []})
    sess = state.get_session(session_id)
    results = search_conversation(sess.chat_history, q)
    return JSONResponse({"results": results})


# --- Message Ratings ---

class RateReq(BaseModel):
    session_id: str
    message_index: int
    rating: str  # thumbs_up, thumbs_down

@app.post("/api/chat/rate")
async def api_rate_message(req: RateReq):
    user = get_session_user(req.session_id)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    sess = state.get_session(req.session_id)
    if 0 <= req.message_index < len(sess.chat_history):
        msg = sess.chat_history[req.message_index]
        rate_message(user["id"], msg.get("content", ""), req.rating, req.session_id)
        # Collect fine-tuning data from ratings
        try:
            from src.experiments import collect_training_sample
            if req.rating == "thumbs_up" and req.message_index > 0:
                user_msg = sess.chat_history[req.message_index - 1].get("content", "")
                assistant_msg = msg.get("content", "")
                if user_msg and assistant_msg:
                    collect_training_sample(user_msg, assistant_msg)
            elif req.rating == "thumbs_down" and req.message_index > 0:
                user_msg = sess.chat_history[req.message_index - 1].get("content", "")
                assistant_msg = msg.get("content", "")
                if user_msg and assistant_msg:
                    collect_training_sample(user_msg, "", bad_response=assistant_msg)
        except Exception:
            pass
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Invalid message index"}, status_code=400)


# --- Git Worktree ---

class WorktreeReq(BaseModel):
    branch: str = ""

@app.post("/api/git/worktree/create")
async def api_create_worktree(req: WorktreeReq):
    result = create_worktree(req.branch or None)
    return JSONResponse(result)

@app.post("/api/git/worktree/cleanup")
async def api_cleanup_worktree(req: WorktreeReq):
    ok = cleanup_worktree(req.branch)
    return JSONResponse({"ok": ok})


# --- MCP Servers ---

@app.get("/api/mcp/servers")
async def api_mcp_servers():
    return JSONResponse({"servers": list_mcp_servers()})

class MCPReq(BaseModel):
    name: str
    url: str

@app.post("/api/mcp/register")
async def api_register_mcp(req: MCPReq):
    result = register_mcp_server(req.name, req.url)
    return JSONResponse(result)


# --- Upload management ---

class DeleteUploadReq(BaseModel):
    filename: str
    session_id: str = ""

@app.post("/api/uploads/delete")
async def delete_upload(req: DeleteUploadReq):
    """Delete an uploaded file. Requires valid session."""
    if req.session_id:
        user = get_session_user(req.session_id)
        if not user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import re as _re2
    if not _re2.match(r'^[a-zA-Z0-9_\-]+\.[a-z0-9]+$', req.filename):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    filepath = UPLOAD_DIR / req.filename
    # Prevent path traversal
    if not filepath.resolve().parent == UPLOAD_DIR.resolve():
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    if not filepath.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        filepath.unlink()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/uploads/list")
async def list_uploads(session_id: str = ""):
    """List all uploaded files. Requires valid session."""
    if session_id:
        user = get_session_user(session_id)
        if not user:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    files = []
    for f in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            ext = f.suffix.lower()
            ftype = "image" if ext in {".png",".jpg",".jpeg",".gif",".webp",".svg"} else \
                    "audio" if ext in {".wav",".mp3",".ogg",".flac"} else \
                    "video" if ext in {".mp4",".webm",".mov"} else "file"
            files.append({"name": f.name, "url": f"/uploads/{f.name}", "type": ftype, "size": f.stat().st_size})
    return JSONResponse({"files": files})

# --- Serve uploads as static files ---
from fastapi.staticfiles import StaticFiles
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
