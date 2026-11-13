"""Prepared reaction rows over real vaults/signed groups; not transport proof.

The tiny parent below composes the receipt transaction only. Core caller grants
and envelope key policy remain A's adapter integration responsibility.
"""
from copy import deepcopy
from uuid import uuid4

import pytest

from mesh_chat.errors import ContactNotApproved, ValidationError
from mesh_chat.service import MeshChatService
from mesh_chat.vault import RecordConflict, VaultStore
from test_group_service import _joined_pair


@pytest.fixture(params=["direct", "group"])
def reaction(request, tmp_path, monkeypatch):
    monkeypatch.setattr(MeshChatService, "_retry_loop", lambda _: None)
    monkeypatch.setattr(MeshChatService, "_native_webrtc_event_loop", lambda _: None)
    pair = _joined_pair(tmp_path)
    service = pair.owner
    service._shutdown.clear()
    message = service.send_message("bailey", "Target") if request.param == "direct" else service.send_group_message(pair.group_id, "Target")
    pair.owner_network.sent.clear()
    pair.owner_network.cancelled.clear()
    yield service, pair, request.param, message["id"]
    pair.close()


def prepare(reaction, emoji="👍", active=True, operation_id=None):
    service, _, scope, message = reaction
    return service.prepare_message_reaction(scope, message, emoji, active, operation_id or str(uuid4()))


def commit(service, prepared):
    service.validate_message_reaction(**prepared.result)
    cached = service.store.operation_result(prepared.operation_id, prepared.input_fingerprint)
    if cached is not None:
        return cached
    identifier = service.store.opaque_id("workspace-operation", prepared.operation_id)
    receipt = {"id": prepared.operation_id, "input_digest": prepared.input_fingerprint, "outcome": prepared.result, "created_at": 1}
    service.store.conditional_put_and_delete({**prepared.expected, ("workspace_operation", identifier): None},
        [*prepared.records, ("workspace_operation", identifier, receipt)], prepared.deletions)
    return prepared.result


def rows(service):
    return service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()


def test_preparation_neither_writes_nor_queues_attempts_and_has_stable_ids(reaction, monkeypatch):
    service, pair, _, _ = reaction
    before, queue = rows(service), (service._direct_retry_snapshot(), service._group_retry_snapshot())
    for name in ("put", "put_many", "put_and_delete", "conditional_put_and_delete", "commit_operation", "delete"):
        monkeypatch.setattr(service.store, name, lambda *a, **k: pytest.fail("Preparation wrote the vault"))
    for name in ("_attempt", "_attempt_group_delivery", "_queue_group_retry", "_changed"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("Preparation activated work"))
    operation = str(uuid4())
    first, again = prepare(reaction, operation_id=operation), prepare(reaction, operation_id=operation)
    assert first.input_fingerprint == again.input_fingerprint
    assert [(kind, identifier) for kind, identifier, _ in first.records] == [(kind, identifier) for kind, identifier, _ in again.records]
    assert rows(service) == before
    assert (service._direct_retry_snapshot(), service._group_retry_snapshot()) == queue
    assert pair.owner_network.sent == pair.owner_network.cancelled == []


def test_parent_receipt_is_visible_before_delivery_and_noop_consumes_a_key(reaction, monkeypatch):
    service, pair, _, _ = reaction
    prepared = prepare(reaction)
    attempts = []
    def observe(identifier):
        assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
        attempts.append(identifier)
    monkeypatch.setattr(service, "_attempt", observe)
    monkeypatch.setattr(service, "_attempt_group_delivery", observe)
    commit(service, prepared)
    assert attempts == []
    service.finish_prepared_message_reaction(prepared)
    assert attempts == list(prepared.direct_ids + prepared.group_ids)
    noop = prepare(reaction)
    assert noop.records == noop.deletions == ()
    assert noop.direct_ids == noop.group_ids == ()
    commit(service, noop)
    service.finish_prepared_message_reaction(noop)
    assert len(service.store.list("workspace_operation")) == 2
    opposite = prepare(reaction, active=False, operation_id=noop.operation_id)
    with pytest.raises(ValidationError, match="different input"):
        commit(service, opposite)
    assert pair.owner_network.sent == []


