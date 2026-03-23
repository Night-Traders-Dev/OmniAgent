"""
Tier 3: Persistent Memory Across Sessions — Fact Store

Stores user preferences, project conventions, correction history, and key observations.
Loaded at session start, queried by agents for personalization.
Uses SQLite alongside the existing persistence layer.
"""
import json
from datetime import datetime
from src.persistence import get_db


def init_memory_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            access_count INTEGER DEFAULT 0,
            UNIQUE(user_id, category, key)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_user ON agent_memory(user_id);
        CREATE INDEX IF NOT EXISTS idx_memory_category ON agent_memory(user_id, category);
    """)
    conn.commit()
    conn.close()


# Memory categories
CATEGORY_PREFERENCE = "preference"      # "prefers Python over JS", "likes concise answers"
CATEGORY_CORRECTION = "correction"      # "don't use that library", "always use type hints"
CATEGORY_CONVENTION = "convention"      # "project uses tabs", "API returns JSON"
CATEGORY_FACT = "fact"                  # "user is a data scientist", "project is a Django app"


def remember(user_id: int, category: str, key: str, value: str, confidence: float = 1.0):
    """Store or update a memory."""
    conn = get_db()
    conn.execute("""
        INSERT INTO agent_memory (user_id, category, key, value, confidence, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id, category, key) DO UPDATE SET
            value=excluded.value, confidence=excluded.confidence, updated_at=datetime('now')
    """, (user_id, category, key, value, confidence))
    conn.commit()
    conn.close()


def recall(user_id: int, category: str = None, limit: int = 20) -> list[dict]:
    """Retrieve memories, optionally filtered by category."""
    conn = get_db()
    if category:
        rows = conn.execute(
            "SELECT category, key, value, confidence, updated_at FROM agent_memory WHERE user_id = ? AND category = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT category, key, value, confidence, updated_at FROM agent_memory WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    # Update access count
    for row in rows:
        conn.execute(
            "UPDATE agent_memory SET access_count = access_count + 1 WHERE user_id = ? AND category = ? AND key = ?",
            (user_id, row["category"], row["key"]),
        )
    conn.commit()
    conn.close()
    return [dict(r) for r in rows]


def recall_as_context(user_id: int) -> str:
    """Format all memories as context for LLM injection."""
    memories = recall(user_id, limit=30)
    if not memories:
        return ""
    lines = ["USER MEMORY (learned from past interactions):"]
    for m in memories:
        lines.append(f"- [{m['category']}] {m['key']}: {m['value']}")
    return "\n".join(lines)


def forget(user_id: int, category: str, key: str):
    """Remove a specific memory."""
    conn = get_db()
    conn.execute("DELETE FROM agent_memory WHERE user_id = ? AND category = ? AND key = ?",
                 (user_id, category, key))
    conn.commit()
    conn.close()


def extract_memories_from_conversation(user_id: int, user_msg: str, assistant_msg: str):
    """Auto-extract memories from conversation patterns.
    Called after each exchange to learn user preferences."""
    lower = user_msg.lower()

    # Detect corrections: "don't do X", "stop doing X", "never X"
    correction_patterns = [
        ("don't ", "correction"), ("dont ", "correction"), ("do not ", "correction"),
        ("stop ", "correction"), ("never ", "correction"), ("avoid ", "correction"),
        ("instead of ", "correction"), ("not like that", "correction"),
    ]
    for pattern, cat in correction_patterns:
        if pattern in lower:
            # Extract the instruction
            idx = lower.index(pattern)
            instruction = user_msg[idx:idx+120].strip()
            if len(instruction) > 10:
                remember(user_id, CATEGORY_CORRECTION, instruction[:60], instruction)
                break

    # Detect preferences: "I prefer X", "I like X", "always X"
    preference_patterns = [
        ("i prefer ", "preference"), ("i like ", "preference"),
        ("always use ", "preference"), ("please use ", "preference"),
        ("i want ", "preference"),
    ]
    for pattern, cat in preference_patterns:
        if pattern in lower:
            idx = lower.index(pattern)
            pref = user_msg[idx:idx+120].strip()
            if len(pref) > 10:
                remember(user_id, CATEGORY_PREFERENCE, pref[:60], pref)
                break


# Initialize on import
init_memory_db()
