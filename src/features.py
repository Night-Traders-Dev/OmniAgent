"""
Feature additions — conversation intelligence, scheduling, monitoring, collaboration.

Categories:
  1. Conversation Intelligence: cross-session search, pinned messages, PDF export
  2. Scheduled Tasks: cron-style automation
  3. Monitoring: request tracing, cost tracking
  4. Knowledge: correction memory, user preferences
"""
import os
import json
import time
import hashlib
import threading
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("features")


# ============================================================
# 1. Cross-Session Conversation Search
# ============================================================

_search_cache: dict[str, tuple] = {}  # key → (timestamp, results)
_SEARCH_CACHE_TTL = 120  # 2 minutes

def search_all_conversations(user_id: int, query: str, limit: int = 20) -> list[dict]:
    """Full-text search across ALL sessions for a user. Results cached for 2 min."""
    import time as _time
    cache_key = f"{user_id}:{query}:{limit}"
    cached = _search_cache.get(cache_key)
    if cached and _time.time() - cached[0] < _SEARCH_CACHE_TTL:
        return cached[1]

    from src.persistence import get_db, decrypt
    conn = get_db()
    try:
        # Search encrypted messages — we have to decrypt and search
        # For performance, search the last 1000 messages
        rows = conn.execute("""
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
            FROM chat_messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.user_id = ? OR s.id IN (SELECT session_id FROM session_collaborators WHERE user_id = ?)
            ORDER BY m.id DESC LIMIT 1000
        """, (user_id, user_id)).fetchall()
    finally:
        conn.close()

    # Decrypt all messages first, then use C accelerator for fast search
    decrypted = []
    row_map = []
    for row in rows:
        try:
            content = decrypt(row[3])
            decrypted.append(content)
            row_map.append(row)
        except Exception:
            continue

    # Use C extension for fast case-insensitive matching if available
    try:
        from src._accel import fuzzy_match
        match_indices = fuzzy_match(decrypted, query)
        results = []
        for idx in match_indices[:limit]:
            row = row_map[idx]
            results.append({
                "message_id": row[0],
                "session_id": row[1],
                "role": row[2],
                "content": decrypted[idx][:200],
                "created_at": row[4],
                "session_title": row[5],
            })
    except ImportError:
        # Fallback to pure Python
        query_lower = query.lower()
        results = []
        for i, content in enumerate(decrypted):
            if query_lower in content.lower():
                row = row_map[i]
                results.append({
                    "message_id": row[0],
                    "session_id": row[1],
                    "role": row[2],
                    "content": content[:200],
                    "created_at": row[4],
                    "session_title": row[5],
                })
                if len(results) >= limit:
                    break
    # Cache results
    _search_cache[cache_key] = (_time.time(), results)
    # Evict old cache entries
    if len(_search_cache) > 50:
        oldest_key = min(_search_cache, key=lambda k: _search_cache[k][0])
        _search_cache.pop(oldest_key, None)
    return results


# ============================================================
# 2. Pinned Messages
# ============================================================

def init_pins_table():
    from src.persistence import get_db
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pinned_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            role TEXT DEFAULT 'assistant',
            pinned_at TEXT DEFAULT (datetime('now')),
            note TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()

try:
    init_pins_table()
except Exception:
    pass


def pin_message(session_id: str, message_index: int, content: str, role: str = "assistant", note: str = "") -> bool:
    from src.persistence import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO pinned_messages (session_id, message_index, content, role, note) VALUES (?, ?, ?, ?, ?)",
        (session_id, message_index, content[:2000], role, note),
    )
    conn.commit()
    conn.close()
    return True


def get_pinned_messages(session_id: str) -> list[dict]:
    from src.persistence import get_db
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pinned_messages WHERE session_id = ? ORDER BY pinned_at DESC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def unpin_message(pin_id: int) -> bool:
    from src.persistence import get_db
    conn = get_db()
    conn.execute("DELETE FROM pinned_messages WHERE id = ?", (pin_id,))
    conn.commit()
    conn.close()
    return True


def get_pinned_context(session_id: str) -> str:
    """Get pinned messages as context string for injection into prompts."""
    pins = get_pinned_messages(session_id)
    if not pins:
        return ""
    lines = ["PINNED MESSAGES (user marked as important):"]
    for p in pins[:10]:  # Max 10 pins in context
        lines.append(f"  [{p['role']}]: {p['content'][:200]}")
        if p.get('note'):
            lines.append(f"  Note: {p['note']}")
    return "\n".join(lines)


# ============================================================
# 3. Scheduled Tasks / Cron
# ============================================================

def init_schedules_table():
    from src.persistence import get_db
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            description TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

try:
    init_schedules_table()
except Exception:
    pass


