from __future__ import annotations

import base64
import json
import os
import time

import pytest
import RNS

from mesh_chat.errors import IdentityMismatch, ValidationError
from mesh_chat.invitations import create_invitation, readable_fingerprint
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@pytest.fixture
def inbox(tmp_path):
    key = os.urandom(32)
    store = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()  # Drive this test synchronously, without network I/O.
    identity = RNS.Identity()
    service._identity = identity
    store.put("profile", "local", {
        "display_name": "Local", "destination_hash": RNS.Destination.hash(identity, "lxmf", "delivery").hex(),
        "public_identity": base64.urlsafe_b64encode(identity.get_public_key()).decode(),
        "identity_hash": identity.hash.hex(), "fingerprint": readable_fingerprint(identity.get_public_key()),
        "created_at": time.time(),
    })
    peer = RNS.Identity()
    document = create_invitation(peer, "Taylor")["file"]
    destination = RNS.Destination.hash(peer, "lxmf", "delivery").hex()
    yield service, document, destination, key
    service.close()


def test_native_receipt_survives_reopen_without_a_renderer_or_accepting(inbox, tmp_path):
    service, document, destination, key = inbox
    service._native_webrtc_live.add("phone")
    service._native_webrtc_peers["phone"] = destination
    text = json.dumps({"type": "contact_invitation", "document": document})
    encoded = base64.b64encode(text.encode()).decode()
    service._handle_native_webrtc_event("control", "phone", "mesh-onboarding:" + encoded)
    saved = service.snapshot()["contact_invitations"]
    assert len(saved) == 1
    assert saved[0]["preview"]["display_name"] == "Taylor"
    assert "document" not in saved[0]
    assert service.store.list("contact") == []
    assert service.store.list("message") == []
    service.close()
    reopened = VaultStore(tmp_path, key, allow_unprotected_for_tests=True)
    try:
        recovered = reopened.get("contact_invitation", saved[0]["id"])
        assert recovered["state"] == "pending"
        assert recovered["document"] == document
    finally:
        reopened.close()


def test_accept_offline_queues_one_request_and_replay_does_not_reopen(inbox):
    service, document, destination, _ = inbox
    saved = service.receive_contact_invitation(document, destination)
    accepted = service._execute("decide_contact_invitation", {"invitation_id": saved["id"], "accept": True})
    assert accepted["trust"] == "awaiting_consent"
    assert len(service.store.list("message")) == 1
    assert service.contact_invitations() == []
    assert service.receive_contact_invitation(document, destination)["state"] == "accepted"
    retried = service.decide_contact_invitation(saved["id"], True)
    assert retried["id"] == accepted["id"]
    assert len(service.store.list("message")) == 1
    assert "document" not in service.store.get("contact_invitation", saved["id"])


def test_decline_is_durable_and_never_creates_a_contact(inbox):
    service, document, destination, _ = inbox
    saved = service.receive_contact_invitation(document, destination)
    assert service.receive_contact_invitation(document, destination)["id"] == saved["id"]
    service.decide_contact_invitation(saved["id"], False)
    assert service.receive_contact_invitation(document, destination)["state"] == "declined"
    assert service.contact_invitations() == []
    assert service.store.list("contact") == []
    with pytest.raises(ValidationError):
        service.decide_contact_invitation(saved["id"], True)


def test_wrong_peer_and_invalid_invitation_never_enter_inbox(inbox):
    service, document, destination, _ = inbox
    with pytest.raises(IdentityMismatch):
        service.receive_contact_invitation(document, "00" * 16)
    with pytest.raises(ValidationError):
        service.receive_contact_invitation("not signed", destination)
    assert service.contact_invitations() == []


def test_expired_invitation_can_be_dismissed_but_not_accepted(inbox):
    service, document, destination, _ = inbox
    saved = service.receive_contact_invitation(document, destination)
    record = service.store.get("contact_invitation", saved["id"])
    record["expires_at"] = time.time() - 1
    service.store.put("contact_invitation", saved["id"], record)
    assert service.contact_invitations()[0]["expired"] is True
    with pytest.raises(ValidationError, match="expired"):
        service.decide_contact_invitation(saved["id"], True)
    assert service.store.list("contact") == []
    service.decide_contact_invitation(saved["id"], False)
    assert service.contact_invitations() == []


def test_saved_workspace_invitation_joins_only_after_explicit_acceptance(inbox, tmp_path):
    from test_workspace_service import _service, _op

    service, _, _, _ = inbox
    owner, _ = _service(tmp_path / "owner", RNS.Identity(), "Owner")
    try:
        workspace = owner.create_workspace(_op(9901), "Family")
        workspace_invite = owner.create_workspace_invitation_command(workspace["id"], _op(9902), connection_mode="webrtc")
        peer = owner._require_profile()["destination_hash"]
        service._native_webrtc_live.add("owner")
        service._native_webrtc_peers["owner"] = peer
        service._native_control_receive("owner", "mesh-onboarding", json.dumps({
            "type": "contact_invitation", "document": owner.invitation(connection_mode="webrtc")["file"],
            "workspace_document": workspace_invite["value"],
        }))
        saved = service.contact_invitations()[0]
        assert saved["workspace"]["name"] == "Family"
        assert service.store.list("workspace") == []
        service.decide_contact_invitation(saved["id"], True)
        assert len(service.store.list("workspace")) == 1
        assert service.contact_invitations() == []
        service.decide_contact_invitation(saved["id"], True)
        assert len(service.store.list("workspace")) == 1
    finally:
        owner.close()
