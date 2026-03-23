"""Tests for src/persistence.py — user accounts, sessions, chat history, metrics."""
import pytest
from src.persistence import (
    create_user, authenticate_user, get_user,
    create_session, rename_session, delete_session, list_user_sessions,
    get_session_user, can_access_session,
    save_message, get_chat_history, clear_chat_history,
    share_session, add_collaborator, remove_collaborator, get_session_collaborators,
    archive_session, unarchive_session,
    save_session_metrics, get_session_metrics,
    hash_password, verify_password,
    encrypt, decrypt,
)
import secrets


@pytest.fixture
def test_user():
    """Create a unique test user."""
    username = f"test_{secrets.token_hex(4)}"
    user = create_user(username, "testpass123")
    assert user is not None
    return user


@pytest.fixture
def test_session(test_user):
    """Create a test session."""
    sid = create_session(test_user["id"], "Test Chat")
    return sid


class TestPasswordHashing:
    def test_hash_verify(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h)

    def test_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts


class TestUserManagement:
    def test_create_user(self, test_user):
        assert test_user["id"] > 0
        assert test_user["username"].startswith("test_")

    def test_duplicate_user(self, test_user):
        result = create_user(test_user["username"], "pass")
        assert result is None

    def test_authenticate(self, test_user):
        user = authenticate_user(test_user["username"], "testpass123")
        assert user is not None
        assert user["id"] == test_user["id"]

    def test_authenticate_wrong_pass(self, test_user):
        assert authenticate_user(test_user["username"], "wrong") is None

    def test_get_user(self, test_user):
        user = get_user(test_user["id"])
        assert user is not None
        assert user["username"] == test_user["username"]


class TestSessionManagement:
    def test_create_session(self, test_user):
        sid = create_session(test_user["id"], "My Chat")
        assert len(sid) == 32  # 16 bytes hex

    def test_get_session_user(self, test_session, test_user):
        user = get_session_user(test_session)
        assert user is not None
        assert user["id"] == test_user["id"]

    def test_rename_session(self, test_session, test_user):
        rename_session(test_session, "Renamed Chat")
        sessions = list_user_sessions(test_user["id"])
        found = [s for s in sessions if s["id"] == test_session]
        assert found and found[0]["title"] == "Renamed Chat"

    def test_delete_session(self, test_session, test_user):
        delete_session(test_session)
        sessions = list_user_sessions(test_user["id"])
        assert not any(s["id"] == test_session for s in sessions)

    def test_list_sessions(self, test_user):
        sid1 = create_session(test_user["id"], "Chat 1")
        sid2 = create_session(test_user["id"], "Chat 2")
        sessions = list_user_sessions(test_user["id"])
        ids = [s["id"] for s in sessions]
        assert sid1 in ids
        assert sid2 in ids
        # Cleanup
        delete_session(sid1)
        delete_session(sid2)

    def test_can_access_own_session(self, test_session, test_user):
        assert can_access_session(test_session, test_user["id"])

    def test_cannot_access_other_session(self, test_session):
        assert not can_access_session(test_session, 999999)


class TestChatHistory:
    def test_save_and_retrieve(self, test_session, test_user):
        save_message(test_session, test_user["id"], "user", "Hello")
        save_message(test_session, test_user["id"], "assistant", "Hi there!")
        history = get_chat_history(test_session)
        assert len(history) >= 2
        assert history[-2]["role"] == "user"
        assert history[-2]["content"] == "Hello"
        assert history[-1]["role"] == "assistant"
        assert history[-1]["content"] == "Hi there!"

    def test_messages_encrypted(self, test_session, test_user):
        save_message(test_session, test_user["id"], "user", "secret message")
        # Read raw from DB
        from src.persistence import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (test_session,),
        ).fetchone()
        conn.close()
        assert row is not None
        # Raw content should NOT be plaintext
        assert row["content"] != "secret message"

    def test_clear_history(self, test_session, test_user):
        save_message(test_session, test_user["id"], "user", "temp")
        clear_chat_history(test_session)
        history = get_chat_history(test_session)
        assert len(history) == 0


class TestCollaboration:
    def test_share_session(self, test_session):
        share_session(test_session)
        # Verify it's marked as shared
        from src.persistence import get_db
        conn = get_db()
        row = conn.execute("SELECT is_shared FROM sessions WHERE id = ?", (test_session,)).fetchone()
        conn.close()
        assert row["is_shared"] in (1, "1")

    def test_add_collaborator(self, test_session, test_user):
        # Create a second user
        user2 = create_user(f"collab_{secrets.token_hex(4)}", "pass")
        assert user2 is not None
        result = add_collaborator(test_session, user2["username"])
        assert result is True
        # Check they can access
        assert can_access_session(test_session, user2["id"])
        # Check they appear in collaborators list
        collabs = get_session_collaborators(test_session)
        assert any(c["id"] == user2["id"] for c in collabs)

    def test_add_nonexistent_collaborator(self, test_session):
        result = add_collaborator(test_session, "nonexistent_user_xyz")
        assert result is False


class TestArchive:
    def test_archive_hides_session(self, test_user, test_session):
        archive_session(test_session)
        sessions = list_user_sessions(test_user["id"])
        assert not any(s["id"] == test_session for s in sessions)

    def test_unarchive_restores(self, test_user, test_session):
        archive_session(test_session)
        unarchive_session(test_session)
        sessions = list_user_sessions(test_user["id"])
        assert any(s["id"] == test_session for s in sessions)

    def test_archived_visible_with_flag(self, test_user, test_session):
        archive_session(test_session)
        sessions = list_user_sessions(test_user["id"], include_archived=True)
        assert any(s["id"] == test_session for s in sessions)


class TestSessionMetrics:
    def test_save_and_get(self, test_session):
        save_session_metrics(test_session, tasks_completed=5, total_llm_calls=10,
                           tokens_in=1000, tokens_out=500, commands_run=3)
        metrics = get_session_metrics(test_session)
        assert metrics is not None
        assert metrics["tasks_completed"] == 5
        assert metrics["tokens_in"] == 1000

    def test_upsert(self, test_session):
        save_session_metrics(test_session, 1, 2, 100, 50, 1)
        save_session_metrics(test_session, 3, 5, 300, 150, 2)
        metrics = get_session_metrics(test_session)
        assert metrics["tasks_completed"] == 3
        assert metrics["tokens_in"] == 300

    def test_metrics_in_session_list(self, test_user, test_session):
        save_session_metrics(test_session, 5, 10, 1000, 500, 3)
        sessions = list_user_sessions(test_user["id"])
        found = [s for s in sessions if s["id"] == test_session]
        assert found
        assert found[0]["metrics"]["tokens_in"] == 1000

    def test_no_metrics(self):
        assert get_session_metrics("nonexistent_session") is None
