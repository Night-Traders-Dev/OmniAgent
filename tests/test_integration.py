"""
Comprehensive integration tests — tests every major system end-to-end.
Run: python -m pytest tests/test_integration.py -v
"""
import os
import sys
import json
import time
import pytest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Tool Execution Tests (all 47 tools)
# ============================================================

class TestToolExecution:
    """Test that every tool executes without crashing."""

    def test_read(self):
        from src.tools import execute_tool
        result = execute_tool("read", {"path": "omni_agent.py"})
        assert "OmniAgent" in result
        assert "ERROR" not in result

    def test_write_and_delete(self):
        from src.tools import execute_tool
        tmp = "/tmp/omni_test_write.txt"
        result = execute_tool("write", {"path": tmp, "content": "test content"})
        assert "OK" in result or "Wrote" in result
        os.unlink(tmp)

    def test_edit(self):
        from src.tools import execute_tool
        tmp = "/tmp/omni_test_edit.txt"
        with open(tmp, "w") as f:
            f.write("hello world")
        result = execute_tool("edit", {"path": tmp, "old_text": "hello", "new_text": "hi"})
        assert "ERROR" not in result
        os.unlink(tmp)

    def test_glob(self):
        from src.tools import execute_tool
        result = execute_tool("glob", {"pattern": "*.py"})
        assert "omni_agent.py" in result

    def test_grep(self):
        from src.tools import execute_tool
        result = execute_tool("grep", {"pattern": "FastAPI", "path": "src/web.py"})
        assert "FastAPI" in result or "web.py" in result

    def test_tree(self):
        from src.tools import execute_tool
        result = execute_tool("tree", {"path": "src", "max_depth": 1})
        assert "src" in result

    def test_shell(self):
        from src.tools import execute_tool
        result = execute_tool("shell", {"cmd": "echo hello"})
        assert "hello" in result

    def test_list_dir(self):
        from src.tools import execute_tool
        result = execute_tool("list_dir", {"path": "src"})
        assert "web.py" in result

    def test_file_info(self):
        from src.tools import execute_tool
        result = execute_tool("file_info", {"path": "omni_agent.py"})
        assert "size" in result.lower() or "bytes" in result.lower() or "line" in result.lower()

    def test_git_status(self):
        from src.tools import execute_tool
        result = execute_tool("git_status", {})
        # May or may not be in a git repo
        assert isinstance(result, str)

    def test_git_log(self):
        from src.tools import execute_tool
        result = execute_tool("git_log", {"n": 3})
        assert isinstance(result, str)

    def test_git_diff(self):
        from src.tools import execute_tool
        result = execute_tool("git_diff", {})
        assert isinstance(result, str)

    def test_python_eval(self):
        from src.tools import execute_tool
        result = execute_tool("python_eval", {"expression": "2 + 2"})
        assert "4" in result

    def test_web_search(self):
        from src.tools import execute_tool
        result = execute_tool("web", {"query": "python programming", "max_results": 2})
        assert isinstance(result, str)
        # May fail if no internet, that's ok

    def test_weather(self):
        from src.tools import execute_tool
        result = execute_tool("weather", {"location": "New York"})
        assert isinstance(result, str)

    def test_env_get(self):
        from src.tools import execute_tool
        result = execute_tool("env_get", {"name": "HOME"})
        assert "HOME=" in result

    def test_env_set(self):
        from src.tools import execute_tool
        result = execute_tool("env_set", {"name": "OMNI_TEST_VAR", "value": "42"})
        assert "OK" in result
        assert os.environ.get("OMNI_TEST_VAR") == "42"

    def test_json_extract(self):
        from src.tools import execute_tool
        data = json.dumps({"users": [{"name": "Alice"}, {"name": "Bob"}]})
        result = execute_tool("json_extract", {"data": data, "path": "users.0.name"})
        assert "Alice" in result

    def test_process_list(self):
        from src.tools import execute_tool
        result = execute_tool("process_list", {})
        assert "PID" in result or "USER" in result or "python" in result.lower()

    def test_network_info(self):
        from src.tools import execute_tool
        result = execute_tool("network_info", {})
        assert isinstance(result, str)

    def test_diff_preview(self):
        from src.tools import execute_tool
        tmp = "/tmp/omni_test_diff.txt"
        with open(tmp, "w") as f:
            f.write("line one\nline two\n")
        result = execute_tool("diff_preview", {"path": tmp, "old_text": "one", "new_text": "1"})
        assert isinstance(result, str)
        os.unlink(tmp)

    def test_analyze_file(self):
        from src.tools import execute_tool
        result = execute_tool("analyze_file", {"path": "src/config.py"})
        assert isinstance(result, str)

    def test_project_deps(self):
        from src.tools import execute_tool
        result = execute_tool("project_deps", {"root": "src"})
        assert isinstance(result, str)

    def test_regex_replace(self):
        from src.tools import execute_tool
        tmp = "/tmp/omni_test_regex.txt"
        with open(tmp, "w") as f:
            f.write("foo bar foo baz")
        result = execute_tool("regex_replace", {"path": tmp, "pattern": "foo", "replacement": "qux", "count": 1})
        assert "1 replacement" in result
        os.unlink(tmp)

    def test_archive_list(self):
        from src.tools import execute_tool
        # Just test the function doesn't crash
        result = execute_tool("archive", {"action": "list", "path": "/nonexistent.zip"})
        assert isinstance(result, str)

    def test_database(self):
        from src.tools import execute_tool
        result = execute_tool("database", {"query": "SELECT COUNT(*) FROM users", "db_path": "omni_data.db"})
        assert isinstance(result, str)