@pytest.mark.parametrize("failure", ["first_write", "commit"])
def test_failed_parent_transaction_rolls_back_reaction_outbox_and_receipt(reaction, monkeypatch, failure):
    service, pair, _, _ = reaction
    prepared, before = prepare(reaction), rows(service)
    if failure == "first_write":
        original = service.store._write_records_locked
        def fail(records, deletions):
            original(list(records)[:1], ())
            raise OSError("injected first-write failure")
        monkeypatch.setattr(service.store, "_write_records_locked", fail)
    else:
        class FailCommit:
            def __init__(self, db): self.db = db
            def execute(self, sql, *args):
                if sql == "COMMIT": raise OSError("injected COMMIT failure")
                return self.db.execute(sql, *args)
            def __getattr__(self, name): return getattr(self.db, name)
        monkeypatch.setattr(service.store, "_db", FailCommit(service.store._db))
    with pytest.raises(OSError, match="injected"):
        commit(service, prepared)
    assert rows(service) == before
    assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) is None
    assert pair.owner_network.sent == pair.owner_network.cancelled == []


def test_lost_commit_return_reopens_receipt_without_second_work(reaction, monkeypatch, tmp_path):
    service, _, scope, _ = reaction
    prepared = prepare(reaction)
    original = service.store.conditional_put_and_delete
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("lost committed return")
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lost)
    with pytest.raises(OSError, match="lost committed"):
        commit(service, prepared)
    assert commit(service, prepared) == prepared.result
    stored_ids = [identifier for kind, identifier, _ in prepared.records if kind != "reaction"]
    key = service.store._key
    service.close()
    with VaultStore(tmp_path / "owner", key, allow_unprotected_for_tests=True) as reopened:
        assert reopened.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
        assert len(reopened.list("reaction")) == 1
        assert all(reopened.get("message" if scope == "direct" else "group_delivery", identifier) for identifier in stored_ids)


@pytest.mark.parametrize("change", ["authority", "revision", "delete"])
def test_changed_target_or_authority_rejects_stale_prepare(reaction, change):
    service, _, scope, message = reaction
    prepared = prepare(reaction)
    if change == "authority":
        kind, identifier = ("contact", "bailey") if scope == "direct" else ("group", reaction[1].group_id)
        value = service.store.get(kind, identifier)
        value["trust" if scope == "direct" else "status"] = "blocked" if scope == "direct" else "closed"
        service.store.put(kind, identifier, value)
        with pytest.raises((ContactNotApproved, ValidationError)):
            commit(service, prepared)
    elif change == "revision":
        commit(service, prepare(reaction, emoji="❤️"))
        with pytest.raises(RecordConflict): commit(service, prepared)
    else:
        service.store.delete("message" if scope == "direct" else "group_message", message)
        with pytest.raises(ValidationError): commit(service, prepared)
    assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) is None


def test_late_old_replay_and_finish_cannot_restore_or_forward_old_reaction(reaction):
    service, pair, _, _ = reaction
    old = prepare(reaction)
    commit(service, old)
    newer = prepare(reaction, emoji="❤️")
    commit(service, newer)
    before = rows(service)
    assert commit(service, old) == old.result
    service.finish_prepared_message_reaction(old)
    assert rows(service) == before
    assert pair.owner_network.sent == pair.owner_network.cancelled == []


def test_postcommit_attempt_or_event_failure_cannot_undo_accepted_rows(reaction, monkeypatch):
    service, _, _, _ = reaction
    prepared = prepare(reaction)
    commit(service, prepared)
    def fail(*args): raise OSError("injected postcommit effect failure")
    monkeypatch.setattr(service, "_attempt", fail)
    monkeypatch.setattr(service, "_attempt_group_delivery", fail)
    monkeypatch.setattr(service, "_changed", fail)
    service.finish_prepared_message_reaction(prepared)
    assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
    assert all(service.store.get(kind, identifier) == value for kind, identifier, value in prepared.records)


@pytest.mark.parametrize("locked", [True, False])
def test_current_identity_is_required_even_for_noop_or_receipt_replay(reaction, locked):
    service, _, _, _ = reaction
    prepared = prepare(reaction)
    commit(service, prepared)
    if locked: service._identity = None
    else: service._shutdown.set()
    with pytest.raises(ValidationError, match="unavailable"):
        commit(service, prepared)
