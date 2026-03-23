"""Tests for src/memory.py — persistent memory across sessions."""
import pytest
from src.memory import (
    remember, recall, recall_as_context, forget,
    extract_memories_from_conversation,
    CATEGORY_PREFERENCE, CATEGORY_CORRECTION, CATEGORY_CONVENTION, CATEGORY_FACT,
)

# Use a unique user_id for test isolation
TEST_USER = 99999


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up test memories before and after each test."""
    for m in recall(TEST_USER, limit=100):
        forget(TEST_USER, m["category"], m["key"])
    yield
    for m in recall(TEST_USER, limit=100):
        forget(TEST_USER, m["category"], m["key"])


class TestRememberRecall:
    def test_basic_roundtrip(self):
        remember(TEST_USER, CATEGORY_FACT, "user_role", "data scientist")
        memories = recall(TEST_USER, CATEGORY_FACT)
        assert len(memories) >= 1
        assert memories[0]["value"] == "data scientist"

    def test_update_existing(self):
        remember(TEST_USER, CATEGORY_FACT, "language", "Python")
        remember(TEST_USER, CATEGORY_FACT, "language", "Rust")
        memories = recall(TEST_USER, CATEGORY_FACT)
        vals = [m["value"] for m in memories if m["key"] == "language"]
        assert vals == ["Rust"]

    def test_recall_by_category(self):
        remember(TEST_USER, CATEGORY_PREFERENCE, "editor", "vim")
        remember(TEST_USER, CATEGORY_FACT, "os", "linux")
        prefs = recall(TEST_USER, CATEGORY_PREFERENCE)
        facts = recall(TEST_USER, CATEGORY_FACT)
        assert any(m["key"] == "editor" for m in prefs)
        assert not any(m["key"] == "os" for m in prefs)
        assert any(m["key"] == "os" for m in facts)

    def test_recall_all(self):
        remember(TEST_USER, CATEGORY_PREFERENCE, "pref1", "v1")
        remember(TEST_USER, CATEGORY_FACT, "fact1", "v2")
        all_memories = recall(TEST_USER)
        assert len(all_memories) >= 2

    def test_forget(self):
        remember(TEST_USER, CATEGORY_FACT, "temp", "to_delete")
        forget(TEST_USER, CATEGORY_FACT, "temp")
        memories = recall(TEST_USER, CATEGORY_FACT)
        assert not any(m["key"] == "temp" for m in memories)


class TestRecallAsContext:
    def test_empty(self):
        assert recall_as_context(TEST_USER) == ""

    def test_with_memories(self):
        remember(TEST_USER, CATEGORY_PREFERENCE, "style", "concise")
        ctx = recall_as_context(TEST_USER)
        assert "concise" in ctx
        assert "USER MEMORY" in ctx


class TestExtractMemories:
    def test_detects_correction(self):
        extract_memories_from_conversation(
            TEST_USER,
            "don't use semicolons in Python code",
            "OK, I won't use semicolons.",
        )
        memories = recall(TEST_USER, CATEGORY_CORRECTION)
        assert len(memories) >= 1
        assert "semicolons" in memories[0]["value"].lower()

    def test_detects_preference(self):
        extract_memories_from_conversation(
            TEST_USER,
            "I prefer tabs over spaces for indentation",
            "Noted, I'll use tabs.",
        )
        memories = recall(TEST_USER, CATEGORY_PREFERENCE)
        assert len(memories) >= 1
        assert "tabs" in memories[0]["value"].lower()

    def test_no_extraction_on_normal_message(self):
        extract_memories_from_conversation(
            TEST_USER,
            "What is the weather in London?",
            "It's 15°C and cloudy.",
        )
        memories = recall(TEST_USER)
        assert len(memories) == 0