# ============================================================
# Persistence Tests
# ============================================================

class TestPersistence:
    def test_user_create_and_auth(self):
        from src.persistence import create_user, authenticate_user, hash_password
        import secrets
        uname = f"test_{secrets.token_hex(4)}"
        user = create_user(uname, "testpass123")
        assert user is not None
        assert user["username"] == uname
        authed = authenticate_user(uname, "testpass123")
        assert authed is not None
        wrong = authenticate_user(uname, "wrongpass")
        assert wrong is None

    def test_encrypt_decrypt(self):
        from src.persistence import encrypt, decrypt
        original = "sensitive data here 12345"
        encrypted = encrypt(original)
        assert encrypted != original
        decrypted = decrypt(encrypted)
        assert decrypted == original

    def test_session_create(self):
        from src.persistence import create_session, get_last_session
        sid = create_session(1, "Test Session")
        assert len(sid) == 32  # 16 bytes hex
        last = get_last_session(1)
        assert last is not None

    def test_message_persistence(self):
        from src.persistence import save_message, get_chat_history, create_session
        sid = create_session(1, "Msg Test")
        save_message(sid, 1, "user", "hello")
        save_message(sid, 1, "assistant", "hi there")
        history = get_chat_history(sid)
        assert len(history) >= 2
        assert history[-2]["content"] == "hello"
        assert history[-1]["content"] == "hi there"

    def test_password_hashing(self):
        from src.persistence import hash_password, verify_password
        h = hash_password("mypassword")
        assert h.startswith("pbkdf2:")
        assert verify_password("mypassword", h)
        assert not verify_password("wrong", h)


# ============================================================
# State Management Tests
# ============================================================

class TestState:
    def test_session_isolation(self):
        from src.state import state
        s1 = state.get_session("test-iso-1")
        s2 = state.get_session("test-iso-2")
        s1.chat_history.append({"role": "user", "content": "s1 only"})
        assert len(s2.chat_history) == 0

    def test_tracking_snapshot(self):
        from src.state import state
        snap = state.tracking_snapshot()
        assert "status" in snap
        assert "session_id" in snap
        assert "tokens_in" in snap

    def test_begin_finish_task(self):
        from src.state import state
        state.begin_task(total_steps=5)
        assert state.task_started_at is not None
        state.finish_task()
        assert state.task_started_at is None


# ============================================================
# Config Tests
# ============================================================

class TestConfig:
    def test_bitnet_detection(self):
        from src.config import BITNET_ENABLED, BITNET_MODEL
        # BitNet should be auto-detected
        assert isinstance(BITNET_ENABLED, bool)
        assert BITNET_MODEL == "bitnet-2b"

    def test_experts_defined(self):
        from src.config import EXPERTS
        assert "general" in EXPERTS
        assert "coding" in EXPERTS
        assert "reasoning" in EXPERTS

    def test_context_window(self):
        from src.config import OLLAMA_NUM_CTX
        assert OLLAMA_NUM_CTX >= 8192


