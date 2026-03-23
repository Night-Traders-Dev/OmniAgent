"""
Persistent storage for user accounts, sessions, and integration tokens.
Uses SQLite with Fernet (AES-128-CBC + HMAC-SHA256) encryption for sensitive data.
Passwords stored as salted SHA-256 hashes.
"""
import sqlite3
import json
import hashlib
import secrets
import base64
import os
from pathlib import Path
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = Path(__file__).parent.parent / "omni_data.db"
KEY_PATH = Path(__file__).parent.parent / ".omni_key"


def _get_encryption_key() -> bytes:
    """Get or create a persistent Fernet key for this installation."""
    if KEY_PATH.exists():
        raw = KEY_PATH.read_bytes()
        # Migrate: old keys were 32 raw bytes, Fernet keys are 44 url-safe-base64 bytes
        if len(raw) == 32:
            fernet_key = base64.urlsafe_b64encode(raw)
            KEY_PATH.write_bytes(fernet_key)
            KEY_PATH.chmod(0o600)
            return fernet_key
        return raw
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    KEY_PATH.chmod(0o600)
    return key


_ENC_KEY = _get_encryption_key()
_FERNET = Fernet(_ENC_KEY)


def encrypt(plaintext: str) -> str:
    """Encrypt a string using Fernet (AES-128-CBC + HMAC-SHA256)."""
    if not plaintext:
        return ""
    return _FERNET.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    if not ciphertext:
        return ""
    try:
        return _FERNET.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        # Data encrypted with a different key or corrupted — return safe placeholder
        return "[encrypted]"


import threading

class _DBPool:
    """Thread-local SQLite connection pool. Each thread reuses its own connection."""
    def __init__(self):
        self._local = threading.local()

    def get(self):
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

_pool = _DBPool()


class _DBConnection:
    """Wrapper that returns a pooled connection. Does NOT close on exit — reused by thread."""
    def __init__(self):
        self.conn = _pool.get()
    def __enter__(self):
        return self.conn
    def __exit__(self, *args):
        pass  # Don't close — pooled
    def __del__(self):
        pass  # Don't close — pooled
    def __getattr__(self, name):
        return getattr(self.conn, name)
    def close(self):
        pass  # No-op for backward compat — connection stays in pool

