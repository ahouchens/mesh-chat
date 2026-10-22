from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
import RNS

from mesh_chat.call_settings import CallSettings
from mesh_chat.errors import (
    ContactNotApproved,
    IdentityMismatch,
    ReconnectReplayed,
    ValidationError,
)
from mesh_chat.models import Contact, Profile, TrustState
from mesh_chat.reconnect import (
    create_connection_capabilities,
    create_reconnect_request,
    preferred_initiator,
    verify_connection_capabilities,
    verify_reconnect_offer,
)
from mesh_chat.reconnect_service import reconnect_session_id
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore

MAILBOX = "https://signal.example.workers.dev"
FINGERPRINT = "sha-256 " + ":".join(["AB"] * 32)
SDP = "\r\n".join(
    [
        "v=0",
        "o=- 1 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=fingerprint:" + FINGERPRINT,
        "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
        "a=mid:0",
        "a=sctp-port:5000",
    ]
) + "\r\n"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _destination(identity: RNS.Identity) -> str:
    return RNS.Destination.hash(identity, "lxmf", "delivery").hex()


def _service(
    root: Path,
    name: str,
    *,
    device_id: str,
    mailbox: str | None = MAILBOX,
) -> tuple[MeshChatService, RNS.Identity, str]:
    root.mkdir(parents=True, exist_ok=True)
    # A stable per-path vault key lets a test reopen the same profile and
    # replay cache, which is what "restart" means here.
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).digest()
    store = VaultStore(root, key, allow_unprotected_for_tests=True)
    store.put(
        "settings",
        "network",
        NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict(),
    )
    settings = CallSettings(signal_mailbox_url=mailbox)
    store.put("call_settings", "default", settings.to_dict())
    service = MeshChatService(store, root, lambda _event: None)
    service._shutdown.set()
    identity = RNS.Identity()
    destination = _destination(identity)
    store.put(
        "identity", "local", {"private_key": _b64(identity.get_private_key())}
    )
    store.put(
        "profile",
        "local",
        Profile(
            display_name=name,
            public_identity=_b64(identity.get_public_key()),
            identity_hash=identity.hash.hex(),
            destination_hash=destination,
            fingerprint="test",
            created_at=1,
        ).to_dict(),
    )
    store.put(
        "reconnect_device",
        "local",
        {"v": 1, "device_id": device_id, "created_at": 1},
    )
    service._identity = identity
    return service, identity, destination


def _add_contact(
    service: MeshChatService,
    contact_id: str,
    identity: RNS.Identity,
    destination: str,
    trust: TrustState = TrustState.APPROVED,
) -> dict[str, Any]:
    contact = Contact(
        id=contact_id,
        display_name=contact_id.title(),
        public_identity=_b64(identity.get_public_key()),
        identity_hash=identity.hash.hex(),
        destination_hash=destination,
        fingerprint="test",
        trust=trust,
        created_at=1,
        updated_at=1,
    ).to_dict()
    service.store.put("contact", contact_id, contact)
    return contact