def create_schedule(session_id: str, description: str, cron_expr: str) -> int:
    """Create a scheduled task. cron_expr: 'daily', 'hourly', 'weekly', or 'Xm'/'Xh'/'Xd'."""
    from src.persistence import get_db
    next_run = _calc_next_run(cron_expr)
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO scheduled_tasks (session_id, description, cron_expr, next_run) VALUES (?, ?, ?, ?)",
        (session_id, description, cron_expr, next_run),
    )
    schedule_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return schedule_id


def list_schedules(session_id: str) -> list[dict]:
    from src.persistence import get_db
    conn = get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_schedule(schedule_id: int):
    from src.persistence import get_db
    conn = get_db()
    conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def toggle_schedule(schedule_id: int, enabled: bool):
    from src.persistence import get_db
    conn = get_db()
    conn.execute("UPDATE scheduled_tasks SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id))
    conn.commit()
    conn.close()


def _calc_next_run(cron_expr: str) -> str:
    now = datetime.now()
    expr = cron_expr.lower().strip()
    if expr == "hourly":
        nxt = now + timedelta(hours=1)
    elif expr == "daily":
        nxt = now + timedelta(days=1)
    elif expr == "weekly":
        nxt = now + timedelta(weeks=1)
    elif expr.endswith("m"):
        nxt = now + timedelta(minutes=int(expr[:-1]))
    elif expr.endswith("h"):
        nxt = now + timedelta(hours=int(expr[:-1]))
    elif expr.endswith("d"):
        nxt = now + timedelta(days=int(expr[:-1]))
    else:
        nxt = now + timedelta(hours=1)  # Default hourly
    return nxt.isoformat()


_scheduler_running = False

def start_scheduler():
    """Background thread that checks and runs due scheduled tasks."""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    def _loop():
        while _scheduler_running:
            try:
                _check_due_tasks()
            except Exception as e:
                log.debug(f"Scheduler error: {e}")
            time.sleep(60)  # Check every minute

    threading.Thread(target=_loop, daemon=True).start()
    log.info("Task scheduler started")


def _check_due_tasks():
    from src.persistence import get_db
    now = datetime.now().isoformat()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    due = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run <= ?",
        (now,),
    ).fetchall()
    conn.close()

    for task in due:
        try:
            log.info(f"Scheduler: Running '{task['description'][:40]}'")
            # Run via the orchestrator
            import asyncio
            from src.agents.orchestrator import Orchestrator
            orch = Orchestrator()

            # Run in a new event loop if needed
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(orch.dispatch(task["description"]))
                else:
                    loop.run_until_complete(orch.dispatch(task["description"]))
            except RuntimeError:
                asyncio.run(orch.dispatch(task["description"]))

            # Update schedule
            from src.persistence import get_db as _gdb
            conn2 = _gdb()
            next_run = _calc_next_run(task["cron_expr"])
            conn2.execute(
                "UPDATE scheduled_tasks SET last_run = ?, next_run = ?, run_count = run_count + 1 WHERE id = ?",
                (now, next_run, task["id"]),
            )
            conn2.commit()
            conn2.close()
        except Exception as e:
            log.error(f"Scheduler: Failed — {e}")


# ============================================================
# 4. User Preference Learning
# ============================================================