def get_db():
    """Get a pooled database connection. Thread-safe, reuses per-thread."""
    return _DBConnection()


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            system_prompt TEXT DEFAULT '',
            execution_mode TEXT DEFAULT 'execute',
            github_token TEXT DEFAULT '',
            google_token TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT DEFAULT 'New Chat',
            created_at TEXT DEFAULT (datetime('now')),
            last_active TEXT DEFAULT (datetime('now')),
            is_shared INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS session_collaborators (
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            added_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (session_id, user_id),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS global_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            settings_json TEXT DEFAULT '{}',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS session_metrics (
            session_id TEXT PRIMARY KEY,
            tasks_completed INTEGER DEFAULT 0,
            total_llm_calls INTEGER DEFAULT 0,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            commands_run INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)
    # Migrate existing tables — add columns if missing
    for col, default in [
        ("title", "'New Chat'"),
        ("is_shared", "0"),
        ("is_archived", "0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    """Hash password using bcrypt (cost factor 12). Falls back to PBKDF2 if bcrypt unavailable."""
    try:
        import bcrypt
        return "bcrypt:" + bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    except ImportError:
        # Fallback: PBKDF2-HMAC-SHA256 with 600k iterations (OWASP recommended)
        salt = secrets.token_bytes(32)
        h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
        return f"pbkdf2:{base64.b64encode(salt).decode()}:{base64.b64encode(h).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash. Supports bcrypt, PBKDF2, and legacy SHA-256."""
    import hmac as _hmac
    if stored_hash.startswith("bcrypt:"):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode(), stored_hash[7:].encode())
        except ImportError:
            return False
    elif stored_hash.startswith("pbkdf2:"):
        _, salt_b64, hash_b64 = stored_hash.split(":", 2)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
        return _hmac.compare_digest(actual, expected)
    else:
        # Legacy SHA-256 — verify then upgrade on next login
        salt, h = stored_hash.split(":", 1)
        return _hmac.compare_digest(
            hashlib.sha256(f"{salt}:{password}".encode()).hexdigest(), h
        )


# --- User Management ---

def create_user(username: str, password: str) -> dict | None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(user) if user else None
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def _decrypt_user(row) -> dict:
    """Convert a user row, decrypting sensitive fields."""
    d = dict(row)
    d["github_token"] = decrypt(d.get("github_token", ""))
    d["google_token"] = decrypt(d.get("google_token", ""))
    return d


def authenticate_user(username: str, password: str) -> dict | None:
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        conn.close()
        return None
    # Auto-upgrade legacy SHA-256 hashes to bcrypt/PBKDF2
    stored = user["password_hash"]
    if not stored.startswith("bcrypt:") and not stored.startswith("pbkdf2:"):
        new_hash = hash_password(password)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
        conn.commit()
    conn.close()
    return _decrypt_user(user)


def get_user(user_id: int) -> dict | None:
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return _decrypt_user(user) if user else None


def update_user_tokens(user_id: int, github_token: str = None, google_token: str = None):
    conn = get_db()
    if github_token is not None:
        conn.execute("UPDATE users SET github_token = ? WHERE id = ?", (encrypt(github_token), user_id))
    if google_token is not None:
        conn.execute("UPDATE users SET google_token = ? WHERE id = ?", (encrypt(google_token), user_id))
    conn.commit()
    conn.close()


def update_user_settings(user_id: int, system_prompt: str = None, execution_mode: str = None):
    conn = get_db()
    if system_prompt is not None:
        conn.execute("UPDATE users SET system_prompt = ? WHERE id = ?", (system_prompt, user_id))
    if execution_mode is not None:
        conn.execute("UPDATE users SET execution_mode = ? WHERE id = ?", (execution_mode, user_id))
    conn.commit()
    conn.close()


# --- Session Management ---

def save_global_state(key: str, value: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO global_state (key, value, updated_at) VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
    """, (key, value))
    conn.commit()
    conn.close()


def get_global_state(key: str, default: str = "0") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM global_state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def save_global_counters(tasks_completed: int, total_llm_calls: int):
    save_global_state("tasks_completed", str(tasks_completed))
    save_global_state("total_llm_calls", str(total_llm_calls))


def load_global_counters() -> tuple[int, int]:
    tasks = int(get_global_state("tasks_completed", "0"))
    llm = int(get_global_state("total_llm_calls", "0"))
    return tasks, llm


def auto_title_session(session_id: str, first_message: str):
    """Generate a short title from the first message and update the session."""
    # Take first 50 chars, trim to last word boundary
    title = first_message.strip()[:50]
    if len(first_message) > 50:
        last_space = title.rfind(' ')
        if last_space > 20:
            title = title[:last_space]
        title += "..."
    # Remove newlines and excessive whitespace
    title = ' '.join(title.split())
    if not title:
        title = "New Chat"
    conn = get_db()
    # Only update if still "New Chat" (don't overwrite manual titles)
    row = conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row and row["title"] in ("New Chat", ""):
        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
        conn.commit()
    conn.close()


def get_last_session(user_id: int) -> str | None:
    """Get the user's most recently active non-archived session ID, or None."""
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM sessions
        WHERE user_id = ? AND COALESCE(is_archived, '0') IN ('0', 0)
        ORDER BY last_active DESC LIMIT 1
    """, (user_id,)).fetchone()
    conn.close()
    return row["id"] if row else None


def create_session(user_id: int, title: str = "New Chat") -> str:
    session_id = secrets.token_hex(16)
    conn = get_db()
    conn.execute("INSERT INTO sessions (id, user_id, title) VALUES (?, ?, ?)", (session_id, user_id, title))
    conn.commit()
    conn.close()
    return session_id


def rename_session(session_id: str, title: str):
    conn = get_db()
    conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
    conn.commit()
    conn.close()


def delete_session(session_id: str):
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM session_collaborators WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def get_session_user(session_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("""
        SELECT u.* FROM users u
        JOIN sessions s ON s.user_id = u.id
        WHERE s.id = ?
    """, (session_id,)).fetchone()
    if row:
        conn.execute("UPDATE sessions SET last_active = datetime('now') WHERE id = ?", (session_id,))
        conn.commit()
    conn.close()
    return _decrypt_user(row) if row else None


def list_user_sessions(user_id: int, include_archived: bool = False) -> list[dict]:
    """List all sessions the user owns or collaborates on, with message counts and metrics."""
    conn = get_db()
    archive_filter = "" if include_archived else "AND COALESCE(s.is_archived, '0') IN ('0', 0)"
    rows = conn.execute(f"""
        SELECT s.*, COUNT(m.id) as message_count,
               (SELECT content FROM chat_messages WHERE session_id = s.id ORDER BY id DESC LIMIT 1) as last_message,
               sm.tasks_completed as m_tasks, sm.total_llm_calls as m_llm,
               sm.tokens_in as m_tokens_in, sm.tokens_out as m_tokens_out, sm.commands_run as m_cmds
        FROM sessions s
        LEFT JOIN chat_messages m ON m.session_id = s.id
        LEFT JOIN session_metrics sm ON sm.session_id = s.id
        WHERE (s.user_id = ? OR s.id IN (SELECT session_id FROM session_collaborators WHERE user_id = ?))
              {archive_filter}
        GROUP BY s.id
        ORDER BY s.last_active DESC
    """, (user_id, user_id)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        lm = d.get("last_message", "")
        d["last_message"] = decrypt(lm)[:80] if lm else ""
        # Include metrics
        d["metrics"] = {
            "tasks_completed": d.pop("m_tasks", 0) or 0,
            "total_llm_calls": d.pop("m_llm", 0) or 0,
            "tokens_in": d.pop("m_tokens_in", 0) or 0,
            "tokens_out": d.pop("m_tokens_out", 0) or 0,
            "commands_run": d.pop("m_cmds", 0) or 0,
        }
        result.append(d)
    return result


# --- Collaboration ---

def share_session(session_id: str):
    """Mark a session as shared."""
    conn = get_db()
    conn.execute("UPDATE sessions SET is_shared = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def add_collaborator(session_id: str, username: str) -> bool:
    """Add a user as collaborator to a session by username."""
    conn = get_db()
    user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return False
    try:
        conn.execute("INSERT INTO session_collaborators (session_id, user_id) VALUES (?, ?)",
                     (session_id, user["id"]))
        conn.execute("UPDATE sessions SET is_shared = 1 WHERE id = ?", (session_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already a collaborator
    conn.close()
    return True


def remove_collaborator(session_id: str, user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM session_collaborators WHERE session_id = ? AND user_id = ?",
                 (session_id, user_id))
    conn.commit()
    conn.close()


def get_session_collaborators(session_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username FROM users u
        JOIN session_collaborators sc ON sc.user_id = u.id
        WHERE sc.session_id = ?
    """, (session_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def can_access_session(session_id: str, user_id: int) -> bool:
    """Check if a user can access a session (owner or collaborator)."""
    conn = get_db()
    row = conn.execute("""
        SELECT 1 FROM sessions WHERE id = ? AND (
            user_id = ? OR id IN (SELECT session_id FROM session_collaborators WHERE user_id = ?)
        )
    """, (session_id, user_id, user_id)).fetchone()
    conn.close()
    return row is not None


# --- Chat Persistence ---

def save_message(session_id: str, user_id: int, role: str, content: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_messages (session_id, user_id, role, content) VALUES (?, ?, ?, ?)",
        (session_id, user_id, role, encrypt(content)),
    )
    conn.commit()
    conn.close()


def get_chat_history(session_id: str, limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": decrypt(r["content"])} for r in reversed(rows)]


def clear_chat_history(session_id: str):
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


# --- Archive ---

def archive_session(session_id: str):
    conn = get_db()
    conn.execute("UPDATE sessions SET is_archived = 1 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def unarchive_session(session_id: str):
    conn = get_db()
    conn.execute("UPDATE sessions SET is_archived = 0 WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# --- Per-Session Metrics ---

def save_session_metrics(session_id: str, tasks_completed: int, total_llm_calls: int,
                         tokens_in: int, tokens_out: int, commands_run: int):
    conn = get_db()
    conn.execute("""
        INSERT INTO session_metrics (session_id, tasks_completed, total_llm_calls, tokens_in, tokens_out, commands_run, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(session_id) DO UPDATE SET
            tasks_completed=excluded.tasks_completed,
            total_llm_calls=excluded.total_llm_calls,
            tokens_in=excluded.tokens_in,
            tokens_out=excluded.tokens_out,
            commands_run=excluded.commands_run,
            updated_at=datetime('now')
    """, (session_id, tasks_completed, total_llm_calls, tokens_in, tokens_out, commands_run))
    conn.commit()
    conn.close()


def get_session_metrics(session_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM session_metrics WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# Initialize on import
init_db()
