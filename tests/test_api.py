"""Tests for FastAPI endpoints."""
import json
import secrets
import pytest
from datetime import datetime, timedelta, timezone
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


def _create_test_session(*, admin: bool = False):
    from src.persistence import create_user, create_session, get_db

    username = f"api_{secrets.token_hex(4)}"
    user = create_user(username, "testpass123")
    assert user is not None

    conn = get_db()
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if admin else 0, user["id"]))
    conn.commit()
    conn.close()

    return user, create_session(user["id"], "API Test")

class TestHome:
    def test_html(self, client):
        r = client.get("/")
        assert r.status_code == 200 and "OmniAgent" in r.text

    def test_favicon(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 204

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


class TestSecurityGuards:
    def test_auth_user_includes_admin_flag(self, client):
        _, sid = _create_test_session(admin=True)
        r = client.get(f"/api/auth/user?session_id={sid}")
        assert r.status_code == 200
        assert r.json()["is_admin"] is True

    def test_mcp_requires_auth(self, client):
        r = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "python_eval", "arguments": {"expression": "21 * 2"}},
        })
        assert r.status_code == 401

    def test_mcp_allows_authenticated_session(self, client):
        _, sid = _create_test_session()
        r = client.post(f"/mcp?session_id={sid}", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "python_eval", "arguments": {"expression": "21 * 2"}},
        })
        assert r.status_code == 200
        assert "42" in r.json()["result"]["content"][0]["text"]

    def test_upload_requires_auth(self, client):
        r = client.post("/api/upload", files={"file": ("note.txt", b"hello world")})
        assert r.status_code == 401

    def test_upload_download_requires_auth(self, client):
        _, sid = _create_test_session()
        upload = client.post(
            "/api/upload",
            data={"session_id": sid},
            files={"file": ("note.txt", b"hello world")},
        )
        assert upload.status_code == 200
        filename = upload.json()["filename"]

        denied = client.get(f"/uploads/{filename}")
        assert denied.status_code == 401

        allowed = client.get(f"/uploads/{filename}?session_id={sid}")
        assert allowed.status_code == 200
        assert allowed.content == b"hello world"

    def test_plugin_endpoints_require_admin(self, client):
        _, sid = _create_test_session(admin=False)
        list_resp = client.get(f"/api/plugins?session_id={sid}")
        assert list_resp.status_code == 403
        r = client.post("/api/plugins/reload", json={"session_id": sid})
        assert r.status_code == 403

    def test_admin_plugin_reload_allowed(self, client):
        _, sid = _create_test_session(admin=True)
        r = client.post("/api/plugins/reload", json={"session_id": sid})
        assert r.status_code == 200
        assert "count" in r.json()

    def test_invite_list_requires_admin(self, client):
        _, sid = _create_test_session(admin=False)
        r = client.get(f"/api/auth/invite/list?session_id={sid}")
        assert r.status_code == 403


class TestHubFeeds:
    def test_hub_today_news_prefers_same_day_articles(self):
        from src.web import _hub_today_news

        now = datetime.now(timezone.utc)
        older = (now - timedelta(days=1)).isoformat()
        today = now.isoformat()

        class FakeDDGS:
            def news(self, *args, **kwargs):
                return [
                    {"date": older, "title": "Older", "body": "old", "url": "https://old.example/a", "image": "", "source": "Old"},
                    {"date": today, "title": "Today", "body": "new", "url": "https://today.example/b", "image": "https://img.example/b.jpg", "source": "Today"},
                ]

        with patch("ddgs.DDGS", return_value=FakeDDGS()):
            articles = _hub_today_news("test", max_results=2)

        assert articles[0]["title"] == "Today"
        assert articles[0]["thumbnail"] == "https://img.example/b.jpg"
        assert len(articles) == 2

    def test_hub_markets_summary_includes_stocks_etfs_and_crypto(self, client):
        stock_quotes = [
            {"symbol": "NVDA", "regularMarketChangePercent": 2.16},
            {"symbol": "SMCI", "regularMarketChangePercent": 6.09},
            {"symbol": "ONDS", "regularMarketChangePercent": 8.53},
        ]
        etf_quotes = [
            {"symbol": "SPY", "regularMarketChangePercent": 0.42},
            {"symbol": "QQQ", "regularMarketChangePercent": 0.87},
            {"symbol": "IWM", "regularMarketChangePercent": -0.33},
        ]
        crypto_quotes = [
            {"symbol": "btc", "price_change_percentage_24h_in_currency": 3.92},
            {"symbol": "eth", "price_change_percentage_24h_in_currency": 4.11},
            {"symbol": "sol", "price_change_percentage_24h_in_currency": 5.48},
        ]

        with patch("src.web._hub_fetch_yahoo_screen", side_effect=[stock_quotes, etf_quotes]), \
             patch("src.web._hub_fetch_top_crypto", return_value=crypto_quotes):
            r = client.get("/api/hub/markets")

        assert r.status_code == 200
        data = r.json()
        assert "Stocks:" in data["summary"]
        assert "ETFs:" in data["summary"]
        assert "Crypto:" in data["summary"]
        assert data["stocks"][0]["symbol"] == "NVDA"
        assert data["etfs"][0]["symbol"] == "SPY"
        assert data["crypto"][0]["symbol"] == "btc"

    def test_hub_top_crypto_skips_stablecoins(self):
        from src.web import _hub_fetch_top_crypto

        payload = [
            {"symbol": "btc", "price_change_percentage_24h_in_currency": 3.0},
            {"symbol": "usdt", "price_change_percentage_24h_in_currency": 0.0},
            {"symbol": "eth", "price_change_percentage_24h_in_currency": 2.0},
            {"symbol": "usdc", "price_change_percentage_24h_in_currency": 0.0},
            {"symbol": "sol", "price_change_percentage_24h_in_currency": 5.0},
        ]

        with patch("src.web._hub_fetch_json", return_value=payload):
            crypto = _hub_fetch_top_crypto(count=3)

        assert [item["symbol"] for item in crypto] == ["btc", "eth", "sol"]

    def test_non_owner_cannot_share_session(self, client):
        owner, owner_sid = _create_test_session()
        attacker, attacker_sid = _create_test_session()
        r = client.post("/api/collab/share", json={"session_id": attacker_sid, "target_session": owner_sid})
        assert r.status_code == 403

    def test_oauth_config_requires_admin(self, client):
        _, sid = _create_test_session(admin=False)
        r = client.post("/api/oauth/config", json={
            "service": "github",
            "client_id": "abc",
            "client_secret": "xyz",
            "session_id": sid,
        })
        assert r.status_code == 403