def init_preferences_table():
    from src.persistence import get_db
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, category, key)
        )
    """)
    conn.commit()
    conn.close()

try:
    init_preferences_table()
except Exception:
    pass


def set_preference(user_id: int, category: str, key: str, value: str, confidence: float = 0.8):
    from src.persistence import get_db
    conn = get_db()
    conn.execute("""
        INSERT INTO user_preferences (user_id, category, key, value, confidence, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id, category, key) DO UPDATE SET
            value=excluded.value, confidence=excluded.confidence, updated_at=datetime('now')
    """, (user_id, category, key, value, confidence))
    conn.commit()
    conn.close()


def get_preferences(user_id: int, category: str = "") -> list[dict]:
    from src.persistence import get_db
    conn = get_db()
    conn.row_factory = sqlite3.Row
    if category:
        rows = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ? AND category = ?",
            (user_id, category),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_preference_context(user_id: int) -> str:
    """Get user preferences as context for prompt injection."""
    prefs = get_preferences(user_id)
    if not prefs:
        return ""
    lines = ["USER PREFERENCES (learned from past interactions):"]
    for p in prefs:
        if p["confidence"] >= 0.5:
            lines.append(f"  [{p['category']}] {p['key']}: {p['value']}")
    return "\n".join(lines) if len(lines) > 1 else ""


# Auto-learn from corrections
def learn_from_correction(user_id: int, user_message: str, correction_context: str = ""):
    """Extract preferences from user corrections like 'use tabs not spaces'."""
    lower = user_message.lower()

    # Coding style — check preference direction ("use X" or "X not Y")
    if "use tabs" in lower or ("tabs" in lower and "not spaces" in lower):
        set_preference(user_id, "coding", "indentation", "tabs")
    elif "use spaces" in lower or ("spaces" in lower and "not tabs" in lower):
        set_preference(user_id, "coding", "indentation", "spaces")

    if "single quotes" in lower:
        set_preference(user_id, "coding", "quotes", "single")
    elif "double quotes" in lower:
        set_preference(user_id, "coding", "quotes", "double")

    if "snake_case" in lower or "snake case" in lower:
        set_preference(user_id, "coding", "naming", "snake_case")
    elif "camelCase" in lower or "camel case" in lower:
        set_preference(user_id, "coding", "naming", "camelCase")

    # Communication style
    if "be concise" in lower or "shorter" in lower or "brief" in lower:
        set_preference(user_id, "style", "verbosity", "concise")
    elif "more detail" in lower or "explain more" in lower:
        set_preference(user_id, "style", "verbosity", "detailed")


# ============================================================
# 5. Request Tracing / Cost Tracking
# ============================================================

_active_traces: dict[str, dict] = {}

def start_trace(session_id: str, message: str) -> str:
    """Start tracing a request. Returns trace_id."""
    import secrets
    trace_id = secrets.token_hex(8)
    _active_traces[trace_id] = {
        "session_id": session_id,
        "message": message[:100],
        "start_time": time.time(),
        "events": [],
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "tools_called": [],
        "models_used": [],
    }
    return trace_id


def trace_event(trace_id: str, event: str, tokens_in: int = 0, tokens_out: int = 0,
                tool: str = "", model: str = ""):
    if trace_id not in _active_traces:
        return
    t = _active_traces[trace_id]
    elapsed = time.time() - t["start_time"]
    t["events"].append({"time": f"{elapsed:.1f}s", "event": event})
    t["total_tokens_in"] += tokens_in
    t["total_tokens_out"] += tokens_out
    if tool and tool not in t["tools_called"]:
        t["tools_called"].append(tool)
    if model and model not in t["models_used"]:
        t["models_used"].append(model)


def end_trace(trace_id: str) -> dict:
    trace = _active_traces.pop(trace_id, None)
    if not trace:
        return {}
    trace["elapsed"] = f"{time.time() - trace['start_time']:.1f}s"
    trace["estimated_cost"] = _estimate_cost(trace["total_tokens_in"], trace["total_tokens_out"])
    _persist_trace(trace)
    return trace


def _estimate_cost(tokens_in: int, tokens_out: int) -> str:
    """Estimate compute cost (even for local models, track the equivalent)."""
    # Based on typical API pricing for reference
    cost_in = tokens_in * 0.000003  # $3/M input tokens
    cost_out = tokens_out * 0.000015  # $15/M output tokens
    total = cost_in + cost_out
    if total < 0.01:
        return f"~${total:.4f}"
    return f"~${total:.2f}"


_completed_traces: list[dict] = []

def _persist_trace(trace: dict):
    """Store completed trace in memory ring buffer (last 100)."""
    _completed_traces.append(trace)
    if len(_completed_traces) > 100:
        _completed_traces.pop(0)

def get_recent_traces(limit: int = 20) -> list[dict]:
    """Get recent completed traces."""
    return _completed_traces[-limit:]


# ============================================================
# 6. PDF Export
# ============================================================

def export_chat_pdf(messages: list[dict], title: str = "OmniAgent Chat") -> bytes:
    """Export chat as a simple HTML-based PDF (no external dependencies)."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:system-ui;max-width:800px;margin:0 auto;padding:20px;color:#333}}
h1{{color:#0969da;border-bottom:2px solid #0969da;padding-bottom:8px}}
.msg{{margin:12px 0;padding:12px;border-radius:8px}}
.user{{background:#f0f7ff;border-left:3px solid #0969da}}
.assistant{{background:#f6f8fa;border-left:3px solid #2ea043}}
.role{{font-size:11px;font-weight:bold;text-transform:uppercase;margin-bottom:4px}}
.user .role{{color:#0969da}} .assistant .role{{color:#2ea043}}
pre{{background:#1b1f23;color:#e6edf3;padding:12px;border-radius:6px;overflow-x:auto}}
code{{font-size:13px}}
.footer{{margin-top:30px;padding-top:10px;border-top:1px solid #ddd;font-size:11px;color:#888}}
</style></head><body>
<h1>{title}</h1>
<p style="color:#666;font-size:12px">Exported {datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(messages)} messages</p>
"""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "").replace("<", "&lt;").replace(">", "&gt;")
        # Basic markdown: code blocks
        import re
        content = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', content, flags=re.DOTALL)
        content = re.sub(r'`([^`]+)`', r'<code>\1</code>', content)
        content = content.replace("\n", "<br>")
        css_class = "user" if role == "user" else "assistant"
        html += f'<div class="msg {css_class}"><div class="role">{role}</div>{content}</div>\n'

    html += f'<div class="footer">Generated by OmniAgent v8.1 · {len(messages)} messages</div>'
    html += '</body></html>'
    return html.encode('utf-8')
