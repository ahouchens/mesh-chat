"""Real-vault inbox preparation; adoption/join composition remains a parent port.

These tests do not replace a Core adapter or claim packaged native delivery.
"""
from copy import deepcopy
import time
from uuid import uuid4

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import create_invitation
from mesh_chat.vault import RecordConflict, VaultStore
from test_contact_invitations import inbox


def prepare(inbox, operation=None):
    service, document, peer, _ = inbox
    return service.prepare_contact_invitation_receive(document, peer, None, operation or str(uuid4()))


def commit(service, prepared):
    # Deliberately cannot finalize an acceptance without C/A's adoption rows.
    if prepared.requires_adoption:
        raise ValidationError("Prepared adoption and join composition is required")
    cached = service.store.operation_result(prepared.operation_id, prepared.input_fingerprint)
    if cached is not None:
        return cached
    identifier = service.store.opaque_id("workspace-operation", prepared.operation_id)
    receipt = {"id": prepared.operation_id, "input_digest": prepared.input_fingerprint, "outcome": prepared.result, "created_at": 1}
    service.store.conditional_put_and_delete({**prepared.expected, ("workspace_operation", identifier): None},
        [*prepared.records, ("workspace_operation", identifier, receipt)], prepared.deletions,
        expected_collections=prepared.expected_collections)
    return prepared.result


def rows(service):
    return service.store._db.execute("SELECT kind,record_id,sealed FROM records ORDER BY kind,record_id").fetchall()


def test_receive_preparation_is_pure_digest_bound_and_does_not_accept(inbox, monkeypatch):
    service, document, peer, _ = inbox
    before = rows(service)
    for name in ("put", "delete", "put_many", "put_and_delete", "commit_operation", "conditional_put_and_delete"):
        monkeypatch.setattr(service.store, name, lambda *a, **k: pytest.fail("Preparation wrote the vault"))
    for name in ("_changed", "accept_invitation", "submit_workspace_join", "native_webrtc_control"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("Preparation invoked a side effect"))
    first, again = prepare(inbox), prepare(inbox)
    assert first.result["id"] == again.result["id"]
    assert first.input_fingerprint == again.input_fingerprint
    assert first.records[0][2]["document"] == document
    assert first.peer_destination == peer
    assert rows(service) == before
    assert service.store.list("contact") == service.store.list("message") == []


def test_receive_receipt_and_pending_inbox_commit_together_and_dedupe_is_a_noop(inbox):
    service, *_ = inbox
    first = prepare(inbox)
    commit(service, first)
    again = prepare(inbox)
    assert again.result["id"] == first.result["id"]
    assert again.records == again.deletions == ()
    commit(service, again)
    assert len(service.store.list("contact_invitation")) == 1
    assert len(service.store.list("workspace_operation")) == 2
    assert service.store.list("contact") == service.store.list("message") == []


def test_full_inbox_does_not_prune_expired_rows_before_rejecting(inbox):
    service, *_ = inbox
    template = prepare(inbox).records[0][2]
    for index in range(32):
        record = {**deepcopy(template), "id": str(uuid4())}
        service.store.put("contact_invitation", record["id"], record)
    expired = {**deepcopy(template), "id": str(uuid4()), "expires_at": time.time() - 1}
    service.store.put("contact_invitation", expired["id"], expired)
    before = rows(service)
    with pytest.raises(ValidationError, match="full"):
        prepare(inbox)
    assert rows(service) == before


def test_expiry_prune_is_staged_and_capacity_phantoms_reject_old_plan(inbox):
    service, *_ = inbox
    template = prepare(inbox).records[0][2]
    expired = {**deepcopy(template), "id": str(uuid4()), "expires_at": time.time() - 1}
    service.store.put("contact_invitation", expired["id"], expired)
    prepared = prepare(inbox)
    assert ("contact_invitation", expired["id"]) in prepared.deletions
    assert service.store.get("contact_invitation", expired["id"]) == expired
    phantom = {**deepcopy(template), "id": str(uuid4())}
    service.store.put("contact_invitation", phantom["id"], phantom)
    with pytest.raises(RecordConflict): commit(service, prepared)
    assert service.store.get("contact_invitation", expired["id"]) == expired
    assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) is None


