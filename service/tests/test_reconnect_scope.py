"""Signed reconnect documents with persisted state and isolated in-memory storage."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import time
import uuid

import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, IdentityMismatch
from mesh_chat.reconnect import (
    create_connection_capabilities,
    create_reconnect_answer,
    create_reconnect_offer,
    create_reconnect_request,
    verify_connection_capabilities,
    verify_reconnect_offer,
    verify_reconnect_request,
)
from mesh_chat.reconnect_service import ReconnectServiceMixin
from mesh_chat.workspace_reconnect import create_workspace_reconnect_capability
from mesh_chat.workspace_service import WorkspaceServiceMixin
from mesh_chat.workspace_wire import WorkspaceWirePayload

WORKSPACES = [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]
FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = f"v=0\r\na=fingerprint:{FINGERPRINT}\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"


class MemoryStore:
    def __init__(self):
        self.records = {}

    def get(self, kind, identifier):
        return deepcopy(self.records.get((kind, identifier)))

    def opaque_id(self, _kind, identifier):
        return identifier

    def put(self, kind, identifier, value):
        self.records[kind, identifier] = deepcopy(value)

    def delete(self, kind, identifier):
        self.records.pop((kind, identifier), None)

    def list(self, kind):
        return [deepcopy(value) for (stored_kind, _), value in self.records.items() if stored_kind == kind]

    def items(self, kind):
        return [(identifier, deepcopy(value)) for (stored_kind, identifier), value in self.records.items() if stored_kind == kind]


class Peer(ReconnectServiceMixin, WorkspaceServiceMixin):
    def __init__(self, device):
        self.device = device
        self.identity = RNS.Identity()
        self.destination = RNS.Destination.hash(self.identity, "lxmf", "delivery").hex()
        self.store = MemoryStore()
        self.store.put("profile", "local", {"destination_hash": self.destination})
        self.store.put("reconnect_device", "local", {"device_id": device})
        self._call_settings = SimpleNamespace(
            signal_mailbox_url="https://signal.example.test", turn_url=None,
            turn_broker_url=None, turn_broker_consent=False,
        )
        self.manifests = {}

    def _call_identity(self):
        return self.identity

    def _require_profile(self):
        return self.store.get("profile", "local")

    def _contact_by_destination(self, destination):
        return next((contact for contact in self.store.list("contact") if contact["destination_hash"] == destination), None)

    def _require_workspace(self, workspace_id):
        return self.store.get("workspace", workspace_id)

    def _workspace_current_manifest(self, workspace):
        return self.manifests[workspace["id"]]

    def _changed(self):
        pass

    def _workspace_changed(self, *_args, **_kwargs):
        pass

    def add_contact(self, other):
        self.store.put("contact", other.device, {
            "id": other.device, "destination_hash": other.destination,
            "display_name": other.device, "trust": "approved",
        })

    def add_workspace(self, other, workspace_id):
        self.store.put("workspace", workspace_id, {
            "id": workspace_id, "name": workspace_id, "state": "active",
            "local_member_id": self.device, "local_device_id": "workspace-" + self.device,
        })
        self.manifests[workspace_id] = SimpleNamespace(members=[
            SimpleNamespace(
                member_id=peer.device, status="active", display_name=peer.device,
                devices=[SimpleNamespace(
                    device_id="workspace-" + peer.device,
                    destination_hash=bytes.fromhex(peer.destination),
                )],
            ) for peer in (self, other)
        ])


def scope(other, workspace_id=None):
    return f"workspace:{workspace_id}:{other.device}:workspace-{other.device}" if workspace_id else other.device


def deliver_capability(sender, recipient, document, workspace_id=None):
    if workspace_id is None:
        return recipient.reconnect_capabilities_store(document)
    wrapped = create_workspace_reconnect_capability(
        sender.identity, workspace_id=workspace_id, manifest_digest="a" * 64,
        capability=document,
    )
    return recipient._receive_workspace_reconnect_capability(WorkspaceWirePayload(
        kind="workspace_reconnect_capability", logical_id=str(uuid.uuid4()),
        workspace_id=workspace_id, expires_at=int(time.time()) + 600, document=wrapped,
    ))


@pytest.fixture
def pair():
    alex, blair = Peer("dev-alex-0001"), Peer("dev-blair-0002")
    for local, other in ((alex, blair), (blair, alex)):
        local.add_contact(other)
        for workspace_id in WORKSPACES:
            local.add_workspace(other, workspace_id)
    return alex, blair


def enable_pair(alex, blair, workspace_id=None):
    left = alex.reconnect_consent_set(scope(blair, workspace_id), True, True)
    right = blair.reconnect_consent_set(scope(alex, workspace_id), True, True)
    deliver_capability(alex, blair, left["capabilities"], workspace_id)
    deliver_capability(blair, alex, right["capabilities"], workspace_id)
    return left, right


@pytest.mark.parametrize("workspace_id", [None, *WORKSPACES])
def test_verification_uses_selected_relationship_among_contact_and_workspaces(pair, workspace_id):
    alex, blair = pair
    left, right = enable_pair(alex, blair, workspace_id)
    left_id, right_id = left["profile"]["id"], right["profile"]["id"]
    request = alex.reconnect_request_create(scope(blair, workspace_id), uuid.uuid4().hex)
    with pytest.raises(IdentityMismatch, match="profile is required"):
        blair.verify_reconnect_request(request["document"])
    verified_request = blair.verify_reconnect_request(request["document"], right_id)
    assert verified_request["contact_id"] == scope(alex, workspace_id)
    assert verified_request["profile_id"] == right_id

    offer = blair.reconnect_offer_create(scope(alex, workspace_id), request["document"], SDP, FINGERPRINT)
    verified_offer = alex.verify_reconnect_offer(offer["document"], left_id)
    assert verified_offer["contact_id"] == scope(blair, workspace_id)
    assert verified_offer["profile_id"] == left_id
    answer = alex.reconnect_answer_create(scope(blair, workspace_id), offer["document"], SDP, FINGERPRINT)
    verified_answer = blair.verify_reconnect_answer(answer["document"], offer["document"], right_id)
    assert verified_answer["contact_id"] == scope(alex, workspace_id)
    assert verified_answer["profile_id"] == right_id
    assert blair.store.get("reconnect_profile", right_id)["state"] == "connecting"


def test_explicit_profile_rejects_other_signed_peer_for_every_document(pair):
    alex, blair = pair
    left, right = enable_pair(alex, blair, WORKSPACES[1])
    outsider = Peer("dev-outsider-0003")
    request = alex.reconnect_request_create(scope(blair, WORKSPACES[1]), uuid.uuid4().hex)
    offer = blair.reconnect_offer_create(scope(alex, WORKSPACES[1]), request["document"], SDP, FINGERPRINT)
    foreign_request = create_reconnect_request(
        outsider.identity, to_destination=blair.destination, device_id=outsider.device,
        attempt_id=uuid.uuid4().hex, nonce=uuid.uuid4().hex,
    )
    foreign_offer = create_reconnect_offer(
        outsider.identity, verify_reconnect_request(request["document"]), sdp=SDP, dtls_fingerprint=FINGERPRINT,
    )
    foreign_answer = create_reconnect_answer(
        outsider.identity, verify_reconnect_offer(offer["document"]), sdp=SDP, dtls_fingerprint=FINGERPRINT,
    )
    with pytest.raises(IdentityMismatch, match="another peer"):
        blair.verify_reconnect_request(foreign_request, right["profile"]["id"])
    with pytest.raises(IdentityMismatch, match="another peer"):
        alex.verify_reconnect_offer(foreign_offer, left["profile"]["id"])
    with pytest.raises(IdentityMismatch, match="another peer"):
        blair.verify_reconnect_answer(foreign_answer, offer["document"], right["profile"]["id"])


@pytest.mark.parametrize("workspace_id", [None, WORKSPACES[1]])
def test_explicit_profile_rechecks_current_contact_or_workspace_authority(pair, workspace_id):
    alex, blair = pair
    left, right = enable_pair(alex, blair, workspace_id)
    request = alex.reconnect_request_create(scope(blair, workspace_id), uuid.uuid4().hex)
    offer = blair.reconnect_offer_create(scope(alex, workspace_id), request["document"], SDP, FINGERPRINT)
    answer = alex.reconnect_answer_create(scope(blair, workspace_id), offer["document"], SDP, FINGERPRINT)
    for local, other in ((alex, blair), (blair, alex)):
        if workspace_id is None:
            contact = local.store.get("contact", other.device)
            contact["trust"] = "blocked"
            local.store.put("contact", other.device, contact)
        else:
            workspace = local.store.get("workspace", workspace_id)
            workspace["state"] = "removed"
            local.store.put("workspace", workspace_id, workspace)
    with pytest.raises(ContactNotApproved):
        blair.verify_reconnect_request(request["document"], right["profile"]["id"])
    with pytest.raises(ContactNotApproved):
        alex.verify_reconnect_offer(offer["document"], left["profile"]["id"])
    with pytest.raises(ContactNotApproved):
        blair.verify_reconnect_answer(answer["document"], offer["document"], right["profile"]["id"])


@pytest.mark.parametrize("workspace_id", [None, WORKSPACES[1]])
def test_delayed_capabilities_cannot_revert_same_second_rotation_or_consent(pair, workspace_id, monkeypatch):
    alex, blair = pair
    now = int(time.time())
    monkeypatch.setattr("mesh_chat.reconnect_service._now", lambda: now)
    left, right = enable_pair(alex, blair, workspace_id)
    old = verify_connection_capabilities(left["capabilities"])
    updated = alex.reconnect_consent_set(scope(blair, workspace_id), False, True)
    new = verify_connection_capabilities(updated["capabilities"])
    assert new.issued_at > old.issued_at
    assert new.mailbox_pair_token != old.mailbox_pair_token
    deliver_capability(alex, blair, updated["capabilities"], workspace_id)
    stored = blair.store.get("reconnect_profile", right["profile"]["id"])
    for document in (updated["capabilities"], left["capabilities"]):
        deliver_capability(alex, blair, document, workspace_id)
        assert blair.store.get("reconnect_profile", right["profile"]["id"]) == stored
    assert stored["remote_auto_reconnect"] is False
    assert stored["remote_mailbox_pair_token"] == new.mailbox_pair_token

    # An equal-time, differently signed legacy document cannot establish a
    # newer consent decision. Do not revert the already accepted document.
    conflict = create_connection_capabilities(
        alex.identity, peer_destination=blair.destination, device_id=alex.device,
        transports=["webrtc"], auto_reconnect=True, allow_direct_ip_disclosure=True,
        mailbox_url=old.mailbox_url, mailbox_pair_token=old.mailbox_pair_token,
        mailbox_expires_at=new.issued_at + 600, expires_at=new.issued_at + 1200, now=new.issued_at,
    )
    deliver_capability(alex, blair, conflict, workspace_id)
    assert blair.store.get("reconnect_profile", right["profile"]["id"]) == stored


def test_pending_capabilities_keep_newest_document_until_contact_arrives(pair, monkeypatch):
    alex, blair = pair
    now = int(time.time())
    monkeypatch.setattr("mesh_chat.reconnect_service._now", lambda: now)
    old = alex.reconnect_consent_set(blair.device, True, True)["capabilities"]
    newest = alex.reconnect_consent_set(blair.device, False, True)["capabilities"]
    blair.store.delete("contact", alex.device)
    assert blair.reconnect_capabilities_store(newest)["pending"]
    assert blair.reconnect_capabilities_store(old)["pending"]
    assert blair.store.get("reconnect_pending_capability", alex.destination)["document"] == newest
    blair.add_contact(alex)
    profiles = blair.reconnect_profiles()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["peer_auto_reconnect"] is False
    assert blair.store.get("reconnect_profile", profiles[0]["id"])["remote_capabilities"] == newest


def test_delayed_capability_after_contact_request_preserves_newer_pending_consent(pair, monkeypatch):
    alex, blair = pair
    now = int(time.time())
    monkeypatch.setattr("mesh_chat.reconnect_service._now", lambda: now)
    old = alex.reconnect_consent_set(blair.device, True, True)["capabilities"]
    newest = alex.reconnect_consent_set(blair.device, False, True)["capabilities"]
    blair.store.delete("contact", alex.device)
    assert blair.reconnect_capabilities_store(newest)["pending"]

    # An inbound LXMF contact request creates this row before approval, which
    # is when the service normally promotes pre-contact capabilities.
    blair.add_contact(alex)
    contact = blair.store.get("contact", alex.device)
    contact["trust"] = "pending_request"
    blair.store.put("contact", alex.device, contact)
    result = blair.reconnect_capabilities_store(old)

    stored = blair.store.get("reconnect_profile", result["profile"]["id"])
    assert stored["remote_capabilities"] == newest
    assert stored["remote_auto_reconnect"] is False
    assert blair.store.get("reconnect_pending_capability", alex.destination) is None
    assert blair.store.get("contact", alex.device)["trust"] == "pending_request"


@pytest.mark.parametrize("workspace_id", [None, *WORKSPACES])
def test_encrypted_capabilities_survive_long_outage_and_still_enforce_revocation(pair, workspace_id, monkeypatch):
    from mesh_chat.signal_crypto import seal, unseal
    alex, blair = pair
    left, right = enable_pair(alex, blair, workspace_id)
    left_id, right_id = left["profile"]["id"], right["profile"]["id"]
    future = time.time() + 45 * 24 * 60 * 60
    monkeypatch.setattr(time, "time", lambda: future)
    a = alex._reconnect_profile(left_id)
    b = blair._reconnect_profile(right_id)
    assert alex._reconnect_profile_public(a)["effective"]["ready"]
    assert blair._reconnect_profile_public(b)["effective"]["ready"]
    am, bm = alex._profile_mailbox(a), blair._profile_mailbox(b)
    assert am["secret"] == bm["secret"]
    assert am["secret"] != am["token"]
    request = alex.reconnect_request_create(scope(blair, workspace_id), uuid.uuid4().hex)
    encrypted = seal(request["document"], am["secret"], am["session"], "request")
    received = unseal(encrypted, bm["secret"], bm["session"], "request")
    assert blair.verify_reconnect_request(received, right_id)["contact_id"] == scope(alex, workspace_id)
    if workspace_id:
        alex.manifests[workspace_id].members[1].status = "removed"
    else:
        contact = alex.store.get("contact", blair.device)
        contact["trust"] = "blocked"
        alex.store.put("contact", blair.device, contact)
    with pytest.raises((ContactNotApproved, IdentityMismatch)):
        alex.reconnect_request_create(scope(blair, workspace_id), uuid.uuid4().hex)


def test_workspace_protocol_upgrade_retries_delivery_without_changing_consent(pair, monkeypatch):
    from mesh_chat.workspace_reconnect import verify_workspace_reconnect_capability

    alex, blair = pair
    workspace_id = WORKSPACES[0]
    left, _ = enable_pair(alex, blair, workspace_id)
    profile_id = left["profile"]["id"]
    profile = alex.store.get("reconnect_profile", profile_id)
    profile["local_capabilities_version"] = 1
    profile["local_capabilities_persistent"] = False
    profile.pop("mailbox_secret")
    alex.store.put("reconnect_profile", profile_id, profile)
    workspace = alex.store.get("workspace", workspace_id)
    workspace["manifest_hash"] = "a" * 64
    alex.store.put("workspace", workspace_id, workspace)
    remote_device = alex.manifests[workspace_id].members[1].devices[0]
    remote_device.display_name = "Peer"
    remote_device.public_identity = blair.identity.get_public_key()
    remote_device.hints = []
    monkeypatch.setattr(alex, "_due_records", lambda **kwargs: [])
    commits = []

    def put_many(records):
        commits.append(records)
        if len(commits) == 1:
            raise RuntimeError("Synthetic transient queue failure")
        for record in records:
            alex.store.put(*record)

    monkeypatch.setattr(alex.store, "put_many", put_many, raising=False)
    alex.reconnect_profiles()
    upgraded = alex.store.get("reconnect_profile", profile_id)
    assert upgraded["local_capabilities_version"] == 3
    assert upgraded["auto_reconnect"] == profile["auto_reconnect"]
    assert upgraded["allow_direct_ip_disclosure"] == profile["allow_direct_ip_disclosure"]
    assert upgraded["capability_delivery_pending"] is True
    assert upgraded["mailbox_pair_token"] != profile["mailbox_pair_token"]
    alex.reconnect_profiles()
    assert alex.store.get("reconnect_profile", profile_id)["capability_delivery_pending"] is False
    deliveries = alex.store.list("workspace_delivery")
    assert len(deliveries) == 1
    wrapper = verify_workspace_reconnect_capability(deliveries[0]["document"])
    assert wrapper.workspace_id == workspace_id
    assert wrapper.expires_at == 0
    assert wrapper.capability == upgraded["local_capabilities"]
    alex.reconnect_profiles()
    assert len(commits) == 2
