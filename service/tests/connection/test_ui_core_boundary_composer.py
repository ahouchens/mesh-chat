"""Independent serialized composer durability and present-authority boundaries."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3

import pytest

from mesh_chat.core_api.composition import bind_service_stream
from mesh_chat.core_api.host import CONSUMER_PERMISSIONS, host_grant
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore

OPERATIONS = {"peer.composer_query", "peer.composer_update", "message.enqueue_draft"}


class ComposerClient:
    def __init__(self, service, caller="boundary-composer-caller"):
        self.grant = host_grant(caller, CONSUMER_PERMISSIONS)
        self.session = bind_service_stream(service, lambda: self.grant)
        caps = self.call("runtime.capabilities")
        assert caps["ok"], caps
        assert caps["result"]["api_minor"] >= 1
        assert OPERATIONS <= set(caps["result"]["operations"]), caps
        assert caps["result"]["limits"]["composer_text_utf8_bytes"] == 16384
        profile = caps["result"]["profiles"][0]
        view = self.call("profile.query", {"profile": profile})
        assert view["ok"], view
        self.scope = {"profile": profile, "peer": view["result"]["peers"][0]}

    def call(self, operation, params=None, key=None):
        request = {"api_version": 1, "request_id": "composer-boundary:1",
                   "operation": operation, "params": params or {}}
        if key is not None:
            request["idempotency_key"] = key
        return json.loads(self.session.exchange(json.dumps(request).encode("utf-8") + b"\n"))

    def query(self, revision=None):
        params = {**self.scope, **({"send_revision": revision} if revision is not None else {})}
        reply = self.call("peer.composer_query", params)
        assert reply["ok"], reply
        return reply["result"]

    def update(self, current, text):
        return self.call("peer.composer_update", {**self.scope, "expected_revision": current["revision"],
                                                   "text": text}, current["update_key"])

    def save(self, text):
        reply = self.update(self.query(), text)
        assert reply["ok"], reply
        return reply["result"]["composer"]

    def send(self, revision):
        return self.call("message.enqueue_draft", {"profile": self.scope["profile"],
                         "recipient": self.scope["peer"], "draft_revision": revision}, revision)


@pytest.fixture
def composer_host(tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    monkeypatch.setattr(MeshChatService, "_prepare_lan_fallback", lambda *_: None)
    key = os.urandom(32)
    hosts = []
    clients = []

    def open_host():
        store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
        service = MeshChatService(store, tmp_path, lambda _: None)
        hosts.append(service)
        if store.get("profile", "local") is None:
            service.create_profile("Composer boundary")
            store.put("contact", "composer-peer", {"id": "composer-peer", "display_name": "Peer",
                      "trust": "approved", "destination_hash": "ab" * 16, "created_at": 1, "updated_at": 1})
        return service

    def client(service, caller="boundary-composer-caller"):
        opened = ComposerClient(service, caller)
        clients.append(opened)
        return opened

    try:
        yield open_host, client
    finally:
        for opened in clients:
            opened.session.close()
        for service in hosts:
            if not service._shutdown.is_set():
                service.close()


def records(store):
    return store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()


def test_public_composer_query_is_pure_and_does_not_import_host_legacy_text(composer_host):
    open_host, client = composer_host
    service = open_host()
    service.store.put("draft", "composer-peer", {"text": "Unowned legacy host draft"})
    opened = client(service)
    before = records(service.store)
    initial = opened.query()
    assert initial["revision"] is None and initial["text"] == ""
    assert initial["last_send"] is None and initial["send_lookup"] is None
    assert records(service.store) == before


def test_unchanged_update_consumes_ticket_and_late_replay_projects_current_composer(composer_host):
    open_host, client = composer_host
    opened = client(open_host())
    first = opened.save("Saved text")
    noop = opened.update(first, "Saved text")
    assert noop["ok"] and noop["result"]["changed"] is False, noop
    unchanged = noop["result"]["composer"]
    assert unchanged["revision"] == first["revision"]
    assert unchanged["update_key"] != first["update_key"]
    newer = opened.save("Newer text")
    replay = opened.update(first, "Saved text")
    assert replay["ok"], replay
    assert replay["result"]["applied_revision"] == first["revision"]
    assert replay["result"]["composer"] == newer
    conflict = opened.update(first, "Different payload")
    assert conflict["error"]["code"] == "idempotency_conflict", conflict


def test_lost_committed_send_reopens_and_old_replay_preserves_newer_draft(composer_host):
    open_host, client = composer_host
    service = open_host()
    first = client(service)
    draft = first.save("Committed before reply loss")
    # Discard the actual committed reply at the caller boundary, then reopen vault/service.
    accepted = first.send(draft["revision"])
    assert accepted["ok"], accepted
    first.session.close()
    service.close()
    reopened = open_host()
    second = client(reopened)
    lookup = second.query(draft["revision"])
    assert lookup["text"] == "" and lookup["send_lookup"]["status"] == "accepted"
    newer = second.save("Keep this newer draft")
    replay = second.send(draft["revision"])
    assert replay["ok"], replay
    assert replay["result"]["message"] == accepted["result"]["message"]
    assert replay["result"]["draft_disposition"] == "superseded"
    assert replay["result"]["composer"] == newer
    assert [item["text"] for item in reopened.store.list("message")] == ["Committed before reply loss"]


def test_deliberate_same_text_send_requires_new_revision_and_creates_one_additional_message(composer_host):
    open_host, client = composer_host
    service = open_host()
    opened = client(service)
    first = opened.save("Same deliberate text")
    assert opened.send(first["revision"])["ok"]
    second = opened.save("Same deliberate text")
    assert second["revision"] != first["revision"]
    assert opened.send(second["revision"])["ok"]
    assert opened.send(first["revision"])["ok"]
    assert len(service.store.list("message")) == 2


def test_foreign_caller_tokens_do_not_grant_composer_read_update_or_send(composer_host):
    open_host, client = composer_host
    service = open_host()
    owner = client(service)
    saved = owner.save("Caller private draft")
    stranger = client(service, "boundary-composer-stranger")
    assert stranger.query()["text"] == ""
    before = records(service.store)
    replies = [stranger.update(saved, "Attempted overwrite"), stranger.send(saved["revision"]),
               stranger.call("peer.composer_query", {**stranger.scope, "send_revision": saved["revision"]})]
    assert all(reply["ok"] is False and reply["error"]["code"] == "forbidden" for reply in replies), replies
    assert records(service.store) == before


@pytest.mark.parametrize("revocation", ["grant", "contact"])
def test_send_replay_rechecks_current_grant_and_contact_authority(composer_host, revocation):
    open_host, client = composer_host
    service = open_host()
    opened = client(service)
    saved = opened.save("Authorized before revocation")
    assert opened.send(saved["revision"])["ok"]
    if revocation == "grant":
        opened.grant = host_grant(opened.grant.caller, {"observe", "read"})
    else:
        service.block_contact("composer-peer")
    before = records(service.store)
    replay = opened.send(saved["revision"])
    assert replay["ok"] is False and replay["error"]["code"] == "forbidden", replay
    assert records(service.store) == before


@pytest.mark.parametrize("phase", ["seal", "after_write", "commit"])
def test_enqueue_draft_rolls_back_all_records_at_real_vault_fault_points(composer_host, monkeypatch, phase):
    open_host, client = composer_host
    service = open_host()
    opened = client(service)
    saved = opened.save("Atomic composer send")
    store = service.store
    before = records(store)
    with monkeypatch.context() as fault:
        if phase == "seal":
            fault.setattr(store, "_seal", lambda *_: (_ for _ in ()).throw(sqlite3.OperationalError("injected seal failure")))
        elif phase == "after_write":
            original = store._write_records_locked
            def fail_after_write(*args, **kwargs):
                original(*args, **kwargs)
                raise sqlite3.OperationalError("injected after-write failure")
            fault.setattr(store, "_write_records_locked", fail_after_write)
        else:
            database = store._db
            class CommitFailure:
                def __getattr__(self, name):
                    return getattr(database, name)
                def execute(self, sql, *args):
                    if sql == "COMMIT":
                        raise sqlite3.OperationalError("injected COMMIT failure")
                    return database.execute(sql, *args)
            fault.setattr(store, "_db", CommitFailure())
        denied = opened.send(saved["revision"])
        assert denied["ok"] is False, denied
        assert denied["error"]["code"] == "unavailable", denied
    assert records(store) == before
    assert opened.query() == saved
    assert opened.send(saved["revision"])["ok"]
    assert [item["text"] for item in store.list("message")] == ["Atomic composer send"]


def test_two_framed_clients_race_one_update_ticket_without_losing_input_identity(composer_host):
    open_host, client = composer_host
    service = open_host()
    first, second = client(service), client(service)
    current = first.query()
    assert second.query() == current
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(opened.update, current, text) for opened, text in
                   ((first, "First candidate"), (second, "Second candidate"))]
        outcomes = [future.result() for future in futures]
    assert sum(reply["ok"] is True for reply in outcomes) == 1, outcomes
    rejected = next(reply for reply in outcomes if not reply["ok"])
    assert rejected["error"]["code"] == "idempotency_conflict", rejected
    winner = next(reply["result"]["composer"] for reply in outcomes if reply["ok"])
    assert first.query() == second.query() == winner
