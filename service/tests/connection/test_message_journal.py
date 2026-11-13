import os

import pytest

from mesh_chat.vault import VaultStore


def chat(identifier="one", **changes):
    return {"id": identifier, "kind": "chat", "contact_id": "peer", "direction": "outbound",
            "state": "queued", "text": "secret text", "created_at": 100, **changes}


@pytest.fixture
def journal(tmp_path):
    from mesh_chat.message_journal import MessageJournal
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        yield store, MessageJournal(store)


def test_journal_records_message_updates_and_removal_without_text(journal):
    store, events = journal
    store.put("message", "one", chat())
    store.put("message", "one", chat(state="received_by_endpoint"))
    store.put("message", "one", chat(state="delivered"))
    store.delete("message", "one")
    changes = events.read(0, 10)
    assert [event["sequence"] for event in changes] == [1, 2, 3, 4]
    assert [event["type"] for event in changes] == ["message.changed"] * 3 + ["message.removed"]
    assert [event["state"] for event in changes] == ["queued", "received_by_endpoint", "delivered", None]
    assert "secret text" not in str(store.list("message_event"))


def test_journal_records_direction_for_changed_and_removed_messages(journal):
    store, events = journal
    store.put("message", "in", chat("in", direction="inbound", state="delivered"))
    store.delete("message", "in")
    assert [event["direction"] for event in events.read(0, 2)] == ["inbound", "inbound"]
    store.put("message", "odd", chat("odd", direction="sideways"))
    assert events.read(2, 1)[0]["direction"] is None


def test_only_public_chat_changes_advance_the_stream(journal):
    store, events = journal
    store.put("message", "one", chat())
    store.put("message", "one", chat(native_id="private-native-identifier"))
    store.put("message", "receipt", chat("receipt", kind="receipt"))
    store.delete("message", "receipt")
    store.delete("message", "missing")
    assert events.head() == 1


def test_failed_projection_write_keeps_message_and_journal_unchanged(journal, monkeypatch):
    from mesh_chat.errors import StorageUnavailable
    store, events = journal
    store.put("message", "one", chat())
    original = store._seal
    def seal(kind, *args):
        if kind == "message_event": raise StorageUnavailable("journal unavailable")
        return original(kind, *args)
    monkeypatch.setattr(store, "_seal", seal)
    with pytest.raises(StorageUnavailable): store.put("message", "one", chat(state="delivered"))
    assert store.get("message", "one")["state"] == "queued"
    assert events.head() == 1


def test_ring_retention_is_bounded_even_for_a_large_atomic_batch(tmp_path, monkeypatch):
    from mesh_chat import message_journal
    monkeypatch.setattr(message_journal, "MAX_EVENTS", 4)
    with VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True) as store:
        events = message_journal.MessageJournal(store)
        store.put_many(("message", str(index), chat(str(index))) for index in range(20))
        assert events.head() == 20
        assert store.record_count("message_event") == 4
        assert [item["sequence"] for item in events.read(16, 4)] == [17, 18, 19, 20]
        with pytest.raises(message_journal.JournalGap): events.read(15, 4)


def test_replay_survives_vault_reopen_and_rejects_expired_events(tmp_path):
    from mesh_chat.message_journal import JournalGap, MessageJournal, RETENTION_SECONDS
    key = os.urandom(32)
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        events = MessageJournal(store, clock=lambda: 100)
        store.put("message", "one", chat())
        generation = events.generation
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as store:
        events = MessageJournal(store, clock=lambda: 101 + RETENTION_SECONDS)
        assert events.generation == generation and events.head() == 1
        with pytest.raises(JournalGap): events.read(0, 10)
