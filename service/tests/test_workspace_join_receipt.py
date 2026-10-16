from __future__ import annotations

import json
import os
import time
import uuid

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.models import DeliveryState
from mesh_chat.workspace_join_receipt import create_workspace_join_receipt, verify_workspace_join_receipt
from mesh_chat.workspace_protocol import verify_workspace_join, verify_workspace_invitation
from mesh_chat.workspace_wire import parse_workspace_payload
from test_workspace_service import _deliver, _flush, _native, _op, _service


@pytest.fixture
def pair(tmp_path):
    owner_identity, joiner_identity = RNS.Identity(), RNS.Identity()
    key = os.urandom(32)
    owner, onet = _service(tmp_path / "owner", owner_identity, "Owner")
    joiner, jnet = _service(tmp_path / "joiner", joiner_identity, "Joiner", vault_key=key)
    workspace = owner.create_workspace(_op(61000), "Receipt", "")
    invitation = owner.create_workspace_invitation_command(workspace["id"], _op(61001))
    joiner.submit_workspace_join(invitation["text"], _op(61002))
    request = _flush(joiner, jnet)[0]
    yield owner, onet, joiner, jnet, workspace, request, key, joiner_identity
    owner.close()
    joiner.close()


def deliver(recipient, sender, message):
    _deliver(recipient, message, source_profile=sender._require_profile(), recipient_profile=recipient._require_profile())


def public(joiner):
    return joiner.workspace_snapshot()["workspaces"][0]


def test_receipt_requires_durable_owner_validation_and_survives_restart(pair, tmp_path):
    owner, onet, joiner, _jnet, workspace, request, key, identity = pair
    before = public(joiner)
    assert before["join_acknowledged"] is False
    joiner._on_workspace_native_status(request["logical_id"], DeliveryState.RECEIVED_BY_ENDPOINT, None)
    assert public(joiner)["join_acknowledged"] is False
    assert public(joiner)["join_delivery_state"] == "received_by_endpoint"
    deliver(owner, joiner, request)
    assert len(owner.workspace_snapshot()["workspace_join_requests"]) == 1
    receipt = _flush(owner, onet)[0]
    wrong_source = _native(receipt, source=os.urandom(16), destination=bytes.fromhex(joiner._require_profile()["destination_hash"]))
    joiner._receive_workspace_payload(wrong_source, parse_workspace_payload(wrong_source))
    assert public(joiner)["join_acknowledged"] is False
    deliver(joiner, owner, receipt)
    assert public(joiner)["join_acknowledged"] is True
    assert public(joiner)["state"] == "joining"
    assert "join_receipt" not in public(joiner)
    assert "join_connection_invitation" not in public(joiner)
    original = joiner.store.get("workspace_delivery", request["logical_id"])["document"]
    joiner.close()
    restored, restored_network = _service(tmp_path / "joiner", identity, "Joiner", vault_key=key)
    try:
        assert public(restored)["join_acknowledged"] is True
        assert restored.store.get("workspace_delivery", request["logical_id"])["document"] == original
        deliver(restored, owner, receipt)
        assert _flush(restored, restored_network) == []
        owner.approve_workspace_join(workspace["id"], owner.workspace_snapshot()["workspace_join_requests"][0]["id"], _op(61003))
        for message in _flush(owner, onet):
            deliver(restored, owner, message)
        assert public(restored)["state"] == "active"
    finally:
        restored.close()


