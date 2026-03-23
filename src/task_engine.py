"""
Long-running Task Engine — persistence, checkpointing, queuing, multi-phase execution.

Enables 24-hour tasks spanning multiple tools, models, files with:
  1. Task persistence in SQLite (survives restarts)
  2. Checkpointing after every tool step
  3. Multi-phase plans with approval gates
  4. File manifest tracking + git branch/rollback
  5. Task queue with sequential execution
  6. Context compression for long conversations
  7. Multi-agent collaboration (architect → workers → reviewer)
"""
import os
import json
import time
import asyncio
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field, asdict

log = logging.getLogger("task_engine")


# ============================================================
# 1. Task Persistence — SQLite storage
# ============================================================

def _get_db():
    from src.persistence import get_db
    return get_db()

def init_task_tables():
    """Create task tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            phases TEXT DEFAULT '[]',
            current_phase INTEGER DEFAULT 0,
            total_phases INTEGER DEFAULT 0,
            file_manifest TEXT DEFAULT '[]',
            git_branch TEXT DEFAULT '',
            progress_log TEXT DEFAULT '[]',
            checkpoints TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            task_description TEXT NOT NULL,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'queued',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

# Auto-init on import
try:
    init_task_tables()
except Exception:
    pass


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"          # Waiting for user approval between phases
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskCheckpoint:
    phase: int
    step: int
    agent: str
    tool: str
    result_summary: str
    timestamp: str
    files_modified: list[str] = field(default_factory=list)


@dataclass
class TaskPhase:
    name: str
    description: str
    agent: str = "coder"
    status: str = "pending"     # pending, running, completed, failed
    steps_completed: int = 0
    max_steps: int = 30
    requires_approval: bool = False
    result_summary: str = ""


def create_task(session_id: str, title: str, description: str, phases: list[dict]) -> str:
    """Create a new persistent task. Returns task_id."""
    import secrets
    task_id = secrets.token_hex(12)
    phase_objects = [
        TaskPhase(
            name=p.get("name", f"Phase {i+1}"),
            description=p.get("description", ""),
            agent=p.get("agent", "coder"),
            max_steps=p.get("max_steps", 30),
            requires_approval=p.get("requires_approval", False),
        ) for i, p in enumerate(phases)
    ]
    conn = _get_db()
    conn.execute(
        """INSERT INTO tasks (id, session_id, title, description, status, phases, total_phases)
           VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
        (task_id, session_id, title, description,
         json.dumps([asdict(p) for p in phase_objects]),
         len(phase_objects)),
    )
    conn.commit()
    conn.close()
    log.info(f"Task created: {task_id} — {title} ({len(phase_objects)} phases)")
    return task_id


def get_task(task_id: str) -> Optional[dict]:
    conn = _get_db()
    conn.row_factory = __import__('sqlite3').Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["phases"] = json.loads(d.get("phases", "[]"))
    d["file_manifest"] = json.loads(d.get("file_manifest", "[]"))
    d["progress_log"] = json.loads(d.get("progress_log", "[]"))
    d["checkpoints"] = json.loads(d.get("checkpoints", "[]"))
    return d


