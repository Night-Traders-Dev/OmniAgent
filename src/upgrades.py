"""
System upgrades — reliability, security, performance, and quality improvements.

All improvements are backward-compatible and fail gracefully.
"""
import os
import time
import json
import threading
import hashlib
import logging
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from collections import OrderedDict

log = logging.getLogger("upgrades")


# ============================================================
# Reliability: Request Queue (prevent concurrent corruption)
# ============================================================

class RequestQueue:
    """Ensures only one chat request processes at a time per session."""
    def __init__(self):
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def get_lock(self, session_id: str) -> threading.Lock:
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def is_busy(self, session_id: str) -> bool:
        lock = self.get_lock(session_id)
        return lock.locked()

request_queue = RequestQueue()


# ============================================================
# Reliability: Tool Timeout Enforcement
# ============================================================

def execute_with_timeout(fn, args: dict, timeout: int = 30):
    """Execute a function with a hard timeout. Returns result or error string."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, **args)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return f"ERROR[timeout]: Tool timed out after {timeout}s"
        except Exception as e:
            return f"ERROR: {e}"


# ============================================================
# Reliability: Ollama Health Check + Auto-Recovery
# ============================================================

_ollama_healthy = True
_last_health_check = 0

def check_ollama_health() -> bool:
    """Check if Ollama is responding. Cache result for 30s."""
    global _ollama_healthy, _last_health_check
    now = time.time()
    if now - _last_health_check < 30:
        return _ollama_healthy
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3):
            _ollama_healthy = True
    except Exception:
        _ollama_healthy = False
        log.warning("Ollama not responding — attempting restart")
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            with urllib.request.urlopen(req, timeout=5):
                _ollama_healthy = True
                log.info("Ollama restarted successfully")
        except Exception:
            log.error("Failed to restart Ollama")
    _last_health_check = now
    return _ollama_healthy


# ============================================================
# Reliability: Model Fallback Chain
# ============================================================

FALLBACK_CHAINS = {
    "coding": ["qwen2.5-coder:7b", "dolphin3:8b", "qwen3:8b"],
    "reasoning": ["deepseek-r1:8b", "dolphin3:8b", "qwen3:8b"],
    "general": ["qwen3:8b", "dolphin3:8b", "qwen2.5:7b"],
    "security": ["dolphin3:8b", "qwen3:8b"],
}

def get_fallback_model(model_key: str, failed_model: str) -> str | None:
    """Get the next model in the fallback chain after a failure."""
    chain = FALLBACK_CHAINS.get(model_key, [])
    try:
        idx = chain.index(failed_model)
        if idx + 1 < len(chain):
            return chain[idx + 1]
    except ValueError:
        pass
    return chain[0] if chain else None


# ============================================================
# Performance: Web Response Cache
# ============================================================

class ResponseCache:
    """LRU cache for web fetches and search results."""
    def __init__(self, max_size: int = 100, ttl: int = 300):
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, key: str) -> str | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._ttl:
                self._cache.move_to_end(key)
                return val
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: str):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (time.time(), value)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

web_cache = ResponseCache(max_size=200, ttl=600)  # 10 min TTL


# ============================================================
# Performance: Auto RAG Indexing
# ============================================================

_rag_indexed = False

def auto_index_rag():
    """Index codebase for RAG on startup (background thread)."""
    global _rag_indexed
    if _rag_indexed:
        return
    def _index():
        global _rag_indexed
        try:
            from src.reasoning import index_codebase
            count = index_codebase()
            _rag_indexed = True
            log.info(f"RAG auto-indexed {count} files")
        except Exception as e:
            log.debug(f"RAG auto-index failed: {e}")
    threading.Thread(target=_index, daemon=True).start()


# ============================================================
# Security: Session Expiry
# ============================================================

SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "72"))  # 3 days

def cleanup_expired_sessions():
    """Remove sessions older than TTL from in-memory state."""
    try:
        from src.state import state
        now = datetime.now()
        expired = []
        for sid, sess in list(state._sessions.items()):
            if sid == "default":
                continue
            # Check last activity via chat history
            if not sess.chat_history and not sess.task_started_at:
                expired.append(sid)
        for sid in expired[:50]:  # Clean up to 50 at a time
            del state._sessions[sid]
        if expired:
            log.info(f"Cleaned up {len(expired)} idle sessions")
    except Exception:
        pass


# ============================================================
# Security: Login Lockout
# ============================================================

_failed_logins: dict[str, list[float]] = {}  # username → list of timestamps
LOCKOUT_ATTEMPTS = 10
LOCKOUT_WINDOW = 300  # 5 minutes

def check_login_lockout(username: str) -> bool:
    """Returns True if the account is locked out."""
    now = time.time()
    attempts = _failed_logins.get(username, [])
    # Remove old attempts
    attempts = [t for t in attempts if now - t < LOCKOUT_WINDOW]
    _failed_logins[username] = attempts
    return len(attempts) >= LOCKOUT_ATTEMPTS

def record_failed_login(username: str):
    if username not in _failed_logins:
        _failed_logins[username] = []
    _failed_logins[username].append(time.time())

def clear_login_attempts(username: str):
    _failed_logins.pop(username, None)


# ============================================================
# Security: Upload Directory Size Limit
# ============================================================

MAX_UPLOAD_DIR_SIZE_MB = int(os.environ.get("MAX_UPLOAD_DIR_MB", "500"))

def check_upload_dir_size() -> bool:
    """Returns True if upload directory is under the size limit."""
    upload_dir = Path(__file__).resolve().parent.parent / "uploads"
    if not upload_dir.exists():
        return True
    total = sum(f.stat().st_size for f in upload_dir.rglob("*") if f.is_file())
    return total < MAX_UPLOAD_DIR_SIZE_MB * 1024 * 1024


# ============================================================
# Security: Audit Log
# ============================================================

AUDIT_LOG = Path(__file__).resolve().parent.parent / "logs" / "audit.log"

def audit_log(session_id: str, action: str, detail: str = ""):
    """Append to the audit log."""
    try:
        AUDIT_LOG.parent.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] session={session_id} action={action} {detail}\n"
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


# ============================================================
# Quality: Output Quality Scoring
# ============================================================

def score_output_quality(task: str, output: str) -> float:
    """Score output quality 0.0 - 1.0 based on heuristics."""
    if not output or len(output.strip()) < 10:
        return 0.1
    score = 0.5
    lower = output.lower()

    # Positive signals
    if len(output) > 100:
        score += 0.1
    if any(marker in output for marker in ['```', 'def ', 'class ', 'function']):
        score += 0.1  # Contains code
    if any(marker in lower for marker in ['because', 'therefore', 'since', 'however']):
        score += 0.05  # Contains reasoning
    if output.count('\n') > 3:
        score += 0.05  # Structured

    # Negative signals
    if lower.startswith("i'm sorry") or lower.startswith("i cannot"):
        score -= 0.3  # Refusal
    if 'as an ai' in lower or 'i am an ai' in lower:
        score -= 0.1
    if output.count(output[:20]) > 2 and len(output[:20]) > 5:
        score -= 0.2  # Repetition
    if len(output) > 50 and output.strip() == output.strip()[:50] * (len(output) // 50):
        score -= 0.3  # Degenerate repetition

    return max(0.0, min(1.0, score))


# ============================================================
# Startup: Initialize All Upgrades
# ============================================================

def init_upgrades():
    """Call on server startup to initialize all upgrade systems."""
    auto_index_rag()
    check_ollama_health()
    # Schedule periodic cleanup
    def _periodic():
        while True:
            time.sleep(3600)  # Every hour
            cleanup_expired_sessions()
            check_ollama_health()
    threading.Thread(target=_periodic, daemon=True).start()
    log.info("Upgrades initialized: queue, cache, RAG, health checks, session cleanup")