def test_receipt_and_request_commit_together_and_duplicate_is_bounded(pair, monkeypatch):
    owner, onet, joiner, _jnet, _workspace, request, *_ = pair
    put_many = owner.store.put_many
    def fail(records, *args, **kwargs):
        if any(kind == "workspace_join_request" for kind, *_ in records):
            assert any(kind == "workspace_delivery" and value["kind"] == "workspace_join_receipt" for kind, _id, value in records)
            raise OSError("simulated disk failure")
        return put_many(records, *args, **kwargs)
    monkeypatch.setattr(owner.store, "put_many", fail)
    # The application ingress suppresses failed inbound operations; no prompt
    # or outgoing receipt may survive the failed storage transaction.
    deliver(owner, joiner, request)
    assert owner.store.list("workspace_join_request") == []
    assert _flush(owner, onet) == []
    monkeypatch.setattr(owner.store, "put_many", put_many)
    deliver(owner, joiner, request)
    receipt = _flush(owner, onet)[0]
    for _ in range(10):
        deliver(owner, joiner, request)
    assert len(owner.store.list("workspace_join_request")) == 1
    assert len(owner.store.list("workspace_delivery")) == 1
    assert _flush(owner, onet) == []
    # A lost application receipt is recoverable after the minimum retry delay.
    owner._on_workspace_native_status(receipt["logical_id"], DeliveryState.RECEIVED_BY_ENDPOINT, None)
    record = owner.store.get("workspace_delivery", receipt["logical_id"])
    record["last_attempt_at"] = time.time() - 31
    owner.store.put("workspace_delivery", record["id"], record)
    deliver(owner, joiner, request)
    retry = _flush(owner, onet)[0]
    assert retry["logical_id"] == receipt["logical_id"]
    assert retry["fields"] == receipt["fields"]


@pytest.mark.parametrize("change", ["join_digest", "join_attempt_id", "workspace_id", "audience_device_id", "audience_destination", "authority_device_id", "v", "expires_at", "received_at", "extra"])
def test_receipt_rejects_wrong_binding_even_with_valid_authority_signature(pair, change):
    owner, _onet, joiner, _jnet, _workspace, request, *_ = pair
    stored = joiner.store.get("workspace_delivery", request["logical_id"])
    join = verify_workspace_join(stored["document"])
    receipt = create_workspace_join_receipt(owner._identity, join, stored["id"])
    value = json.loads(receipt)
    value[change] = {
        "join_digest": "0" * 64, "join_attempt_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()), "audience_device_id": str(uuid.uuid4()),
        "audience_destination": "0" * 32, "authority_device_id": str(uuid.uuid4()),
        "v": True, "expires_at": join.invitation.expires_at + 1,
        "received_at": int(time.time()) + 24 * 60 * 60 + 120, "extra": "ignored?",
    }[change]
    from mesh_chat.workspace_protocol import _sign
    value.pop("signature")
    altered = _sign(owner._identity, value)
    with pytest.raises(ValidationError):
        verify_workspace_join_receipt(altered, join, stored["id"])


def test_receipt_rejects_substituted_key_stale_and_noncanonical_documents(pair):
    owner, _onet, joiner, _jnet, _workspace, request, *_ = pair
    stored = joiner.store.get("workspace_delivery", request["logical_id"])
    join = verify_workspace_join(stored["document"])
    receipt = create_workspace_join_receipt(owner._identity, join, stored["id"])
    with pytest.raises(IdentityMismatch):
        create_workspace_join_receipt(RNS.Identity(), join, stored["id"])
    from mesh_chat.workspace_protocol import _sign
    value = json.loads(receipt)
    value.pop("signature")
    forged = _sign(RNS.Identity(), value)
    with pytest.raises(IdentityMismatch):
        verify_workspace_join_receipt(forged, join, stored["id"])
    for raw in (receipt + " ", "x" * 2049):
        with pytest.raises(ValidationError):
            verify_workspace_join_receipt(raw, join, stored["id"])
    with pytest.raises(ValidationError):
        verify_workspace_join_receipt(receipt, join, stored["id"], now=join.invitation.expires_at + 1)
    skewed = create_workspace_join_receipt(owner._identity, join, stored["id"], now=join.created_at - 10)
    verify_workspace_join_receipt(skewed, join, stored["id"], now=join.created_at)


def test_wrong_native_source_and_revoked_invitation_produce_no_receipt(pair):
    owner, onet, joiner, _jnet, workspace, request, *_ = pair
    native = _native(request, source=os.urandom(16), destination=bytes.fromhex(owner._require_profile()["destination_hash"]))
    owner._receive_workspace_payload(native, parse_workspace_payload(native))
    assert _flush(owner, onet) == []
    invitation = owner.store.list("workspace_invitation")[0]
    invitation["state"] = "revoked"
    owner.store.put("workspace_invitation", invitation["id"], invitation)
    deliver(owner, joiner, request)
    assert owner.store.list("workspace_join_request") == []
    assert _flush(owner, onet) == []