class FakeMailbox:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], str] = {}
        self.published: list[dict[str, Any]] = []

    def publish(
        self,
        url: str,
        document: str,
        role: str,
        *,
        token: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        assert token, "reconnect publish must carry a capability token"
        assert session, "reconnect publish must carry a session"
        self.published.append({"url": url, "role": role, "token": token, "session": session})
        self.documents[(session, role)] = document
        return {
            "session_id": session,
            "role": role,
            "expires_in": 600,
            "rotated": False,
        }

    def fetch(
        self,
        url: str,
        session: str,
        role: str,
        *,
        token: str | None = None,
        pending: bool = False,
    ) -> dict[str, Any]:
        assert token, "reconnect fetch must carry a capability token"
        document = self.documents.get((session, role))
        if document is None:
            return {"session_id": session, "role": role, "document": None, "pending": True}
        return {"session_id": session, "role": role, "document": document}


@pytest.fixture()
def mailbox(monkeypatch: pytest.MonkeyPatch) -> FakeMailbox:
    fake = FakeMailbox()
    monkeypatch.setattr("mesh_chat.reconnect_service.publish_signal", fake.publish)
    monkeypatch.setattr("mesh_chat.reconnect_service.fetch_signal", fake.fetch)
    return fake


def _pair(
    root: Path,
    mailbox: str | None = MAILBOX,
    *,
    device_a: str = "dev-aaaa-0001",
    device_b: str = "dev-bbbb-0002",
) -> tuple[
    MeshChatService,
    str,
    MeshChatService,
    str,
]:
    alex, alex_identity, alex_destination = _service(
        root / "alex", "Alex", device_id=device_a, mailbox=mailbox
    )
    blair, blair_identity, blair_destination = _service(
        root / "blair", "Blair", device_id=device_b, mailbox=mailbox
    )
    _add_contact(alex, "contact-blair", blair_identity, blair_destination)
    _add_contact(blair, "contact-alex", alex_identity, alex_destination)
    return alex, "contact-blair", blair, "contact-alex"


def _exchange(alex: MeshChatService, blair: MeshChatService) -> None:
    alex_capabilities = alex.reconnect_capabilities_create("contact-blair")["capabilities"]
    blair_capabilities = blair.reconnect_capabilities_create("contact-alex")["capabilities"]
    blair.reconnect_capabilities_store(alex_capabilities)
    alex.reconnect_capabilities_store(blair_capabilities)


def _consent(alex: MeshChatService, blair: MeshChatService) -> None:
    alex.reconnect_consent_set("contact-blair", True, True)
    blair.reconnect_consent_set("contact-alex", True, True)
    alex_capabilities = alex.reconnect_capabilities_create("contact-blair")["capabilities"]
    blair_capabilities = blair.reconnect_capabilities_create("contact-alex")["capabilities"]
    blair.reconnect_capabilities_store(alex_capabilities)
    alex.reconnect_capabilities_store(blair_capabilities)
    # The peer's consent changed after the first store; store the newest signed
    # documents one more time so both profiles see reciprocal consent.
    blair.reconnect_capabilities_store(
        alex.reconnect_capabilities_create("contact-blair")["capabilities"]
    )
    alex.reconnect_capabilities_store(
        blair.reconnect_capabilities_create("contact-alex")["capabilities"]
    )


def test_capabilities_default_off_and_persist_without_exposing_token(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        _exchange(alex, blair)
        profiles = alex.reconnect_profiles()
        profile = profiles["profiles"][0]
        assert profile["auto_reconnect"] is False
        assert profile["peer_auto_reconnect"] is False
        assert profile["effective"]["ready"] is False
        assert "consent_missing" in profile["effective"]["reasons"]
        assert "peer_consent_missing" in profile["effective"]["reasons"]
        assert profile["effective"]["session"]
        assert "mailbox_pair_token" not in json.dumps(profiles)

        stored = alex.store.get("reconnect_profile", profile["id"])
        assert stored["remote_capabilities"]
        assert stored["mailbox_pair_token"]
        # A restart sees the same profile and token.
        alex.close()
        reopened, _, _ = _service(
            tmp_path / "alex", "Alex", device_id="dev-aaaa-0001"
        )
        assert reopened.reconnect_profiles()["profiles"][0]["has_peer_capabilities"]
        reopened.close()
    finally:
        blair.close()


def test_reciprocal_consent_is_required_in_both_directions(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, alex_id = _pair(tmp_path)
    try:
        _exchange(alex, blair)
        alex.reconnect_consent_set(blair_id, True, False)
        with pytest.raises(ContactNotApproved):
            alex.reconnect_request_create(blair_id, uuid.uuid4().hex)

        blair.reconnect_consent_set(alex_id, True, False)
        # The peer needs the newly signed consent document.
        with pytest.raises(ContactNotApproved):
            alex.reconnect_request_create(blair_id, uuid.uuid4().hex)
        alex.reconnect_capabilities_store(
            blair.reconnect_capabilities_create(alex_id)["capabilities"]
        )
        blair.reconnect_capabilities_store(
            alex.reconnect_capabilities_create(blair_id)["capabilities"]
        )
        created = alex.reconnect_request_create(blair_id, uuid.uuid4().hex)
        assert created["document"]
    finally:
        blair.close()


def test_blocked_or_deleted_peer_is_rejected_before_any_document(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, alex_id = _pair(tmp_path)
    try:
        _consent(alex, blair)
        request = alex.reconnect_request_create(blair_id, uuid.uuid4().hex)["document"]

        blair.store.put(
            "contact", alex_id, {**blair.store.get("contact", alex_id), "trust": "blocked"}
        )
        with pytest.raises(ContactNotApproved):
            blair.verify_reconnect_request(request)
        with pytest.raises(ContactNotApproved):
            blair.reconnect_offer_create(alex_id, request, SDP, FINGERPRINT)

        blair.store.delete("contact", alex_id)
        with pytest.raises(ContactNotApproved):
            blair.verify_reconnect_request(request)
        with pytest.raises((ContactNotApproved, ValidationError)):
            blair.reconnect_consent_set(alex_id, True, True)
    finally:
        blair.close()


def test_tampered_expired_and_foreign_documents_are_rejected(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, alex_id = _pair(tmp_path)
    try:
        _consent(alex, blair)
        document = alex.reconnect_request_create(blair_id, uuid.uuid4().hex)["document"]
        tampered = json.loads(document)
        tampered["attempt_id"] = "attempt-tampered-01"
        with pytest.raises((IdentityMismatch, ValidationError)):
            blair.verify_reconnect_request(json.dumps(tampered))

        old = create_reconnect_request(
            alex._call_identity(),
            to_destination=blair.store.get("profile", "local")["destination_hash"],
            device_id="dev-aaaa-0001",
            attempt_id=uuid.uuid4().hex,
            nonce=uuid.uuid4().hex,
            now=1_700_000_000,
            expires_at=1_700_000_300,
        )
        with pytest.raises(ValidationError):
            blair.verify_reconnect_request(old)

        stranger = RNS.Identity()
        foreign = create_reconnect_request(
            stranger,
            to_destination=blair.store.get("profile", "local")["destination_hash"],
            device_id="dev-cccc-0003",
            attempt_id=uuid.uuid4().hex,
            nonce=uuid.uuid4().hex,
        )
        with pytest.raises(ContactNotApproved):
            blair.verify_reconnect_request(foreign)

        other_device = create_reconnect_request(
            alex._call_identity(),
            to_destination="0" * 32,
            device_id="dev-aaaa-0001",
            attempt_id=uuid.uuid4().hex,
            nonce=uuid.uuid4().hex,
        )
        with pytest.raises(IdentityMismatch):
            blair.verify_reconnect_request(other_device)
    finally:
        blair.close()


def test_capabilities_reject_a_foreign_recipient_and_unsigned_token(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, _, blair, _ = _pair(tmp_path)
    try:
        stranger = RNS.Identity()
        wrong_recipient = create_connection_capabilities(
            stranger,
            peer_destination="1" * 32,
            device_id="dev-dddd-0004",
            transports=["webrtc"],
            auto_reconnect=True,
        )
        with pytest.raises((ContactNotApproved, IdentityMismatch)):
            alex.reconnect_capabilities_store(wrong_recipient)

        with pytest.raises(IdentityMismatch):
            alex.reconnect_capabilities_store(
                create_connection_capabilities(
                    blair._call_identity(),
                    peer_destination="2" * 32,
                    device_id="dev-bbbb-0002",
                    transports=["webrtc"],
                )
            )
    finally:
        blair.close()


def test_token_rotation_replaces_the_capability(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        first = alex.reconnect_consent_set(blair_id, True, False)
        first_token = verify_connection_capabilities(
            first["capabilities"]
        ).mailbox_pair_token
        second = alex.reconnect_consent_set(blair_id, True, False)
        assert second["changed"] is False
        rotated = alex.reconnect_capabilities_create(blair_id, True)["capabilities"]
        rotated_token = verify_connection_capabilities(rotated).mailbox_pair_token
        assert rotated_token != first_token
        assert second["capabilities"] == first["capabilities"]
    finally:
        blair.close()


def test_replay_survives_a_restart(tmp_path: Path, mailbox: FakeMailbox) -> None:
    alex, _, blair, _ = _pair(tmp_path)
    try:
        assert alex.reconnect_replay_check("attempt:abc12345", 600)["accepted"] is True
        assert alex.reconnect_replay_check("attempt:abc12345", 600)["accepted"] is False
        alex.close()
        restarted, _, _ = _service(
            tmp_path / "alex", "Alex", device_id="dev-aaaa-0001"
        )
        assert (
            restarted.reconnect_replay_check("attempt:abc12345", 600)["accepted"]
            is False
        )
        restarted.close()
    finally:
        blair.close()


def test_deterministic_initiator_for_both_orders(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, _, blair, _ = _pair(tmp_path, device_a="dev-aaaa-0001", device_b="dev-bbbb-0002")
    try:
        _exchange(alex, blair)
        assert alex.reconnect_profiles()["profiles"][0]["effective"]["preferred"] is True
        assert blair.reconnect_profiles()["profiles"][0]["effective"]["preferred"] is False
    finally:
        blair.close()

    swapped, _, other, _ = _pair(
        tmp_path / "swapped", device_a="dev-zzzz-9999", device_b="dev-bbbb-0002"
    )
    try:
        _exchange(swapped, other)
        assert swapped.reconnect_profiles()["profiles"][0]["effective"]["preferred"] is False
        assert preferred_initiator("dev-zzzz-9999", "dev-bbbb-0002") is False
    finally:
        other.close()


def test_full_request_offer_answer_pipeline(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, alex_id = _pair(tmp_path)
    try:
        _consent(alex, blair)
        alex_profile = alex.reconnect_profiles()["profiles"][0]
        blair_profile = blair.reconnect_profiles()["profiles"][0]
        assert alex_profile["effective"]["ready"] is True, alex_profile["effective"]
        assert blair_profile["effective"]["ready"] is True, blair_profile["effective"]
        assert alex_profile["effective"]["preferred"] is True

        attempt_id = uuid.uuid4().hex
        request = alex.reconnect_request_create(blair_id, attempt_id)
        alex.reconnect_publish(alex_profile["id"], request["document"], "request")
        fetched = blair.reconnect_fetch(blair_profile["id"], "request")
        assert fetched["pending"] is False
        assert fetched["document"] == request["document"]

        offer = blair.reconnect_offer_create(
            alex_id, fetched["document"], SDP, FINGERPRINT
        )
        blair.reconnect_publish(blair_profile["id"], offer["document"], "offer")

        fetched_offer = alex.reconnect_fetch(alex_profile["id"], "offer")
        verified_offer = alex.verify_reconnect_offer(fetched_offer["document"])
        assert verified_offer["sdp"] == SDP
        assert verified_offer["attempt_id"] == attempt_id

        answer = alex.reconnect_answer_create(
            blair_id, fetched_offer["document"], SDP, FINGERPRINT
        )
        alex.reconnect_publish(alex_profile["id"], answer["document"], "answer")
        fetched_answer = blair.reconnect_fetch(blair_profile["id"], "answer")
        verified_answer = blair.verify_reconnect_answer(
            fetched_answer["document"], fetched_offer["document"]
        )
        assert verified_answer["sdp"] == SDP
        assert verified_answer["session_id"] == offer["session_id"]

        with pytest.raises(ReconnectReplayed):
            blair.verify_reconnect_answer(
                fetched_answer["document"], fetched_offer["document"]
            )

        assert mailbox.published
        assert all(item["token"] for item in mailbox.published)
        assert all(item["session"] for item in mailbox.published)
    finally:
        blair.close()


def test_no_mailbox_means_manual_required_not_a_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path, mailbox=None)
    try:
        alex.reconnect_consent_set(blair_id, True, False)
        profiles = alex.reconnect_profiles()
        assert profiles["mailbox_configured"] is False
        profile = profiles["profiles"][0]
        assert profile["effective"]["configured"] is False
        assert "mailbox_not_configured" in profile["effective"]["reasons"]
        with pytest.raises((ContactNotApproved, ValidationError)):
            alex.reconnect_request_create(blair_id, uuid.uuid4().hex)
        status = alex.reconnect_status("manual_required", "Signaling mailbox is not configured")
        assert status["state"] == "manual_required"
        assert status["detail"] == "Signaling mailbox is not configured"
    finally:
        blair.close()


def test_start_stop_lifecycle_and_status_transitions(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        _consent(alex, blair)
        started = alex.reconnect_start(blair_id)
        assert started["profiles"][0]["active"] is True
        assert started["profiles"][0]["state"] == "waiting_for_peer"
        assert alex.reconnect_status("connected", "Reticulum path ready")["state"] == "connected"
        stopped = alex.reconnect_stop(blair_id)
        assert stopped["profiles"][0]["active"] is False
        assert stopped["profiles"][0]["state"] == "stopped"
        # A per-contact stop leaves the global supervisor status alone; a full
        # stop records the stopped state.
        assert stopped["state"] == "connected"
        assert alex.reconnect_stop()["state"] == "stopped"
    finally:
        blair.close()


def test_direct_ip_disclosure_or_a_consented_relay_is_required(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        _exchange(alex, blair)
        alex.reconnect_consent_set(blair_id, True, False)
        profile = alex.reconnect_profiles()["profiles"][0]
        assert "relay_required" in profile["effective"]["reasons"]
        assert profile["effective"]["ready"] is False

        alex.reconnect_consent_set(blair_id, True, True)
        profile = alex.reconnect_profiles()["profiles"][0]
        assert "relay_required" not in profile["effective"]["reasons"]
    finally:
        blair.close()


def test_invitation_and_approval_carry_signed_capabilities(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, _, alex_destination = _service(
        tmp_path / "alex", "Alex", device_id="dev-aaaa-0001"
    )
    blair, _, blair_destination = _service(
        tmp_path / "blair", "Blair", device_id="dev-bbbb-0002"
    )
    try:
        invitation = alex._execute(
            "create_invitation", {"peer_destination": blair_destination}
        )
        alex_capabilities = invitation["reconnect_capabilities"]
        verified = verify_connection_capabilities(
            alex_capabilities, expected_signer=alex_destination
        )
        assert verified.peer_destination == blair_destination
        assert verified.device_id == "dev-aaaa-0001"
        assert verified.auto_reconnect is False

        accepted = blair._execute(
            "accept_invitation", {"invitation": invitation["text"]}
        )
        joiner_capabilities = accepted["reconnect_capabilities"]
        verified_joiner = verify_connection_capabilities(
            joiner_capabilities, expected_signer=blair_destination
        )
        assert verified_joiner.peer_destination == alex_destination
        assert verified_joiner.auto_reconnect is False

        # The owner can approve the resulting pending contact and receives its
        # own capability for the now-known peer.
        _add_contact(
            alex,
            accepted["id"],
            blair._call_identity(),
            blair_destination,
            trust=TrustState.PENDING_REQUEST,
        )
        approved = alex._execute("approve_request", {"contact_id": accepted["id"]})
        owner_capabilities = approved["reconnect_capabilities"]
        assert verify_connection_capabilities(
            owner_capabilities, expected_signer=alex_destination
        ).peer_destination == blair_destination
    finally:
        blair.close()


def test_capabilities_can_be_fetched_for_delivery_after_a_restart(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        created = alex.reconnect_consent_set(blair_id, True, True)
        delivered = alex.reconnect_capabilities_get(blair_id)
        assert delivered["local_capabilities"] == created["capabilities"]
        assert delivered["peer_capabilities"] is None
        verified = verify_connection_capabilities(created["capabilities"])
        assert verified.auto_reconnect is True
        assert verified.allow_direct_ip_disclosure is True
    finally:
        blair.close()


def test_path_status_distinguishes_pending_from_unavailable(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    from types import SimpleNamespace

    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        unavailable = alex.reconnect_path_status(blair_id)
        assert unavailable["state"] == "network_unavailable"
        assert unavailable["reason"] == "network_unavailable"

        requested: list[bytes] = []
        alex.network = SimpleNamespace(  # type: ignore[assignment]
            path_known=lambda _destination: False,
            recipient_ready=lambda _destination: False,
            request_path=lambda destination: requested.append(destination),
            reannounce=lambda: None,
        )
        pending = alex.reconnect_path_status(blair_id)
        assert pending["state"] == "path_pending"
        assert pending["has_path"] is False
        assert pending["reason"] == "path_not_ready"
        assert requested

        alex.network = SimpleNamespace(  # type: ignore[assignment]
            path_known=lambda _destination: True,
            recipient_ready=lambda _destination: True,
            request_path=lambda _destination: None,
            reannounce=lambda: None,
        )
        ready = alex.reconnect_path_status(blair_id)
        assert ready["state"] == "path_available"
        assert ready["ready"] is True
        assert ready["reason"] is None
    finally:
        blair.close()


def test_reconnect_commands_are_dispatched(tmp_path: Path, mailbox: FakeMailbox) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        profiles = alex._execute("reconnect_profiles", {})
        assert profiles["local_device_id"] == "dev-aaaa-0001"
        assert profiles["profiles"] == []

        status = alex._execute(
            "reconnect_status",
            {"state": "waiting_for_peer", "detail": "dispatch test"},
        )
        assert status["state"] == "waiting_for_peer"

        assert alex._execute(
            "reconnect_replay_check", {"key": "attempt:dispatch01"}
        )["accepted"] is True
        assert alex._execute(
            "reconnect_replay_check", {"key": "attempt:dispatch01"}
        )["accepted"] is False

        with pytest.raises(ValidationError):
            alex._execute("reconnect_status", {"state": "not-a-state"})

        consent = alex._execute(
            "reconnect_consent_set",
            {
                "contact_id": blair_id,
                "auto_reconnect": True,
                "allow_direct_ip_disclosure": True,
            },
        )
        assert consent["profile"]["auto_reconnect"] is True
        capabilities = alex._execute(
            "reconnect_capabilities_get", {"contact_id": blair_id}
        )
        assert capabilities["local_capabilities"] == consent["capabilities"]
    finally:
        blair.close()


def test_capability_for_an_unknown_contact_is_held_then_promoted(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, _, alex_destination = _service(
        tmp_path / "alex", "Alex", device_id="dev-aaaa-0001"
    )
    blair, _, blair_destination = _service(
        tmp_path / "blair", "Blair", device_id="dev-bbbb-0002"
    )
    try:
        _add_contact(blair, "contact-alex", alex._call_identity(), alex_destination)
        capability = blair.reconnect_consent_set(
            "contact-alex", True, True
        )["capabilities"]
        # Blair's capability arrives before Alex has a contact record for it
        # (for example over the control channel, ahead of the LXMF request).
        held = alex.reconnect_capabilities_store(capability)
        assert held["pending"] is True
        assert held["profile"] is None
        assert alex.reconnect_profiles()["profiles"] == []

        _add_contact(alex, "contact-blair", blair._call_identity(), blair_destination)
        profiles = alex.reconnect_profiles()["profiles"]
        assert len(profiles) == 1
        assert profiles[0]["has_peer_capabilities"] is True
        assert profiles[0]["peer_auto_reconnect"] is True
        assert profiles[0]["peer_transports"] == ["webrtc"]
        assert profiles[0]["peer_capabilities_issued_at"] > 0
        assert alex.store.get("reconnect_pending_capability", blair_destination) is None
    finally:
        blair.close()


def test_local_capability_metadata_is_explicit(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, blair_id, blair, _ = _pair(tmp_path)
    try:
        result = alex.reconnect_consent_set(blair_id, True, True)
        profile = result["profile"]
        assert profile["transports"] == ["webrtc"]
        assert profile["capabilities_issued_at"] > 0
        assert profile["capabilities_expires_at"] > profile["capabilities_issued_at"]
    finally:
        blair.close()


def test_pending_capability_is_promoted_on_approval(
    tmp_path: Path, mailbox: FakeMailbox
) -> None:
    alex, _, alex_destination = _service(
        tmp_path / "alex", "Alex", device_id="dev-aaaa-0001"
    )
    blair, _, blair_destination = _service(
        tmp_path / "blair", "Blair", device_id="dev-bbbb-0002"
    )
    try:
        _add_contact(blair, "contact-alex", alex._call_identity(), alex_destination)
        capability = blair.reconnect_consent_set(
            "contact-alex", True, True
        )["capabilities"]
        assert alex.reconnect_capabilities_store(capability)["pending"] is True

        _add_contact(
            alex,
            "contact-blair",
            blair._call_identity(),
            blair_destination,
            trust=TrustState.PENDING_REQUEST,
        )
        approved = alex.approve_request("contact-blair")
        assert "reconnect_capabilities" in approved
        profiles = alex.reconnect_profiles()["profiles"]
        assert profiles[0]["has_peer_capabilities"] is True
        assert profiles[0]["peer_auto_reconnect"] is True
        assert alex.store.get("reconnect_pending_capability", blair_destination) is None
    finally:
        blair.close()


def test_invalid_mailbox_token_is_rejected_by_the_transport() -> None:
    from mesh_chat import signal_mailbox

    with pytest.raises(ValidationError):
        signal_mailbox.publish(
            MAILBOX,
            json.dumps({"type": "webrtc_reconnect_request"}),
            "request",
            token="short",
            session="s" * 20,
        )
    assert reconnect_session_id("a" * 32) == reconnect_session_id("a" * 32)
    assert reconnect_session_id("a" * 32) != reconnect_session_id("b" * 32)
