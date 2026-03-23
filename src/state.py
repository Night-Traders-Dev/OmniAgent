import os
import json
import uuid
import threading
from pydantic import BaseModel, Field
from src.config import SESSION_FILE


class ChatReq(BaseModel):
    message: str = Field(..., max_length=100_000)  # 100KB max enforced at model level
    tool_flags: dict | None = None
    model_override: str | None = None
    session_id: str | None = None


class SessionState:
    """Per-client session state. Each user/connection gets its own fully isolated sandbox."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.chat_history: list[dict] = []
        self.progress_log: list[str] = []
        self.cmd_history: list[str] = []

        # Task tracking (per-session)
        self.task_started_at: str | None = None
        self.current_step: str = ""
        self.step_index: int = 0
        self.total_steps: int = 0
        self.active_model: str = ""
        self.active_agents: list[str] = []
        self.current_status: str = "Idle"

        # Per-user settings — NOT shared globally
        self.enabled_tools: dict[str, bool] = {
            "web_search": True,
            "file_read": True,
            "file_write": True,
            "shell": True,
            "vision": True,
            "image_gen": True,
            "voice": True,
            "git": True,
        }
        self.model_override: str = "auto"
        self.user_system_prompt: str = ""
        self.execution_mode: str = "execute"

        # Per-user integration tokens — NOT shared globally
        self.github_token: str = ""
        self.google_token: str = ""

        # Token usage tracking
        self.total_tokens_in: int = 0
        self.total_tokens_out: int = 0

    def begin_task(self, total_steps: int = 0):
        from datetime import datetime, timezone
        self.task_started_at = datetime.now(timezone.utc).isoformat()
        self.step_index = 0
        self.total_steps = total_steps
        self.current_step = "Initializing"
        self.active_agents = []

    def advance_step(self, step_name: str, model: str = "", agents: list[str] | None = None):
        self.step_index += 1
        self.current_step = step_name
        if model:
            self.active_model = model
        if agents is not None:
            self.active_agents = agents

    def finish_task(self):
        self.task_started_at = None
        self.step_index = 0
        self.total_steps = 0
        self.current_step = ""
        self.active_model = ""
        self.active_agents = []

    def get_recent_history(self, max_turns: int = 10) -> list[dict]:
        return self.chat_history[-(max_turns * 2):]

    def format_history_context(self, max_turns: int = 10) -> str:
        """Tier 1: Hierarchical summarization — recent turns full, older turns compressed."""
        recent = self.get_recent_history(max_turns)
        if not recent:
            return ""
        lines = ["CONVERSATION HISTORY:"]
        total = len(recent)
        for i, msg in enumerate(recent):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            # Recent messages (last 4) get more space
            if i >= total - 4:
                max_len = 1500
            # Mid-range messages get moderate space
            elif i >= total - 8:
                max_len = 600
            # Older messages get compressed heavily
            else:
                max_len = 200
            if len(content) > max_len:
                content = content[:max_len] + "..."
            lines.append(f"[{role}]: {content}")
        return "\n".join(lines)

    def estimate_context_usage(self) -> dict:
        """Estimate current context window usage."""
        total_chars = sum(len(m.get("content", "")) for m in self.chat_history)
        estimated_tokens = total_chars // 4  # ~4 chars per token
        context_limit = 8192  # Typical for 8B models
        return {
            "estimated_tokens": estimated_tokens,
            "context_limit": context_limit,
            "usage_pct": min(100, int(estimated_tokens / context_limit * 100)),
            "messages": len(self.chat_history),
        }

    def tracking_snapshot(self) -> dict:
        ctx = self.estimate_context_usage()
        return {
            "session_id": self.session_id,
            "status": self.current_status,
            "task_started_at": self.task_started_at,
            "current_step": self.current_step,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "active_model": self.active_model,
            "active_agents": self.active_agents,
            "session_messages": len(self.chat_history),
            "commands_run": len(self.cmd_history),
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "context_usage_pct": ctx["usage_pct"],
            "estimated_tokens": ctx["estimated_tokens"],
        }

    def save(self, path: str):
        data = {"chat_history": self.chat_history[-50:]}
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str):
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.chat_history = data
                elif isinstance(data, dict):
                    self.chat_history = data.get("chat_history", [])
            except (json.JSONDecodeError, IOError):
                pass


class GlobalState:
    """Global state manager. Only truly global data lives here (GPU, counters).
    All user-specific data lives in SessionState to prevent cross-user leaks."""

    def __init__(self):
        # Truly global — safe to share (read-only metrics)
        self.gpu_telemetry = "Temp: -- | VRAM: --"

        # Restore global counters from DB (persist across restarts)
        try:
            from src.persistence import load_global_counters
            tasks, llm = load_global_counters()
            self.tasks_completed: int = tasks
            self.total_llm_calls: int = llm
        except Exception:
            self.tasks_completed: int = 0
            self.total_llm_calls: int = 0

        # Per-session state
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._active_session_id: str = "default"

        # Create default session
        self.get_session("default")
        self._sessions["default"].load(SESSION_FILE)

    def get_session(self, session_id: str) -> SessionState:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionState(session_id)
            return self._sessions[session_id]

    def set_active_session(self, session_id: str):
        with self._lock:
            self._active_session_id = session_id

    @property
    def session(self) -> SessionState:
        return self.get_session(self._active_session_id)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    # --- Backwards-compatible properties delegating to active session ---
    # These ensure all existing code that reads/writes state.X
    # actually reads/writes the ACTIVE SESSION's data, not global data.

    @property
    def chat_history(self) -> list[dict]:
        return self.session.chat_history
    @chat_history.setter
    def chat_history(self, val):
        self.session.chat_history = val

    @property
    def progress_log(self) -> list[str]:
        return self.session.progress_log
    @progress_log.setter
    def progress_log(self, val):
        self.session.progress_log = val

    @property
    def cmd_history(self) -> list[str]:
        return self.session.cmd_history
    @cmd_history.setter
    def cmd_history(self, val):
        self.session.cmd_history = val

    @property
    def task_started_at(self):
        return self.session.task_started_at
    @task_started_at.setter
    def task_started_at(self, val):
        self.session.task_started_at = val

    @property
    def current_status(self) -> str:
        return self.session.current_status
    @current_status.setter
    def current_status(self, val: str):
        self.session.current_status = val

    @property
    def current_step(self):
        return self.session.current_step
    @current_step.setter
    def current_step(self, val):
        self.session.current_step = val

    @property
    def step_index(self):
        return self.session.step_index
    @step_index.setter
    def step_index(self, val):
        self.session.step_index = val

    @property
    def total_steps(self):
        return self.session.total_steps
    @total_steps.setter
    def total_steps(self, val):
        self.session.total_steps = val

    @property
    def active_model(self):
        return self.session.active_model
    @active_model.setter
    def active_model(self, val):
        self.session.active_model = val

    @property
    def active_agents(self):
        return self.session.active_agents
    @active_agents.setter
    def active_agents(self, val):
        self.session.active_agents = val

    # Per-user settings — now delegate to session
    @property
    def enabled_tools(self) -> dict[str, bool]:
        return self.session.enabled_tools
    @enabled_tools.setter
    def enabled_tools(self, val):
        self.session.enabled_tools = val

    @property
    def model_override(self) -> str:
        return self.session.model_override
    @model_override.setter
    def model_override(self, val):
        self.session.model_override = val

    @property
    def user_system_prompt(self) -> str:
        return self.session.user_system_prompt
    @user_system_prompt.setter
    def user_system_prompt(self, val):
        self.session.user_system_prompt = val

    @property
    def execution_mode(self) -> str:
        return self.session.execution_mode
    @execution_mode.setter
    def execution_mode(self, val):
        self.session.execution_mode = val

    def begin_task(self, total_steps: int = 0):
        self.session.begin_task(total_steps)

    def advance_step(self, step_name: str, model: str = "", agents: list[str] | None = None):
        self.session.advance_step(step_name, model, agents)

    def finish_task(self):
        self.session.finish_task()
        self.tasks_completed += 1
        # Persist global counters to DB
        try:
            from src.persistence import save_global_counters
            save_global_counters(self.tasks_completed, self.total_llm_calls)
        except Exception:
            pass

    def get_recent_history(self, max_turns: int = 10) -> list[dict]:
        return self.session.get_recent_history(max_turns)

    def format_history_context(self, max_turns: int = 6) -> str:
        return self.session.format_history_context(max_turns)

    def save_session(self):
        self.session.save(SESSION_FILE)

    def tracking_snapshot(self) -> dict:
        snap = self.session.tracking_snapshot()
        snap["gpu"] = self.gpu_telemetry
        snap["tasks_completed"] = self.tasks_completed
        snap["total_llm_calls"] = self.total_llm_calls
        return snap


state = GlobalState()
