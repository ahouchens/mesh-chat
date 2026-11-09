"""Trusted migration, durable legacy write fences and format downgrade denial."""

import os

import pytest

from mesh_chat import vault
from mesh_chat.errors import StorageUnavailable
from mesh_chat.vault import RecordConflict, VaultStore
from test_core_messages import host
from test_core_composer import open_composer, query, save, send


def test_only_private_host_can_preview_and_migrate_legacy_draft(host):
    service = host()
    service.store.put("draft", "internal-peer", {"contact_id": "internal-peer", "text": "host UI legacy text"})
    public, public_scope = open_composer(service, caller="external-consumer")
    assert query(public, public_scope)["result"]["text"] == ""
    owner, owner_scope = open_composer(service, legacy=True)
    initial = query(owner, owner_scope)["result"]
    assert initial["revision"] is None and initial["text"] == "host UI legacy text"
    assert service.store.get("draft", "internal-peer")["text"] == initial["text"]
    assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "1"
    assert save(owner, owner_scope, initial["text"], initial)["ok"]
    assert service.store.get("draft", "internal-peer") is None
    assert service.store.list("record_write_fence")
    assert owner("peer.draft_set", **owner_scope, text="old late UI writer")["error"]["code"] == "conflict"
    assert query(public, public_scope)["result"]["text"] == ""
    with pytest.raises(RecordConflict):
        service.store.put("draft", "internal-peer", {"text": "old direct service writer"})
    assert query(owner, owner_scope)["result"]["text"] == initial["text"]


def test_legacy_source_change_invalidates_initial_cas_ticket(host):
    service = host()
    service.store.put("draft", "internal-peer", {"text": "first legacy version"})
    owner, scope = open_composer(service, legacy=True)
    initial = query(owner, scope)["result"]
    service.store.put("draft", "internal-peer", {"text": "newer legacy version"})
    rejected = save(owner, scope, "stale migration", initial)
    assert rejected["ok"] is False, rejected
    assert service.store.list("api_composer") == []
    assert service.store.get("draft", "internal-peer")["text"] == "newer legacy version"


def test_migration_failure_rolls_back_source_fence_and_schema_floor(host, monkeypatch):
    service = host()
    original_draft = {"text": "recoverable legacy draft"}
    service.store.put("draft", "internal-peer", original_draft)
    owner, scope = open_composer(service, legacy=True)
    original = service.store._write_records_locked

    def fail(*args):
        original(*args)
        raise OSError("injected migration transaction fault")
    monkeypatch.setattr(service.store, "_write_records_locked", fail)
    reply = save(owner, scope, original_draft["text"])
    assert reply["error"]["code"] == "unavailable", reply
    assert service.store.get("draft", "internal-peer") == original_draft
    assert service.store.list("record_write_fence") == service.store.list("api_composer") == []
    assert service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0] == "1"


def test_fence_survives_reopen_before_any_core_binding_and_old_format_reader_fails(host, monkeypatch):
    service = host()
    owner, scope = open_composer(service, legacy=True)
    assert save(owner, scope, "migrated text")["ok"]
    root, key = service.profile_dir, service.store._key
    service.close()
    with VaultStore(root, key, allow_unprotected_for_tests=True) as reopened:
        with pytest.raises(RecordConflict):
            reopened.put("draft", "internal-peer", {"text": "writer before Core initialization"})
    monkeypatch.setattr(vault, "MAX_SCHEMA_VERSION", 1)
    with pytest.raises(StorageUnavailable, match="Unsupported vault schema"):
        VaultStore(root, key, allow_unprotected_for_tests=True)


def test_contact_erasure_clears_composers_of_all_callers_once_without_projection_overlap(host):
    service = host()
    owner, scope = open_composer(service, legacy=True)
    external, external_scope = open_composer(service, caller="external-writer")
    assert save(owner, scope, "owner draft")["ok"]
    assert save(external, external_scope, "consumer draft")["ok"]
    reply = owner("peer.delete", **scope)
    assert reply["ok"], reply
    assert service.store.get("contact", "internal-peer") is None
    assert all(row["text"] == "" for row in service.store.list("api_composer"))


def test_public_legacy_drafts_are_caller_scoped_without_importing_ui_text(host):
    service = host()
    service.store.put("draft", "internal-peer", {"text": "private UI legacy"})
    first, first_scope = open_composer(service, caller="consumer-one")
    second, second_scope = open_composer(service, caller="consumer-two")
    assert first("peer.draft_get", **first_scope)["result"]["text"] == ""
    assert first("peer.draft_set", **first_scope, text="consumer one")["ok"]
    assert second("peer.draft_get", **second_scope)["result"]["text"] == ""
    assert service.store.get("draft", "internal-peer")["text"] == "private UI legacy"
    own = query(first, first_scope)["result"]
    assert own["text"] == "consumer one" and own["revision"] is None
    assert save(first, first_scope, own["text"], own)["ok"]
    assert first("peer.draft_set", **first_scope, text="late legacy overwrite")["error"]["code"] == "conflict"