@pytest.mark.parametrize("failure", ["first_write", "commit"])
def test_receive_transaction_failure_rolls_back_digest_expiry_and_receipt(inbox, monkeypatch, failure):
    service, *_ = inbox
    expired = {**deepcopy(prepare(inbox).records[0][2]), "id": str(uuid4()), "expires_at": time.time() - 1}
    service.store.put("contact_invitation", expired["id"], expired)
    prepared, before = prepare(inbox), rows(service)
    assert ("contact_invitation", expired["id"]) in prepared.deletions
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
    assert service.store.list("contact_invitation") == [expired]
    assert service.store.list("workspace_operation") == []


def test_lost_receive_commit_return_recovers_receipt_after_real_reopen(inbox, monkeypatch, tmp_path):
    service, _, _, key = inbox
    prepared = prepare(inbox)
    original = service.store.conditional_put_and_delete
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("lost committed return")
    monkeypatch.setattr(service.store, "conditional_put_and_delete", lost)
    with pytest.raises(OSError, match="lost committed"):
        commit(service, prepared)
    assert commit(service, prepared) == prepared.result
    service.close()
    with VaultStore(tmp_path, key, allow_unprotected_for_tests=True) as reopened:
        assert reopened.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
        assert len(reopened.list("contact_invitation")) == 1
        assert reopened.list("contact") == reopened.list("message") == []


def test_pending_acceptance_returns_adoption_requirements_without_accepting(inbox, monkeypatch):
    service, document, _, _ = inbox
    saved = service.receive_contact_invitation(document, inbox[2])
    before = rows(service)
    for name in ("accept_invitation", "submit_workspace_join", "_contact_capabilities", "native_webrtc_control", "_changed"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("Decision preparation activated adoption"))
    prepared = service.prepare_contact_invitation_decide(saved["id"], True, str(uuid4()))
    assert prepared.requires_adoption and prepared.personal_document == document
    assert prepared.records[0][2]["state"] == "accepted"
    assert "document" not in prepared.records[0][2]
    assert service.store.get("contact_invitation", saved["id"])["document"] == document
    assert rows(service) == before
    with pytest.raises(ValidationError, match="composition"):
        commit(service, prepared)


def test_workspace_acceptance_stages_original_join_document_and_stable_child_id(inbox, tmp_path):
    from test_workspace_service import _service, _op
    service, _, _, _ = inbox
    owner, _ = _service(tmp_path / "workspace-owner", RNS.Identity(), "Owner")
    try:
        workspace = owner.create_workspace(_op(9911), "Family")
        invitation = owner.create_workspace_invitation_command(workspace["id"], _op(9912), connection_mode="webrtc")
        document = owner.invitation(connection_mode="webrtc")["file"]
        saved = service.receive_contact_invitation(document, owner._require_profile()["destination_hash"], invitation["value"])
        first = service.prepare_contact_invitation_decide(saved["id"], True, str(uuid4()))
        again = service.prepare_contact_invitation_decide(saved["id"], True, str(uuid4()))
        assert first.requires_adoption and first.workspace_document == invitation["value"]
        assert first.join_operation_id == again.join_operation_id
        assert service.store.list("contact") == service.store.list("workspace") == service.store.list("workspace_delivery") == []
    finally:
        owner.close()