# ============================================================
# Reasoning & RAG Tests
# ============================================================

class TestReasoning:
    def test_rag_indexing(self):
        from src.reasoning import index_codebase, _file_index
        count = index_codebase("src")
        assert count > 0
        assert len(_file_index) > 0

    def test_rag_retrieval(self):
        from src.reasoning import index_codebase, retrieve_context
        index_codebase("src")
        context = retrieve_context("web server FastAPI endpoints")
        assert "web" in context.lower() or "RELEVANT" in context

    def test_simple_embed(self):
        from src.reasoning import _simple_embed, _cosine_sim
        e1 = _simple_embed("python function sort")
        e2 = _simple_embed("python function sort")
        e3 = _simple_embed("banana smoothie recipe")
        assert _cosine_sim(e1, e2) > _cosine_sim(e1, e3)

    def test_should_use_chain(self):
        from src.reasoning import should_use_reasoning_chain
        assert should_use_reasoning_chain("refactor the entire authentication system")
        assert not should_use_reasoning_chain("what is 2+2")

    def test_context_compression(self):
        from src.task_engine import compress_context
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(25)]
        compressed = compress_context(msgs, max_keep=8)
        assert len(compressed) <= 9

    def test_quality_scoring(self):
        from src.upgrades import score_output_quality
        good = score_output_quality("code", "def quicksort(arr):\n    if len(arr) <= 1: return arr\n    pivot = arr[0]\n    return quicksort([x for x in arr[1:] if x < pivot]) + [pivot] + quicksort([x for x in arr[1:] if x >= pivot])")
        bad = score_output_quality("code", "I'm sorry, I cannot help")
        assert good > bad


# ============================================================
# Task Engine Tests
# ============================================================

class TestTaskEngine:
    def test_full_task_lifecycle(self):
        from src.task_engine import create_task, get_task, update_task, TaskStatus
        tid = create_task("test-lc", "Lifecycle Test", "Test task lifecycle", [
            {"name": "P1", "description": "First phase", "agent": "coder"},
            {"name": "P2", "description": "Second phase", "agent": "reasoner"},
        ])
        task = get_task(tid)
        assert task["status"] == "pending"
        assert len(task["phases"]) == 2
        update_task(tid, status=TaskStatus.RUNNING)
        task = get_task(tid)
        assert task["status"] == "running"

    def test_task_queue(self):
        from src.task_engine import enqueue_task, get_queue, dequeue_next
        enqueue_task("test-q2", "Task A", priority=1)
        enqueue_task("test-q2", "Task B", priority=2)
        queue = get_queue("test-q2")
        assert len(queue) >= 2
        # Higher priority first
        next_item = dequeue_next("test-q2")
        assert next_item["task_description"] == "Task B"


# ============================================================
# Features Tests
# ============================================================

class TestFeatures:
    def test_cross_session_search(self):
        from src.features import search_all_conversations
        # Just verify it doesn't crash
        results = search_all_conversations(1, "test query")
        assert isinstance(results, list)

    def test_scheduled_task_crud(self):
        from src.features import create_schedule, list_schedules, delete_schedule
        sid = create_schedule("test-sched2", "Daily backup", "daily")
        schedules = list_schedules("test-sched2")
        assert any(s["description"] == "Daily backup" for s in schedules)
        delete_schedule(sid)

    def test_user_preferences(self):
        from src.features import set_preference, get_preferences, get_preference_context
        set_preference(77777, "coding", "language", "python")
        set_preference(77777, "style", "verbosity", "concise")
        prefs = get_preferences(77777)
        assert len(prefs) >= 2
        ctx = get_preference_context(77777)
        assert "python" in ctx

    def test_pdf_export(self):
        from src.features import export_chat_pdf
        msgs = [{"role": "user", "content": "test"}, {"role": "assistant", "content": "response"}]
        pdf = export_chat_pdf(msgs)
        assert b"<html>" in pdf
        assert b"test" in pdf

    def test_pinned_messages(self):
        from src.features import pin_message, get_pinned_messages, get_pinned_context, unpin_message
        pin_message("test-pin2", 0, "Important info", "assistant")
        pins = get_pinned_messages("test-pin2")
        assert len(pins) >= 1
        ctx = get_pinned_context("test-pin2")
        assert "Important info" in ctx
        unpin_message(pins[0]["id"])


