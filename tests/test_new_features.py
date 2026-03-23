"""Tests for new features: task engine, TTS preprocessor, upgrades, features module."""
import os
import sys
import json
import types
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTTSPreprocessor:
    def test_abbreviations(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "A P I" in preprocess_for_tts("The API works")
        assert "G P U" in preprocess_for_tts("Check GPU")
        assert "jason" in preprocess_for_tts("Parse JSON")

    def test_temperatures(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "degrees celsius" in preprocess_for_tts("It's 53°C")
        assert "degrees fahrenheit" in preprocess_for_tts("It's 72°F")

    def test_percentages(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "85 percent" in preprocess_for_tts("CPU at 85%")

    def test_file_paths(self):
        from src.tts_preprocessor import preprocess_for_tts
        result = preprocess_for_tts("Check src/web.py")
        assert "web dot pie" in result

    def test_keyboard_shortcuts(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "control shift" in preprocess_for_tts("Press Ctrl+Shift+P")

    def test_money(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "dollars per month" in preprocess_for_tts("$29.99/mo")

    def test_data_sizes(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "gigabytes" in preprocess_for_tts("6GB VRAM")
        assert "24 of 32 gigabytes" in preprocess_for_tts("24/32GB")

    def test_markdown_stripped(self):
        from src.tts_preprocessor import preprocess_for_tts
        result = preprocess_for_tts("**bold** text *italic*")
        assert "**" not in result
        assert "bold" in result

    def test_code_blocks_removed(self):
        from src.tts_preprocessor import preprocess_for_tts
        result = preprocess_for_tts("Here is code:\n```python\nprint('hi')\n```\nDone.")
        assert "code block omitted" in result

    def test_urls_simplified(self):
        from src.tts_preprocessor import preprocess_for_tts
        result = preprocess_for_tts("Visit https://github.com/app")
        assert "github dot com" in result

    def test_versions(self):
        from src.tts_preprocessor import preprocess_for_tts
        assert "version 8 point 1" in preprocess_for_tts("Running v8.1")


class TestTaskEngine:
    def test_create_and_get_task(self):
        from src.task_engine import create_task, get_task
        tid = create_task("test", "Test Task", "Description", [
            {"name": "Phase 1", "description": "Do stuff", "agent": "coder"},
        ])
        assert tid
        task = get_task(tid)
        assert task["title"] == "Test Task"
        assert len(task["phases"]) == 1
        assert task["status"] == "pending"

    def test_list_tasks(self):
        from src.task_engine import create_task, list_tasks
        create_task("test-list", "Task A", "Desc", [{"name": "P1", "description": "d"}])
        tasks = list_tasks("test-list")
        assert len(tasks) >= 1

    def test_task_queue(self):
        from src.task_engine import enqueue_task, get_queue
        enqueue_task("test-queue", "Do something", priority=1)
        queue = get_queue("test-queue")
        assert len(queue) >= 1
        assert queue[0]["task_description"] == "Do something"

    def test_context_compression(self):
        from src.task_engine import compress_context
        msgs = [{"role": "user", "content": f"message {i}"} for i in range(30)]
        compressed = compress_context(msgs, max_keep=10)
        assert len(compressed) <= 11  # 1 summary + 10 recent
        assert len(compressed) < len(msgs)


class TestUpgrades:
    def test_web_cache(self):
        from src.upgrades import web_cache
        web_cache.set("test:key", "value123")
        assert web_cache.get("test:key") == "value123"
        assert web_cache.get("nonexistent") is None

    def test_quality_scoring(self):
        from src.upgrades import score_output_quality
        good = score_output_quality("write code", "Here is the implementation with a class and methods...")
        bad = score_output_quality("test", "I'm sorry, I cannot help with that as an AI")
        assert good > bad

    def test_fallback_model(self):
        from src.upgrades import get_fallback_model
        assert get_fallback_model("coding", "qwen2.5-coder:7b") == "dolphin3:8b"
        assert get_fallback_model("coding", "dolphin3:8b") == "qwen3:8b"
        assert get_fallback_model("general", "qwen3:8b") == "dolphin3:8b"

    def test_general_model_default(self):
        from src.config import EXPERTS
        assert EXPERTS["general"] == "qwen3:8b"

    def test_login_lockout(self):
        from src.upgrades import check_login_lockout, record_failed_login, clear_login_attempts
        clear_login_attempts("locktest")
        assert not check_login_lockout("locktest")
        for _ in range(10):
            record_failed_login("locktest")
        assert check_login_lockout("locktest")
        clear_login_attempts("locktest")

    def test_upload_dir_size(self):
        from src.upgrades import check_upload_dir_size
        assert isinstance(check_upload_dir_size(), bool)


class TestModelDefaults:
    def test_detect_vision_model_prefers_qwen3_vl(self, monkeypatch):
        from src import multimodal

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "models": [
                        {"name": "llama3.2-vision:11b"},
                        {"name": "qwen3-vl:8b"},
                    ]
                }).encode()

        monkeypatch.setattr(multimodal.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
        assert multimodal._detect_vision_model() == "qwen3-vl:8b"

    def test_gpu_worker_verifier_defaults_to_qwen3(self, monkeypatch):
        import gpu_worker

        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"correct": true, "score": 9, "issues": [], "summary": "ok"}'))]
                )

        class FakeOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = types.SimpleNamespace(completions=FakeCompletions())

        monkeypatch.delenv("VERIFY_MODEL", raising=False)
        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

        req = gpu_worker.VerifyReq(original_prompt="hello", original_result="world")
        result = gpu_worker._verify_sync(req)

        assert result["ok"] is True
        assert captured["model"] == "qwen3:8b"

    def test_minimax_model_uses_remote_client(self, monkeypatch):
        from src import config

        local_client = object()
        remote_client = object()

        monkeypatch.setattr(config, "CLIENT", local_client)
        monkeypatch.setattr(config, "MINIMAX_CLIENT", remote_client)

        assert config.get_client_for_model("qwen3:8b") is local_client
        assert config.get_client_for_model("MiniMax-M2.7") is remote_client

    def test_minimax_fallback_can_take_over_general_role(self, monkeypatch):
        from src import config

        calls = []

        class FailingCompletions:
            def create(self, **kwargs):
                calls.append(("local", kwargs["model"]))
                raise RuntimeError("ollama offline")

        class RemoteCompletions:
            def create(self, **kwargs):
                calls.append(("remote", kwargs["model"]))
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
                    usage=None,
                )

        local_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=FailingCompletions()))
        remote_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=RemoteCompletions()))

        monkeypatch.setattr(config, "CLIENT", local_client)
        monkeypatch.setattr(config, "MINIMAX_CLIENT", remote_client)
        monkeypatch.setattr(config, "MINIMAX_MODEL", "MiniMax-M2.7")
        monkeypatch.setattr(config, "MINIMAX_FALLBACK_ROLES", {"general"})

        response, used_model = config.create_chat_completion(
            model="qwen3:8b",
            model_key="general",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert response.choices[0].message.content == "ok"
        assert used_model == "MiniMax-M2.7"
        assert calls == [("local", "qwen3:8b"), ("remote", "MiniMax-M2.7")]


class TestFeatures:
    def test_pin_and_unpin(self):
        from src.features import pin_message, get_pinned_messages, unpin_message
        pin_message("test-pins", 0, "Important message", "assistant", "Remember this")
        pins = get_pinned_messages("test-pins")
        assert len(pins) >= 1
        assert pins[0]["content"] == "Important message"
        unpin_message(pins[0]["id"])

    def test_schedule_create(self):
        from src.features import create_schedule, list_schedules, delete_schedule
        sid = create_schedule("test-sched", "Run tests", "daily")
        schedules = list_schedules("test-sched")
        assert len(schedules) >= 1
        delete_schedule(sid)

    def test_preferences(self):
        from src.features import set_preference, get_preferences
        set_preference(99999, "coding", "indent", "tabs")
        prefs = get_preferences(99999, "coding")
        assert len(prefs) >= 1
        assert prefs[0]["value"] == "tabs"

    def test_pdf_export(self):
        from src.features import export_chat_pdf
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]
        pdf = export_chat_pdf(msgs, "Test Chat")
        assert b"<html>" in pdf
        assert b"Hello" in pdf
        assert b"Hi! How can I help?" in pdf

    def test_preference_learning(self):
        from src.features import learn_from_correction, get_preferences
        learn_from_correction(88888, "use tabs not spaces please")
        prefs = get_preferences(88888, "coding")
        indent_pref = [p for p in prefs if p["key"] == "indentation"]
        assert len(indent_pref) >= 1
        assert indent_pref[0]["value"] == "tabs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