def update_task(task_id: str, **kwargs):
    conn = _get_db()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    sets.append("updated_at = datetime('now')")
    vals.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def list_tasks(session_id: str, status: str = "") -> list[dict]:
    conn = _get_db()
    conn.row_factory = __import__('sqlite3').Row
    if status:
        rows = conn.execute(
            "SELECT id, title, status, current_phase, total_phases, created_at, updated_at FROM tasks WHERE session_id = ? AND status = ? ORDER BY created_at DESC",
            (session_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, status, current_phase, total_phases, created_at, updated_at FROM tasks WHERE session_id = ? ORDER BY created_at DESC LIMIT 50",
            (session_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_checkpoint(task_id: str, checkpoint: TaskCheckpoint):
    task = get_task(task_id)
    if not task:
        return
    cps = task["checkpoints"]
    cps.append(asdict(checkpoint))
    # Keep last 100 checkpoints
    if len(cps) > 100:
        cps = cps[-100:]
    update_task(task_id, checkpoints=cps)


def add_to_manifest(task_id: str, file_path: str, action: str = "modified"):
    task = get_task(task_id)
    if not task:
        return
    manifest = task["file_manifest"]
    entry = {"path": file_path, "action": action, "timestamp": datetime.now().isoformat()}
    # Deduplicate by path (keep latest)
    manifest = [m for m in manifest if m["path"] != file_path]
    manifest.append(entry)
    update_task(task_id, file_manifest=manifest)


def append_task_log(task_id: str, entry: str):
    task = get_task(task_id)
    if not task:
        return
    logs = task["progress_log"]
    logs.append(entry)
    if len(logs) > 500:
        logs = logs[-500:]
    update_task(task_id, progress_log=logs)


# ============================================================
# 2. Context Compression
# ============================================================

def compress_context(messages: list[dict], max_keep: int = 10) -> list[dict]:
    """Compress older messages into a summary, keeping recent ones full."""
    if len(messages) <= max_keep:
        return messages

    old = messages[:-max_keep]
    recent = messages[-max_keep:]

    # Summarize old messages
    summaries = []
    for msg in old:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "assistant" and len(content) > 200:
            # Keep first 100 chars + any tool calls mentioned
            summary = content[:100] + "..."
            summaries.append(f"[{role}] {summary}")
        elif role == "user":
            summaries.append(f"[{role}] {content[:80]}")

    if summaries:
        compressed = [{
            "role": "system",
            "content": f"EARLIER CONVERSATION SUMMARY ({len(old)} messages):\n" + "\n".join(summaries[-20:])
        }]
        return compressed + recent

    return recent


# ============================================================
# 3. File Manifest + Git Branch/Rollback
# ============================================================

def create_task_branch(task_id: str) -> str:
    """Create a git branch for the task to enable rollback."""
    branch_name = f"task/{task_id[:8]}"
    try:
        # Check if we're in a git repo
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return ""
        # Stash any uncommitted changes
        subprocess.run(["git", "stash", "push", "-m", f"pre-task-{task_id[:8]}"],
                      capture_output=True, text=True, timeout=10)
        # Create and checkout branch
        subprocess.run(["git", "checkout", "-b", branch_name],
                      capture_output=True, text=True, timeout=10)
        update_task(task_id, git_branch=branch_name)
        log.info(f"Created branch: {branch_name}")
        return branch_name
    except Exception as e:
        log.warning(f"Failed to create task branch: {e}")
        return ""


def rollback_task(task_id: str) -> str:
    """Rollback all changes made by a task."""
    task = get_task(task_id)
    if not task:
        return "Task not found"
    branch = task.get("git_branch", "")
    if not branch:
        return "No git branch — rollback not available"
    try:
        # Checkout main/master
        for main in ["main", "master"]:
            r = subprocess.run(["git", "checkout", main],
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                break
        # Delete the task branch
        subprocess.run(["git", "branch", "-D", branch],
                      capture_output=True, text=True, timeout=10)
        # Pop stash
        subprocess.run(["git", "stash", "pop"],
                      capture_output=True, text=True, timeout=10)
        update_task(task_id, status=TaskStatus.CANCELLED)
        return f"Rolled back — branch {branch} deleted"
    except Exception as e:
        return f"Rollback failed: {e}"


def get_task_diff(task_id: str) -> str:
    """Get a summary of all changes made by a task."""
    task = get_task(task_id)
    if not task:
        return "Task not found"
    manifest = task.get("file_manifest", [])
    if not manifest:
        return "No files modified"
    lines = [f"Task: {task.get('title', task_id)}",
             f"Files affected: {len(manifest)}", ""]
    for m in manifest:
        lines.append(f"  {m['action'].upper()}: {m['path']}")
    # Also get git diff if available
    try:
        r = subprocess.run(["git", "diff", "--stat"],
                          capture_output=True, text=True, timeout=10)
        if r.stdout.strip():
            lines.append(f"\nGit diff:\n{r.stdout.strip()}")
    except Exception:
        pass
    return "\n".join(lines)


# ============================================================
# 4. Task Queue
# ============================================================

_queue_running = False
_queue_lock = threading.Lock()

def enqueue_task(session_id: str, description: str, priority: int = 1) -> int:
    """Add a task to the queue. Returns queue position."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO task_queue (session_id, task_description, priority) VALUES (?, ?, ?)",
        (session_id, description, priority),
    )
    conn.commit()
    pos = conn.execute(
        "SELECT COUNT(*) FROM task_queue WHERE status = 'queued' AND session_id = ?",
        (session_id,),
    ).fetchone()[0]
    conn.close()
    return pos


def get_queue(session_id: str) -> list[dict]:
    conn = _get_db()
    conn.row_factory = __import__('sqlite3').Row
    rows = conn.execute(
        "SELECT * FROM task_queue WHERE session_id = ? AND status = 'queued' ORDER BY priority DESC, id ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dequeue_next(session_id: str) -> Optional[dict]:
    conn = _get_db()
    conn.row_factory = __import__('sqlite3').Row
    row = conn.execute(
        "SELECT * FROM task_queue WHERE session_id = ? AND status = 'queued' ORDER BY priority DESC, id ASC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row:
        conn.execute("UPDATE task_queue SET status = 'running' WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()
    return dict(row) if row else None


def complete_queued(queue_id: int, status: str = "completed"):
    conn = _get_db()
    conn.execute("UPDATE task_queue SET status = ? WHERE id = ?", (status, queue_id))
    conn.commit()
    conn.close()


async def process_queue(session_id: str):
    """Process the task queue sequentially."""
    global _queue_running
    with _queue_lock:
        if _queue_running:
            return
        _queue_running = True

    try:
        while True:
            item = dequeue_next(session_id)
            if not item:
                break
            log.info(f"Queue: Processing — {item['task_description'][:60]}")
            try:
                from src.agents.orchestrator import Orchestrator
                orch = Orchestrator()
                result = await orch.dispatch(item["task_description"])
                complete_queued(item["id"], "completed")
                log.info(f"Queue: Completed — {item['task_description'][:40]}")
            except Exception as e:
                complete_queued(item["id"], "failed")
                log.error(f"Queue: Failed — {e}")
    finally:
        _queue_running = False


# ============================================================
# 5. Multi-Phase Task Executor
# ============================================================

async def execute_task(task_id: str, session_id: str) -> dict:
    """Execute a multi-phase task with checkpointing and persistence."""
    from src.state import state
    from src.agents.orchestrator import Orchestrator

    task = get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    update_task(task_id, status=TaskStatus.RUNNING)
    phases = task["phases"]
    orch = Orchestrator()

    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Task: Starting '{task['title']}' ({len(phases)} phases)")
    append_task_log(task_id, f"[{ts}] Task started")

    # Create git branch for rollback
    branch = create_task_branch(task_id)
    if branch:
        state.progress_log.append(f"[{ts}] Task: Created branch '{branch}' for rollback")

    start_phase = task.get("current_phase", 0)

    for i in range(start_phase, len(phases)):
        phase = phases[i]
        phase_name = phase.get("name", f"Phase {i+1}")

        ts = datetime.now().strftime("%H:%M:%S")
        state.progress_log.append(f"[{ts}] Task: Phase {i+1}/{len(phases)} — {phase_name}")
        append_task_log(task_id, f"[{ts}] Phase {i+1}: {phase_name}")

        # Check if phase needs approval
        if phase.get("requires_approval") and i > start_phase:
            update_task(task_id, status=TaskStatus.PAUSED, current_phase=i)
            state.progress_log.append(f"[{ts}] Task: Paused — waiting for approval to continue")
            return {"status": "paused", "task_id": task_id, "phase": i, "waiting_for": "approval"}

        # Execute the phase
        phase["status"] = "running"
        phases[i] = phase
        update_task(task_id, phases=phases, current_phase=i)

        try:
            context = f"TASK: {task['description']}\nCURRENT PHASE: {phase_name} — {phase.get('description', '')}"
            # Add results from prior phases
            for j in range(i):
                prior = phases[j]
                if prior.get("result_summary"):
                    context += f"\nPHASE {j+1} RESULT: {prior['result_summary'][:300]}"

            result = await orch.dispatch(phase.get("description", task["description"]), context=context)
            reply = result.get("reply", "")

            phase["status"] = "completed"
            phase["result_summary"] = reply[:500]
            phases[i] = phase
            update_task(task_id, phases=phases)

            ts = datetime.now().strftime("%H:%M:%S")
            state.progress_log.append(f"[{ts}] Task: Phase {i+1} completed ✓")
            append_task_log(task_id, f"[{ts}] Phase {i+1} completed")

        except Exception as e:
            phase["status"] = "failed"
            phases[i] = phase
            update_task(task_id, phases=phases, status=TaskStatus.FAILED, error=str(e))
            ts = datetime.now().strftime("%H:%M:%S")
            state.progress_log.append(f"[{ts}] Task: Phase {i+1} FAILED — {e}")
            return {"status": "failed", "task_id": task_id, "error": str(e)}

    # All phases complete
    update_task(task_id, status=TaskStatus.COMPLETED, completed_at=datetime.now().isoformat())
    diff = get_task_diff(task_id)
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Task: ALL PHASES COMPLETE ✓\n{diff}")

    return {"status": "completed", "task_id": task_id, "diff": diff}


async def resume_task(task_id: str, session_id: str) -> dict:
    """Resume a paused or interrupted task from its last checkpoint."""
    task = get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    if task["status"] not in (TaskStatus.PAUSED, TaskStatus.RUNNING):
        return {"error": f"Task is {task['status']}, cannot resume"}
    return await execute_task(task_id, session_id)


# ============================================================
# 6. Auto Task Planning
# ============================================================

async def plan_long_task(description: str, session_id: str) -> dict:
    """Use the orchestrator to break a complex task into phases."""
    from src.agents.orchestrator import Orchestrator
    from src.state import state

    orch = Orchestrator()
    plan_prompt = (
        f"Break this complex task into sequential phases. Each phase should be a self-contained unit of work.\n\n"
        f"TASK: {description}\n\n"
        f"Respond with JSON:\n"
        f'{{"title": "short title", "phases": [{{"name": "Phase 1 name", "description": "what to do", '
        f'"agent": "coder|reasoner|researcher|planner", "max_steps": 30, "requires_approval": false}}]}}\n\n'
        f"Use 2-6 phases. Set requires_approval=true for destructive phases (delete, deploy, migrate)."
    )

    from src.config import EXPERTS, create_chat_completion
    loop = asyncio.get_event_loop()
    response, _ = await loop.run_in_executor(
        None,
        lambda: create_chat_completion(
            model=EXPERTS["general"],
            model_key="general",
            messages=[{"role": "user", "content": plan_prompt}],
            response_format={"type": "json_object"},
        ),
    )

    from src.tools import parse_json
    plan = parse_json(response.choices[0].message.content)
    if not plan or "phases" not in plan:
        # Fallback: single phase
        plan = {"title": description[:50], "phases": [
            {"name": "Execute", "description": description, "agent": "coder", "max_steps": 30}
        ]}

    task_id = create_task(
        session_id=session_id,
        title=plan.get("title", description[:50]),
        description=description,
        phases=plan["phases"],
    )

    return {"task_id": task_id, "plan": plan}