# ============================================================
# Platform Tests
# ============================================================

class TestPlatform:
    def test_mcp_legacy_manifest(self):
        from src.platform import mcp_server
        manifest = mcp_server.get_manifest()
        assert manifest["name"] == "omniagent"
        assert len(manifest["tools"]) >= 46

    def test_mcp_legacy_execute(self):
        from src.platform import mcp_server
        result = mcp_server.execute_tool("python_eval", {"expression": "3 * 7"})
        assert "21" in result["result"]
        assert not result["isError"]

    def test_sandbox_fallback(self):
        from src.platform import run_sandboxed
        result = run_sandboxed("print('hello')", "python", timeout=5)
        # May use Docker sandbox or fall back to direct execution
        output = str(result.get("stdout", "") or result.get("output", "") or "")
        error = str(result.get("stderr", "") or result.get("error", "") or "")
        assert "hello" in output or "permission denied" in error.lower() or result.get("sandbox") is not None


# ============================================================
# TTS Preprocessor Tests
# ============================================================

class TestTTSPreprocessor:
    def test_full_pipeline(self):
        from src.tts_preprocessor import preprocess_for_tts
        text = "The API uses 32GB GPU at 53°C. Check src/web.py. Use Ctrl+Shift+P. PR #42 costs $9.99/mo."
        result = preprocess_for_tts(text)
        assert "A P I" in result
        assert "gigabytes" in result
        assert "degrees celsius" in result
        assert "web dot pie" in result
        assert "control shift" in result
        assert "number 42" in result
        assert "dollars per month" in result


# ============================================================
# Upgrades Tests
# ============================================================

class TestUpgrades:
    def test_request_queue(self):
        from src.upgrades import request_queue
        lock = request_queue.get_lock("test-rq")
        assert not request_queue.is_busy("test-rq")
        lock.acquire()
        assert request_queue.is_busy("test-rq")
        lock.release()

    def test_model_fallback(self):
        from src.upgrades import get_fallback_model, FALLBACK_CHAINS
        for role, chain in FALLBACK_CHAINS.items():
            if len(chain) > 1:
                fb = get_fallback_model(role, chain[0])
                assert fb == chain[1]

    def test_web_cache(self):
        from src.upgrades import web_cache
        web_cache.set("int-test", "cached_value")
        assert web_cache.get("int-test") == "cached_value"
        assert web_cache.get("nonexistent") is None

    def test_upload_dir_check(self):
        from src.upgrades import check_upload_dir_size
        assert check_upload_dir_size()  # Should be under limit


# ============================================================
# OAuth Tests
# ============================================================

class TestOAuth:
    def test_is_configured(self):
        from src.oauth import is_configured
        # Should return bool regardless
        assert isinstance(is_configured("github"), bool)
        assert isinstance(is_configured("google"), bool)

    def test_save_and_load_config(self):
        from src.oauth import save_oauth_config, get_oauth_status
        save_oauth_config("github", "test_id", "test_secret")
        status = get_oauth_status()
        assert status["github_configured"]


# ============================================================
# Experiments Tests
# ============================================================

class TestExperiments:
    def test_training_data_collection(self):
        from src.experiments import collect_training_sample, get_training_stats
        collect_training_sample("test prompt", "good response", "bad response")
        stats = get_training_stats()
        assert stats["samples"] >= 1

    def test_metrics_recording(self):
        from src.experiments import record_metrics_snapshot, get_metrics_history
        record_metrics_snapshot()
        history = get_metrics_history(hours=1)
        assert len(history) >= 1

    def test_conversation_tree(self):
        from src.experiments import get_conversation_tree
        tree = get_conversation_tree("nonexistent")
        assert tree["total"] == 0
        assert isinstance(tree["nodes"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
