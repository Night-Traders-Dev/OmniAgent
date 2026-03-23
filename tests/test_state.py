"""Tests for src/state.py."""
import json
import pytest
from src.state import GlobalState, SessionState, ChatReq

class TestChatReq:
    def test_basic(self): assert ChatReq(message="hi").message == "hi"
    def test_flags(self): assert ChatReq(message="t", tool_flags={"web_search":False}).tool_flags["web_search"] is False
    def test_override(self): assert ChatReq(message="t", model_override="llama3:8b").model_override == "llama3:8b"
    def test_session_id(self): assert ChatReq(message="t", session_id="abc").session_id == "abc"

class TestSessionState:
    def setup_method(self): self.s = SessionState("test")

    def test_initial(self):
        assert self.s.session_id == "test"
        assert self.s.current_status == "Idle"
        assert self.s.chat_history == []

    def test_begin_task(self):
        self.s.begin_task(5)
        assert self.s.task_started_at is not None
        assert self.s.total_steps == 5

    def test_advance_step(self):
        self.s.begin_task()
        self.s.advance_step("Planning", model="m", agents=["p"])
        assert self.s.step_index == 1 and self.s.active_model == "m"

    def test_finish_task(self):
        self.s.begin_task(); self.s.finish_task()
        assert self.s.task_started_at is None

    def test_history(self):
        self.s.chat_history = [{"role":"user","content":"q"},{"role":"assistant","content":"a"}]*5
        assert len(self.s.get_recent_history(max_turns=2)) == 4

    def test_format_empty(self):
        assert self.s.format_history_context() == ""

    def test_format_content(self):
        self.s.chat_history = [{"role":"user","content":"hello"}]
        ctx = self.s.format_history_context()
        assert "CONVERSATION HISTORY" in ctx and "hello" in ctx

    def test_snapshot(self):
        self.s.begin_task(); self.s.advance_step("T", model="m")
        snap = self.s.tracking_snapshot()
        assert snap["current_step"] == "T" and snap["session_id"] == "test"

class TestGlobalState:
    def setup_method(self): self.s = GlobalState()

    def test_initial(self):
        # Global counters may be non-zero if restored from DB
        assert isinstance(self.s.tasks_completed, int)
        assert isinstance(self.s.total_llm_calls, int)

    def test_tools_defaults(self):
        assert all(self.s.enabled_tools[k] for k in ["web_search","file_read","file_write","shell"])

    def test_model_override(self): assert self.s.model_override == "auto"
    def test_system_prompt(self): assert self.s.user_system_prompt == ""

    def test_session_isolation(self):
        s1 = self.s.get_session("client1")
        s2 = self.s.get_session("client2")
        s1.chat_history.append({"role":"user","content":"from client1"})
        s2.chat_history.append({"role":"user","content":"from client2"})
        assert len(s1.chat_history) == 1
        assert len(s2.chat_history) == 1
        assert s1.chat_history[0]["content"] == "from client1"
        assert s2.chat_history[0]["content"] == "from client2"

    def test_session_progress_isolation(self):
        s1 = self.s.get_session("a")
        s2 = self.s.get_session("b")
        s1.progress_log.append("log from a")
        assert len(s2.progress_log) == 0

    def test_active_session_switching(self):
        self.s.get_session("x")
        self.s.get_session("y")
        self.s.set_active_session("x")
        self.s.chat_history.append({"role":"user","content":"x"})
        self.s.set_active_session("y")
        assert len(self.s.chat_history) == 0

    def test_list_sessions(self):
        self.s.get_session("s1")
        self.s.get_session("s2")
        sessions = self.s.list_sessions()
        assert "s1" in sessions and "s2" in sessions

    def test_global_metrics_shared(self):
        self.s.tasks_completed = 5
        self.s.set_active_session("a")
        assert self.s.tasks_completed == 5
        self.s.set_active_session("b")
        assert self.s.tasks_completed == 5

    def test_begin_finish_increments_global(self):
        self.s.set_active_session("test")
        before = self.s.tasks_completed
        self.s.begin_task()
        self.s.finish_task()
        assert self.s.tasks_completed == before + 1
