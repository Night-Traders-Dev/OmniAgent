"""Tests for FastAPI endpoints."""
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from src.web import app
from src.state import state

@pytest.fixture(autouse=True)
def reset():
    state.set_active_session("default")
    sess = state.session
    sess.current_status = "Idle"
    sess.chat_history.clear()
    sess.progress_log.clear()
    sess.cmd_history.clear()
    sess.task_started_at = None
    sess.step_index = 0
    sess.total_steps = 0
    state.tasks_completed = 0
    state.total_llm_calls = 0
    state.enabled_tools = {"web_search":True,"file_read":True,"file_write":True,"shell":True}
    state.model_override = "auto"
    state.user_system_prompt = ""
    state.execution_mode = "execute"
    yield

@pytest.fixture
def client(): return TestClient(app)

class TestHome:
    def test_html(self, client):
        r = client.get("/")
        assert r.status_code == 200 and "OmniAgent" in r.text

class TestMetrics:
    def test_returns(self, client):
        r = client.get("/api/metrics")
        d = r.json()
        assert "tasks_completed" in d
    def test_reflects(self, client):
        state.tasks_completed = 7
        assert client.get("/api/metrics").json()["tasks_completed"] == 7

class TestSettings:
    def test_get(self, client):
        d = client.get("/api/settings").json()
        assert "experts" in d and "user_system_prompt" in d
    def test_update(self, client):
        r = client.post("/api/settings", json={"reasoning":"new:13b"})
        assert r.json()["experts"]["reasoning"] == "new:13b"

class TestSystemPrompt:
    def test_get(self, client):
        assert client.get("/api/system-prompt").json()["prompt"] == ""
    def test_set(self, client):
        client.post("/api/system-prompt", json={"prompt":"Be concise"})
        assert state.user_system_prompt == "Be concise"
    def test_get_after_set(self, client):
        client.post("/api/system-prompt", json={"prompt":"test"})
        assert client.get("/api/system-prompt").json()["prompt"] == "test"

class TestExecutionMode:
    def test_get_default(self, client):
        assert client.get("/api/mode").json()["mode"] == "execute"
    def test_set_teach(self, client):
        client.post("/api/mode", json={"mode":"teach"})
        assert state.execution_mode == "teach"
    def test_set_execute(self, client):
        state.execution_mode = "teach"
        client.post("/api/mode", json={"mode":"execute"})
        assert state.execution_mode == "execute"
    def test_invalid_mode(self, client):
        assert client.post("/api/mode", json={"mode":"invalid"}).status_code == 400
    def test_settings_includes_mode(self, client):
        assert "execution_mode" in client.get("/api/settings").json()

class TestToolToggle:
    def test_off(self, client):
        client.post("/api/tools/toggle", json={"tool":"web_search","enabled":False})
        assert state.enabled_tools["web_search"] is False
    def test_on(self, client):
        state.enabled_tools["shell"] = False
        client.post("/api/tools/toggle", json={"tool":"shell","enabled":True})
        assert state.enabled_tools["shell"] is True
    def test_unknown(self, client):
        assert client.post("/api/tools/toggle", json={"tool":"nope","enabled":True}).status_code == 400

class TestToolsList:
    def test_lists(self, client):
        d = client.get("/api/tools").json()
        assert "read" in d["tools"]
        assert "edit" in d["tools"]
        assert "glob" in d["tools"]

class TestModelOverride:
    def test_set(self, client):
        client.post("/api/model-override", json={"model":"llama3:8b"})
        assert state.model_override == "llama3:8b"

class TestClearSession:
    def test_clears(self, client):
        state.chat_history.append({"role":"user","content":"t"})
        client.post("/api/clear-session")
        assert len(state.chat_history) == 0

class TestAgentRegistry:
    def test_lists(self, client):
        d = client.get("/api/agents").json()
        names = [a["name"] for a in d["agents"]]
        assert "coder" in names and "researcher" in names
    def test_has_tools_flag(self, client):
        d = client.get("/api/agents").json()
        coder = [a for a in d["agents"] if a["name"]=="coder"][0]
        assert coder["has_tools"] is True
        assert coder["max_steps"] >= 5

class TestExports:
    def setup_method(self):
        state.chat_history = [{"role":"user","content":"Hi"},{"role":"assistant","content":"Hello!"}]
    def test_json(self, client): assert client.get("/api/export/json").status_code == 200
    def test_md(self, client): assert "OmniAgent" in client.get("/api/export/md").text
    def test_txt(self, client): assert "[USER]" in client.get("/api/export/txt").text
    def test_csv(self, client): assert "role" in client.get("/api/export/csv").text
    def test_html(self, client): assert "<!DOCTYPE" in client.get("/api/export/html").text
    def test_bad(self, client): assert client.get("/api/export/pdf").status_code == 400

class TestChat:
    def test_with_flags(self, client):
        with patch("src.web.orchestrator.dispatch", new_callable=AsyncMock) as m:
            m.return_value = {"reply":"ok"}
            client.post("/chat", json={"message":"t","tool_flags":{"web_search":False},"model_override":"auto"})
            assert state.enabled_tools["web_search"] is False