def test_decline_is_atomic_notified_only_after_commit_and_noop_has_no_effects(inbox, monkeypatch):
    service, document, peer, _ = inbox
    saved = service.receive_contact_invitation(document, peer)
    prepared = service.prepare_contact_invitation_decide(saved["id"], False, str(uuid4()))
    notifications = []
    service._native_webrtc_peers["fixture-session"] = peer
    service._native_webrtc_live.add("fixture-session")
    def notify(*args):
        assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
        notifications.append(args)
    monkeypatch.setattr(service, "native_webrtc_control", notify)
    service.finish_prepared_contact_invitation_decide(prepared)
    assert notifications == []
    commit(service, prepared)
    service.finish_prepared_contact_invitation_decide(prepared)
    assert len(notifications) == 1
    assert "invitation_declined" in notifications[0][2]
    noop = service.prepare_contact_invitation_decide(saved["id"], False, str(uuid4()))
    assert noop.records == ()
    commit(service, noop)
    service.finish_prepared_contact_invitation_decide(noop)
    assert len(notifications) == 1
    assert service.store.list("contact") == service.store.list("message") == []


def test_decision_readset_prevents_overwriting_newer_review(inbox):
    service, document, peer, _ = inbox
    saved = service.receive_contact_invitation(document, peer)
    older = service.prepare_contact_invitation_decide(saved["id"], False, str(uuid4()))
    service.decide_contact_invitation(saved["id"], False)
    with pytest.raises(RecordConflict): commit(service, older)
    assert service.store.operation_result(older.operation_id, older.input_fingerprint) is None


def test_postcommit_notification_failure_leaves_decision_and_receipt_durable(inbox, monkeypatch):
    service, document, peer, _ = inbox
    saved = service.receive_contact_invitation(document, peer)
    prepared = service.prepare_contact_invitation_decide(saved["id"], False, str(uuid4()))
    commit(service, prepared)
    service._native_webrtc_peers["fixture-session"] = peer
    service._native_webrtc_live.add("fixture-session")
    def fail(*args): raise OSError("injected notification failure")
    monkeypatch.setattr(service, "native_webrtc_control", fail)
    monkeypatch.setattr(service, "_changed", fail)
    service.finish_prepared_contact_invitation_decide(prepared)
    assert service.store.operation_result(prepared.operation_id, prepared.input_fingerprint) == prepared.result
    assert service.store.get("contact_invitation", saved["id"])["state"] == "declined"


@pytest.mark.parametrize("change", ["expired", "blocked", "locked", "closed"])
def test_replay_authority_checks_current_expiry_trust_and_identity(inbox, change):
    service, document, peer, _ = inbox
    saved = service.receive_contact_invitation(document, peer)
    if change == "expired":
        record = service.store.get("contact_invitation", saved["id"])
        record["expires_at"] = time.time() - 1
        service.store.put("contact_invitation", saved["id"], record)
    elif change == "blocked":
        contact = service.accept_invitation(document)
        contact["trust"] = "blocked"
        service.store.put("contact", contact["id"], contact)
    elif change == "locked": service._identity = None
    else: service._shutdown.set()
    with pytest.raises(ValidationError):
        service.validate_contact_invitation_decide(saved["id"], True)


def test_strict_input_fingerprint_rejects_same_key_with_a_different_invitation(inbox):
    service, *_ = inbox
    original = prepare(inbox)
    commit(service, original)
    peer = RNS.Identity()
    document = create_invitation(peer, "Another peer")["file"]
    changed = service.prepare_contact_invitation_receive(document, RNS.Destination.hash(peer, "lxmf", "delivery").hex(), None, original.operation_id)
    with pytest.raises(ValidationError, match="different input"):
        commit(service, changed)


def test_opposite_decisions_share_no_fingerprint_and_cannot_reuse_receipt_key(inbox):
    service, document, peer, _ = inbox
    saved = service.receive_contact_invitation(document, peer)
    operation = str(uuid4())
    declined = service.prepare_contact_invitation_decide(saved["id"], False, operation)
    accepted = service.prepare_contact_invitation_decide(saved["id"], True, operation)
    assert accepted.input_fingerprint != declined.input_fingerprint
    commit(service, declined)
    with pytest.raises(ValidationError, match="different input"):
        service.store.operation_result(operation, accepted.input_fingerprint)
    assert service.store.get("contact_invitation", saved["id"])["state"] == "declined"
    assert service.store.list("contact") == service.store.list("message") == []