def test_unacknowledged_join_retries_same_bytes_after_endpoint_proof(pair):
    _owner, _onet, joiner, jnet, _workspace, request, *_ = pair
    joiner._on_workspace_native_status(request["logical_id"], DeliveryState.RECEIVED_BY_ENDPOINT, None)
    delivery = joiner.store.get("workspace_delivery", request["logical_id"])
    assert delivery["next_attempt_at"] > time.time()
    delivery["next_attempt_at"] = 0
    joiner.store.put_many([("workspace_delivery", delivery["id"], delivery), *joiner._due_records(add=[delivery])])
    retried = _flush(joiner, jnet)[0]
    assert retried["fields"] == request["fields"]
    assert retried["logical_id"] == request["logical_id"]
    assert public(joiner)["join_acknowledged"] is False


def test_upgrade_resumes_exact_pre_receipt_join_and_migrates_legacy_owner_request(pair):
    owner, onet, joiner, jnet, workspace, request, *_ = pair
    deliver(owner, joiner, request)
    pending = owner.store.list("workspace_join_request")[0]
    original_receipt = pending.pop("receipt_delivery_id")
    pending.pop("join_attempt_id")
    owner.store.delete("workspace_delivery", original_receipt)
    owner.store.put("workspace_join_request", pending["id"], pending)
    stored = joiner._require_workspace(workspace["id"])
    stored.pop("join_receipt_tracking")
    joiner.store.put("workspace", joiner._workspace_record_id(workspace["id"]), stored)
    delivery = joiner.store.get("workspace_delivery", request["logical_id"])
    delivery["state"] = DeliveryState.RECEIVED_BY_ENDPOINT.value
    joiner.store.put_many([
        ("workspace_delivery", delivery["id"], delivery),
        *joiner._due_records(remove=[delivery["id"]]),
    ])
    assert public(joiner)["join_acknowledged"] is False
    retry = _flush(joiner, jnet)[0]
    assert retry["fields"] == request["fields"]
    deliver(owner, joiner, retry)
    assert len(owner.store.list("workspace_join_request")) == 1
    receipt = _flush(owner, onet)[0]
    deliver(joiner, owner, receipt)
    assert public(joiner)["join_acknowledged"] is True


def test_join_is_committed_before_route_setup_and_failed_setup_is_restart_safe(tmp_path, monkeypatch):
    from mesh_chat.participant import create_access_document, create_email_invitation
    from mesh_chat.errors import NetworkUnavailable
    owner, _onet = _service(tmp_path / "route-owner", RNS.Identity(), "Owner")
    identity, key = RNS.Identity(), os.urandom(32)
    joiner, _jnet = _service(tmp_path / "route-joiner", identity, "Joiner", vault_key=key)
    try:
        workspace = owner.create_workspace(_op(62000), "Queued first", "")
        invite = owner.create_workspace_invitation_command(workspace["id"], _op(62001), connection_mode="nearby")
        access = create_access_document(
            owner._identity, [{"host": "93.184.216.34", "port": 4242, "path": "pcp"}],
            network_name="queue_first_network_name", passphrase="queue_first_passphrase_123456789",
            expires_at=int(time.time()) + 3600,
        )
        raw = create_email_invitation(owner._identity, "workspace", verify_workspace_invitation(invite["text"]).serialized, access)
        attempts = []
        def fail_setup(*args, **kwargs):
            saved = joiner.store.list("workspace_delivery")
            assert len(saved) == 1 and saved[0]["kind"] == "workspace_join"
            attempts.append(saved[0]["document"])
            raise NetworkUnavailable("simulated route loss")
        monkeypatch.setattr(joiner, "approve_participant_access", fail_setup)
        result = joiner.submit_workspace_join(raw, _op(62002))
        assert result["connection_setup_failed"] is True
        assert result["join_acknowledged"] is False
        assert len(attempts) == 1
        joiner.close()
        restored, network = _service(tmp_path / "route-joiner", identity, "Joiner", vault_key=key)
        try:
            restored_access = []
            monkeypatch.setattr(restored, "approve_participant_access", lambda *args, **kwargs: restored_access.append(args[0]) or {})
            _flush(restored, network)
            assert len(restored_access) == 1
            assert restored.store.list("workspace_delivery")[0]["document"] == attempts[0]
            assert "join_connection_invitation" not in restored._require_workspace(workspace["id"])
        finally:
            restored.close()
    finally:
        owner.close()
        joiner.close()
