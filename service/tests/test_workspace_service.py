from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import LXMF
import pytest
import RNS

from mesh_chat.errors import ContactNotApproved, IdentityMismatch, StaleCursor, ValidationError
from mesh_chat.invitations import readable_fingerprint
from mesh_chat.models import DeliveryState
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore
from mesh_chat.workspace_protocol import (
    WorkspaceManifestMemberInput,
    create_workspace_admin_decision,
    create_workspace_channel_manifest,
    create_workspace_channel_record,
    create_workspace_device_card,
    create_workspace_event,
    create_workspace_manifest,
    create_workspace_mutation_event,
    verify_workspace_genesis,
    verify_workspace_admin_request,
    verify_workspace_manifest,
)
from mesh_chat.workspace_wire import WorkspaceWirePayload, parse_workspace_payload
from mesh_chat.workspace_service import (
    normalize_workspace_search_text,
    sanitize_notification_text,
    tokenize_workspace_search_text,
)


class RecordingWorkspaceNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.remembered: list[bytes] = []

    def invitation_hints(self) -> list[dict[str, Any]]:
        return []

    def remember_contact(self, _public_key: bytes, destination: bytes) -> None:
        self.remembered.append(destination)

    def recipient_ready(self, _destination: bytes) -> bool:
        return True

    def path_known(self, _destination: bytes) -> bool:
        return True

    def request_path(self, _destination: bytes) -> None:
        pass

    def send_with_fields(self, **value: Any) -> str:
        self.sent.append(value)
        return f"native-{len(self.sent)}"

    def apply_connection_settings(self, _settings: Any) -> None:
        pass

    def cancel_outbound(self, _logical_ids: set[str]) -> int:
        return 0

    def snapshot(self) -> dict[str, Any]:
        return {"interface_available": True, "interfaces": []}

    def shutdown(self) -> None:
        pass


class RecoveringWorkspaceRouteNetwork(RecordingWorkspaceNetwork):
    def __init__(self) -> None:
        super().__init__()
        self.route_attached = False
        self.attachment_failures = 1
        self.events: list[str] = []
        self.preference_timeouts: list[float] = []

    def apply_connection_settings(self, _settings: Any) -> None:
        self.events.append("apply")
        if self.attachment_failures:
            self.attachment_failures -= 1
            raise RuntimeError("route attachment failed")
        self.route_attached = True

    def prefer_signed_route(
        self,
        _destination: bytes,
        _connection_hints: list[dict[str, Any]],
        *,
        timeout: float = 0.75,
    ) -> bool:
        self.events.append("prefer")
        self.preference_timeouts.append(timeout)
        return self.route_attached

    def recipient_ready(self, _destination: bytes) -> bool:
        self.events.append("ready")
        return self.route_attached

    def send_with_fields(self, **value: Any) -> str:
        self.events.append("send")
        return super().send_with_fields(**value)


class RaisingPreferenceWorkspaceNetwork(RecordingWorkspaceNetwork):
    def __init__(self) -> None:
        super().__init__()
        self.preference_timeouts: list[float] = []

    def prefer_signed_route(
        self,
        _destination: bytes,
        _connection_hints: list[dict[str, Any]],
        *,
        timeout: float = 0.75,
    ) -> bool:
        self.preference_timeouts.append(timeout)
        raise RuntimeError("route preference failed")


def _profile(identity: RNS.Identity, display_name: str) -> dict[str, Any]:
    public_key = identity.get_public_key()
    destination = RNS.Destination.hash(identity, "lxmf", "delivery")
    return {
        "display_name": display_name,
        "public_identity": base64.urlsafe_b64encode(public_key).decode("ascii"),
        "identity_hash": identity.hash.hex(),
        "destination_hash": destination.hex(),
        "fingerprint": readable_fingerprint(public_key),
        "created_at": time.time(),
    }


def _service(
    root: Path,
    identity: RNS.Identity,
    display_name: str,
    *,
    vault_key: bytes | None = None,
) -> tuple[MeshChatService, RecordingWorkspaceNetwork]:
    store = VaultStore(
        root, vault_key or os.urandom(32), allow_unprotected_for_tests=True
    )
    # Keep this unit harness on its recording network even when reopening a
    # persisted profile. The production constructor sees both records and
    # starts Reticulum, so temporarily remove only these two local-profile
    # records while constructing the service and restore them immediately.
    if store.get("identity", "local") is not None:
        store.delete("identity", "local")
    if store.get("profile", "local") is not None:
        store.delete("profile", "local")
    service = MeshChatService(store, root, lambda _event: None)
    store.put(
        "identity",
        "local",
        {
            "private_key": base64.urlsafe_b64encode(
                identity.get_private_key()
            ).decode("ascii")
        },
    )
    store.put("profile", "local", _profile(identity, display_name))
    service._shutdown.set()
    service._identity = identity
    network = RecordingWorkspaceNetwork()
    service.network = network  # type: ignore[assignment]
    return service, network


def _native(sent: dict[str, Any], *, source: bytes, destination: bytes) -> LXMF.LXMessage:
    return LXMF.LXMessage(
        None,
        None,
        content=sent["text"],
        fields=sent["fields"],
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=destination,
        source_hash=source,
    )


def _deliver(
    recipient: MeshChatService,
    sent: dict[str, Any],
    *,
    source_profile: dict[str, Any],
    recipient_profile: dict[str, Any],
) -> None:
    recipient._on_inbound_locked(
        _native(
            sent,
            source=bytes.fromhex(source_profile["destination_hash"]),
            destination=bytes.fromhex(recipient_profile["destination_hash"]),
        )
    )


def _flush(service: MeshChatService, network: RecordingWorkspaceNetwork) -> list[dict[str, Any]]:
    before = len(network.sent)
    service._retry_workspace_outbox()
    return network.sent[before:]


def _op(index: int) -> str:
    return str(uuid.UUID(int=index, version=4))


def _joined_pair(
    root: Path, *, base: int
) -> tuple[
    MeshChatService,
    RecordingWorkspaceNetwork,
    dict[str, Any],
    MeshChatService,
    RecordingWorkspaceNetwork,
    dict[str, Any],
    dict[str, Any],
    bytes,
    RNS.Identity,
]:
    owner_identity = RNS.Identity()
    member_identity = RNS.Identity()
    member_key = os.urandom(32)
    owner, owner_network = _service(root / "owner", owner_identity, "Alex")
    member, member_network = _service(
        root / "member", member_identity, "Bailey", vault_key=member_key
    )
    owner_profile = owner._require_profile()
    member_profile = member._require_profile()
    workspace = owner.create_workspace(_op(base), "Channel lab", "Increment 3")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(base + 1)
    )
    member.submit_workspace_join(invitation["text"], _op(base + 2))
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    request = next(
        item
        for item in owner.workspace_snapshot()["workspace_join_requests"]
        if item["workspace_id"] == workspace["id"]
    )
    owner.approve_workspace_join(workspace["id"], request["id"], _op(base + 3))
    controls = _flush(owner, owner_network)
    controls.sort(
        key=lambda item: 0
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_manifest_root"
        else 1
    )
    for item in controls:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert member._require_workspace(workspace["id"])["state"] == "active"
    return (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    )


def test_direct_workspace_binding_rechecks_admission_and_local_identity(tmp_path):
    from dataclasses import replace
    from mesh_chat.direct_binding import BindingAuthority, create_binding
    owner, _, owner_profile, member, _, _, workspace, _, identity = _joined_pair(tmp_path, base=90000)
    try:
        local = owner._require_workspace(workspace["id"])
        remote = member._require_workspace(workspace["id"])
        now = int(time.time())
        authority = BindingAuthority(identity.get_public_key(),
            bytes.fromhex(owner_profile["destination_hash"]), {
                "kind": "workspace", "workspace_id": workspace["id"],
                "issuer_device_id": remote["local_device_id"],
                "audience_device_id": local["local_device_id"],
            }, now + 300, b"c" * 32)
        cert = b"native public certificate"
        raw = create_binding(identity, authority, cert, session_id=str(uuid.uuid4()),
            challenge=authority.challenge, generation=1,
            candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": now + 300}],
            issued_at=now, expires_at=now + 300)
        assert owner._accept_direct_workspace_binding(raw, authority, cert).generation == 1
        for changed in (
            replace(authority, audience_destination=b"x" * 16),
            replace(authority, issuer_public_identity=RNS.Identity().get_public_key()),
            replace(authority, scope={**authority.scope, "audience_device_id": remote["local_device_id"]}),
        ):
            with pytest.raises((ValidationError, IdentityMismatch)):
                owner._accept_direct_workspace_binding(raw, changed, cert)
        original_identity = owner._identity
        owner._identity = RNS.Identity()
        with pytest.raises(IdentityMismatch):
            owner._accept_direct_workspace_binding(raw, authority, cert)
        owner._identity = original_identity
        owner._identity = None
        with pytest.raises(ValidationError):
            owner._accept_direct_workspace_binding(raw, authority, cert)
        owner._identity = original_identity
        for state in ("joining", "removed", "closed", "frozen"):
            owner.store.put("workspace", owner._workspace_record_id(workspace["id"]),
                            {**local, "state": state})
            with pytest.raises(ValidationError):
                owner._accept_direct_workspace_binding(raw, authority, cert)
        owner.store.put("workspace", owner._workspace_record_id(workspace["id"]), local)
        # Even an independently valid signed manifest from another workspace
        # must not authorize this scope through a changed local pointer.
        other = owner.create_workspace(_op(90011), "Other", "")
        owner.store.put("workspace", owner._workspace_record_id(workspace["id"]),
                        {**local, "manifest_hash": owner._require_workspace(other["id"])["manifest_hash"]})
        with pytest.raises(IdentityMismatch):
            owner._accept_direct_workspace_binding(raw, authority, cert)
        owner.store.put("workspace", owner._workspace_record_id(workspace["id"]), local)
        owner.remove_workspace_member(workspace["id"], remote["local_member_id"], _op(90010))
        with pytest.raises(IdentityMismatch):
            owner._accept_direct_workspace_binding(raw, authority, cert)
    finally:
        owner.close()
        member.close()


def test_direct_join_binding_requires_saved_pending_join(tmp_path, monkeypatch):
    from dataclasses import replace
    from mesh_chat.errors import InvitationExpired
    from mesh_chat.direct_binding import BindingAuthority, create_binding
    from mesh_chat.workspace_protocol import verify_workspace_invitation, workspace_document_digest
    owner_identity, identity = RNS.Identity(), RNS.Identity()
    owner, _ = _service(tmp_path / "owner", owner_identity, "Owner")
    joiner, _ = _service(tmp_path / "joiner", identity, "Joiner")
    try:
        workspace = owner.create_workspace(_op(91000), "Pending", "")
        invitation = owner.create_workspace_invitation_command(workspace["id"], _op(91001))
        invite = verify_workspace_invitation(invitation["text"])
        now = int(time.time())
        authority = BindingAuthority(owner_identity.get_public_key(),
            bytes.fromhex(joiner._require_profile()["destination_hash"]), {
                "kind": "invitation", "digest": workspace_document_digest(invite.serialized),
                "expires_at": invite.expires_at,
            }, now + 300, b"c" * 32)
        cert = b"public native cert"
        raw = create_binding(owner_identity, authority, cert, session_id=str(uuid.uuid4()),
            challenge=authority.challenge, generation=1,
            candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": now + 300}],
            issued_at=now, expires_at=now + 300)
        def accept(expected=authority):
            return joiner._accept_direct_join_binding(workspace["id"], raw, expected, cert)
        with pytest.raises(ValidationError):
            accept()  # Preview alone cannot authorize a path.
        joiner.submit_workspace_join(invitation["text"], _op(91002))
        assert accept().generation == 1
        for changed in (replace(authority, issuer_public_identity=RNS.Identity().get_public_key()),
                        replace(authority, audience_destination=b"x" * 16),
                        replace(authority, scope={**authority.scope, "digest": "ab" * 32})):
            with pytest.raises(IdentityMismatch):
                accept(changed)
        record_id = joiner._workspace_invitation_record_id(invite.nonce)
        record = joiner.store.get("workspace_invitation", record_id)
        for state in ("revoked", "expired", "consumed", "active"):
            joiner.store.put("workspace_invitation", record_id, {**record, "state": state})
            with pytest.raises(IdentityMismatch):
                accept()
        joiner.store.put("workspace_invitation", record_id, record)
        with monkeypatch.context() as clock:
            clock.setattr(time, "time", lambda: invite.expires_at + 1)
            with pytest.raises(InvitationExpired):
                accept()
        local = joiner._require_workspace(workspace["id"])
        for state in ("active", "declined", "removed"):
            joiner.store.put("workspace", joiner._workspace_record_id(workspace["id"]), {**local, "state": state})
            with pytest.raises(ValidationError):
                accept()
        joiner.store.put("workspace", joiner._workspace_record_id(workspace["id"]), local)
        joiner._identity = RNS.Identity()
        with pytest.raises(IdentityMismatch):
            accept()
        joiner._identity = identity
        delivery = joiner.store.get("workspace_delivery", local["join_delivery_id"])
        joiner.store.put("workspace_delivery", local["join_delivery_id"],
                        {**delivery, "recipient_destination": "ab" * 16})
        with pytest.raises(IdentityMismatch):
            accept()
        joiner.store.delete("workspace_delivery", local["join_delivery_id"])
        with pytest.raises(ValidationError):
            accept()
    finally:
        owner.close()
        joiner.close()


def test_direct_owner_binding_selects_one_responder_without_admission(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from mesh_chat.direct_binding import BindingAuthority, create_binding
    identity, key = RNS.Identity(), os.urandom(32)
    owner, _ = _service(tmp_path, identity, "Owner", vault_key=key)
    try:
        workspace = owner.create_workspace(_op(92000), "Owner negotiation", "")
        invitation = owner.create_workspace_invitation_command(workspace["id"], _op(92001))
        now = int(time.time())
        prepared = owner._prepare_direct_invitation(invitation["id"], now + 240)
        assert owner._prepare_direct_invitation(invitation["id"], now + 250) == prepared
        cert = b"native public certificate"
        def binding(peer, generation=1, challenge=None):
            authority = BindingAuthority(peer.get_public_key(), bytes.fromhex(prepared["audience"]),
                prepared["scope"], prepared["expires_at"], challenge or bytes.fromhex(prepared["challenge"]))
            raw = create_binding(peer, authority, cert, session_id=str(uuid.uuid4()),
                challenge=authority.challenge, generation=generation,
                candidates=[{"host": "8.8.8.8", "port": 12345, "expires_at": prepared["expires_at"]}],
                issued_at=now, expires_at=prepared["expires_at"])
            return raw, authority
        def accept(pair):
            return owner._accept_direct_owner_binding(invitation["id"], *pair, cert)
        first, second = RNS.Identity(), RNS.Identity()
        with pytest.raises(IdentityMismatch):
            accept(binding(first, challenge=b"x" * 32))
        assert owner.store.get("direct_pending", invitation["id"])["selected_identity"] is None
        pairs = [binding(first), binding(second)]
        with monkeypatch.context() as disk:
            def fail_write(*args):
                raise OSError("write failed")
            disk.setattr(owner.store, "_seal", fail_write)
            with pytest.raises(OSError):
                accept(pairs[0])
        assert owner.store.get("direct_pending", invitation["id"])["selected_identity"] is None
        def compete(pair):
            try:
                return accept(pair)
            except IdentityMismatch:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, pairs))
        assert sum(value is not None for value in results) == 1
        winner = 0 if results[0] else 1
        assert accept(pairs[winner]) == results[winner]
        assert owner.store.list("workspace_join_request") == []
        assert len(owner._workspace_current_manifest(owner._require_workspace(workspace["id"])).members) == 1
        owner.close()
        owner, _ = _service(tmp_path, identity, "Owner", vault_key=key)
        assert accept(pairs[winner]) == results[winner]
        with pytest.raises(IdentityMismatch):
            accept(pairs[1 - winner])
        peer = (first, second)[winner]
        with pytest.raises(ValidationError):
            accept(binding(peer))  # Same generation, different signed bytes.
        assert accept(binding(peer, generation=2)).generation == 2
        with pytest.raises(ValidationError):
            accept(pairs[winner])
        with pytest.raises(ValidationError, match="still active"):
            owner._replace_direct_invitation(invitation["id"], prepared["challenge"], now + 290)
        old_challenge = prepared["challenge"]
        old_expiry = prepared["expires_at"]
        with monkeypatch.context() as clock:
            clock.setattr(time, "time", lambda: old_expiry + 1)
            with pytest.raises(ValidationError):
                accept(pairs[winner])
            with pytest.raises(ValidationError):
                owner._prepare_direct_invitation(invitation["id"], prepared["expires_at"] + 200)
            with monkeypatch.context() as disk:
                disk.setattr(owner.store, "_seal", fail_write)
                with pytest.raises(OSError):
                    owner._replace_direct_invitation(invitation["id"], old_challenge, old_expiry + 200)
            assert owner.store.get("direct_pending", invitation["id"])["challenge"] == old_challenge
            prepared = owner._replace_direct_invitation(invitation["id"], old_challenge, old_expiry + 200)
            assert prepared["challenge"] != old_challenge
            assert prepared["selected_identity"] == peer.get_public_key().hex()
            assert prepared["accepted"]["generation"] == 2
            assert owner._replace_direct_invitation(invitation["id"], old_challenge, old_expiry + 200) == prepared
            with pytest.raises(ValidationError):
                owner._replace_direct_invitation(invitation["id"], old_challenge, old_expiry + 201)
            with pytest.raises(ValidationError):
                owner._replace_direct_invitation(invitation["id"], "00" * 32, old_expiry + 200)
            with pytest.raises(IdentityMismatch):
                accept(pairs[winner])  # Old challenge cannot reactivate the expired path.
            with pytest.raises(IdentityMismatch):
                accept(binding((first, second)[1 - winner], generation=3))
            with pytest.raises(ValidationError):
                accept(binding(peer, generation=2))  # Replacement does not reset replay history.
            refreshed = binding(peer, generation=3)
            assert accept(refreshed).generation == 3
        owner.close()
        owner, _ = _service(tmp_path, identity, "Owner", vault_key=key)
        assert accept(refreshed).generation == 3
        owner.revoke_workspace_invitation(workspace["id"], invitation["id"], _op(92002))
        with pytest.raises(ValidationError):
            accept(pairs[winner])
        with pytest.raises(ValidationError):
            owner._replace_direct_invitation(invitation["id"], old_challenge, prepared["expires_at"])
    finally:
        owner.close()


def _deliver_all(
    recipient: MeshChatService,
    packets: list[dict[str, Any]],
    *,
    source_profile: dict[str, Any],
    recipient_profile: dict[str, Any],
) -> None:
    for packet in packets:
        _deliver(
            recipient,
            packet,
            source_profile=source_profile,
            recipient_profile=recipient_profile,
        )


def test_workspace_history_catch_up_recovers_exact_missed_canonical_event(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path, base=90_000)
    general_id = workspace["general_channel_id"]
    sent = owner.send_workspace_message(
        workspace["id"], general_id, "retained while the peer was offline",
        _op(90_010), _op(90_011),
    )
    original = owner.store.get(
        "workspace_event", owner._workspace_event_record_id(sent["id"])
    )
    assert original is not None
    # Do not deliver the ordinary seven-day live leg. Start a separately signed
    # retained-history job from the offline peer instead.
    outcome = member.start_workspace_history(
        workspace["id"], general_id, _op(90_012)
    )
    assert outcome["status"] == "requesting"
    requests = [
        item for item in _flush(member, member_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind == "workspace_history_request"
    ]
    assert len(requests) == 1
    _deliver(
        owner,
        requests[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    responses = [
        item for item in _flush(owner, owner_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind == "workspace_history_response"
    ]
    assert len(responses) == 1
    _deliver(
        member,
        responses[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    recovered = member.store.get(
        "workspace_event", member._workspace_event_record_id(sent["id"])
    )
    assert recovered is not None
    assert recovered["serialized"] == original["serialized"]
    page = member.list_workspace_messages(workspace["id"], general_id)
    assert [item["text"] for item in page["messages"]] == [
        "retained while the peer was offline"
    ]
    status = member.get_workspace_history_status(workspace["id"], general_id)
    assert status["job"]["recovered_events"] == 1
    assert status["job"]["status"] == "complete_known"
    _deliver(
        member,
        responses[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    replayed = member.get_workspace_history_status(workspace["id"], general_id)
    assert replayed["job"]["recovered_events"] == 1
    assert replayed["job"]["verified_pages"] == 1


def test_mobile_notification_queue_is_durable_private_bounded_and_deduplicated(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        _member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "notifications", base=91_000)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    member.set_native_notification_state("android", True, "allowed")
    member.mobile_lifecycle_transition("background", "activity_paused")
    member.set_hide_notification_previews(True, _op(91_010))

    message = owner.send_workspace_message(
        workspace_id,
        channel_id,
        "hostile\npreview\u202e text",
        _op(91_011),
        _op(91_012),
    )
    packets = _flush(owner, owner_network)
    event_packet = next(
        item
        for item in packets
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_event"
    )
    _deliver(
        member,
        event_packet,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )

    state = member.notification_state()
    assert state["pending_native_count"] == 1
    work = member.drain_native_notification_work(16)["items"]
    assert len(work) == 1
    assert work[0]["title"] == "Mesh Chat"
    assert work[0]["body"] == "New message"
    assert len(json.dumps(work[0]).encode("utf-8")) <= 1024
    assert workspace_id not in json.dumps(work[0])
    assert channel_id not in json.dumps(work[0])
    assert message["id"] not in json.dumps(work[0])

    # A replay cannot mint a second logical notification.
    _deliver(
        member,
        event_packet,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.notification_state()["pending_native_count"] == 1
    assert member.drain_native_notification_work(16)["items"] == work

    # Routing re-authorizes without changing the existing unread state.
    before = member.workspace_snapshot()["workspace_channels"][0]["unread_count"]
    target = member.open_notification_target(work[0]["notification_id"])
    after = member.workspace_snapshot()["workspace_channels"][0]["unread_count"]
    assert target == {
        "available": True,
        "workspace_id": workspace_id,
        "conversation_id": channel_id,
        "conversation_kind": "channel",
        "thread_root_id": None,
        "event_id": message["id"],
    }
    assert before == after == 1

    # Pending native work survives a service restart and an accepted native
    # acknowledgment only records platform API acceptance.
    member.close()
    restarted, _network = _service(
        tmp_path / "notifications" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    assert restarted.drain_native_notification_work(16)["items"] == work
    assert restarted.acknowledge_native_notification(
        work[0]["notification_id"], "retry"
    ) == {"acknowledged": True, "outcome": "retry"}
    assert restarted.drain_native_notification_work(16)["items"] == work
    assert restarted.acknowledge_native_notification(
        work[0]["notification_id"], "accepted"
    ) == {"acknowledged": True, "outcome": "accepted"}
    assert restarted.drain_native_notification_work(16)["items"] == []
    assert restarted.acknowledge_native_notification(
        work[0]["notification_id"], "accepted"
    ) == {"acknowledged": False}
    with pytest.raises(ValidationError, match="acknowledgment"):
        restarted.acknowledge_native_notification("../route", "accepted")
    with pytest.raises(ValidationError, match="acknowledgment"):
        restarted.acknowledge_native_notification(work[0]["notification_id"], "read")
    with pytest.raises(ValidationError, match="batch limit"):
        restarted.drain_native_notification_work(17)

    restarted.hide_workspace_message(workspace_id, message["id"], _op(91_015))
    unavailable = restarted.open_notification_target(work[0]["notification_id"])
    assert unavailable["available"] is False
    assert unavailable["reason"] == "authorization_changed"

    owner.send_workspace_message(
        workspace_id,
        channel_id,
        "committed while the activity is backgrounded",
        _op(91_013),
        _op(91_014),
    )
    _deliver_all(
        restarted,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert restarted.notification_state()["pending_native_count"] == 1
    restarted.mobile_lifecycle_transition("foreground", "activity_resumed")
    assert restarted.notification_state()["pending_native_count"] == 0
    assert restarted.drain_native_notification_work(16)["items"] == []


def test_notification_text_sanitization_removes_hostile_controls_and_bounds() -> None:
    hostile = "  hello\n\tworld\u202e\u200b\x00  " + ("🙂" * 200)
    sanitized = sanitize_notification_text(hostile, 24)

    assert sanitized.startswith("hello world")
    assert len(sanitized) == 24
    assert all(not value in sanitized for value in ("\n", "\t", "\u202e", "\u200b", "\x00"))


def test_notification_precedence_uses_structured_mentions_and_never_catches_up(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "notification-policy", base=92_000)
    workspace_id = workspace["id"]
    member_id = member.workspace_snapshot()["workspaces"][0]["local_member_id"]
    member.set_native_notification_state("android", True, "allowed")
    member.mobile_lifecycle_transition("background", "activity_paused")
    member.set_workspace_notification_preference(
        workspace_id, None, "mentions_only", _op(92_010)
    )
    channel = owner.create_workspace_channel(
        workspace_id, "alerts", "Unsubscribed public alerts", _op(92_011)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )

    owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey text alone is not a mention",
        _op(92_012),
        _op(92_013),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.drain_native_notification_work(16)["items"] == []


    owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Structured mention",
        _op(92_014),
        _op(92_015),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    work = member.drain_native_notification_work(16)["items"]
    assert len(work) == 1
    assert work[0]["category"] == "mention"
    member.acknowledge_native_notification(work[0]["notification_id"], "accepted")

    member.set_workspace_channel_mentions_muted(
        workspace_id, channel["id"], True, _op(92_016)
    )
    owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Muted structured mention",
        _op(92_017),
        _op(92_018),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.drain_native_notification_work(16)["items"] == []

    # Historical recovery materializes the canonical event but cannot create
    # notification work, even while the mobile runtime is backgrounded.
    missed = owner.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "old event recovered later",
        _op(92_019),
        _op(92_020),
        [member_id],
    )
    assert missed
    member.start_workspace_history(
        workspace_id, workspace["general_channel_id"], _op(92_021)
    )
    requests = [
        item
        for item in _flush(member, member_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_history_request"
    ]
    _deliver(
        owner,
        requests[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    responses = [
        item
        for item in _flush(owner, owner_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_history_response"
    ]
    _deliver(
        member,
        responses[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.drain_native_notification_work(16)["items"] == []


def test_workspace_notification_families_cover_channel_dm_thread_and_skip_mutations(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        _member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "notification-families", base=93_000)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    owner_view = owner.workspace_snapshot()["workspaces"][0]
    member_id = next(
        item["id"]
        for item in owner_view["members"]
        if item["id"] != owner_view["local_member_id"]
    )
    member.set_native_notification_state("android", True, "allowed")
    member.mobile_lifecycle_transition("background", "activity_paused")

    root = owner.send_workspace_message(
        workspace_id, channel_id, "Channel arrival", _op(93_010), _op(93_011)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    work = member.drain_native_notification_work(16)["items"]
    assert [item["category"] for item in work] == ["channel_message"]
    member.acknowledge_native_notification(work[0]["notification_id"], "accepted")

    direct = owner.open_workspace_direct(workspace_id, member_id, _op(93_012))
    owner.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Workspace DM arrival",
        _op(93_013),
        _op(93_014),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    work = member.drain_native_notification_work(16)["items"]
    assert [item["category"] for item in work] == ["direct_message"]
    member.acknowledge_native_notification(work[0]["notification_id"], "accepted")

    owner.send_workspace_thread_reply(
        workspace_id,
        channel_id,
        root["id"],
        "Thread reply arrival",
        _op(93_015),
        _op(93_016),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    work = member.drain_native_notification_work(16)["items"]
    assert [item["category"] for item in work] == ["thread_reply"]
    member.acknowledge_native_notification(work[0]["notification_id"], "accepted")

    owner.edit_workspace_message(
        workspace_id,
        root["id"],
        "Edited channel arrival",
        _op(93_017),
        _op(93_018),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.drain_native_notification_work(16)["items"] == []

    owner.send_workspace_message(
        workspace_id,
        channel_id,
        "Structured mention arrival",
        _op(93_019),
        _op(93_020),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    work = member.drain_native_notification_work(16)["items"]
    assert [item["category"] for item in work] == ["mention"]


def test_joining_workspace_projects_exact_delivery_state(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "join-state-owner", owner_identity, "Alex"
    )
    joiner, _joiner_network = _service(
        tmp_path / "join-state-joiner", joiner_identity, "Bailey"
    )
    workspace = owner.create_workspace(_op(9000), "Delivery state", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(9001)
    )

    submitted = joiner.submit_workspace_join(invitation["text"], _op(9002))
    assert submitted["state"] == "joining"
    assert submitted["join_delivery_state"] == DeliveryState.QUEUED.value
    assert "join_delivery_id" not in submitted

    joining = joiner.workspace_snapshot()["workspaces"][0]
    assert joining["join_delivery_state"] == DeliveryState.QUEUED.value
    assert "join_delivery_id" not in joining
    stored = joiner._require_workspace(workspace["id"])
    delivery_id = stored["join_delivery_id"]
    assert isinstance(delivery_id, str)

    assert joiner._on_workspace_native_status(
        delivery_id, DeliveryState.RECEIVED_BY_ENDPOINT, None
    )
    received = joiner.workspace_snapshot()["workspaces"][0]
    assert received["join_delivery_state"] == DeliveryState.RECEIVED_BY_ENDPOINT.value
    assert "join_delivery_id" not in received

    owner.close()
    joiner.close()


def test_join_delivery_pointer_migrates_once_and_uses_direct_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "join-migration-owner", owner_identity, "Alex"
    )
    joiner, _joiner_network = _service(
        tmp_path / "join-migration-joiner", joiner_identity, "Bailey"
    )
    workspace = owner.create_workspace(_op(9010), "Migrated join", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(9011)
    )
    joiner.submit_workspace_join(invitation["text"], _op(9012))

    record_id = joiner._workspace_record_id(workspace["id"])
    stored = joiner.store.get("workspace", record_id)
    assert stored is not None
    delivery_id = stored.pop("join_delivery_id")
    joiner.store.put("workspace", record_id, stored)

    original_delivery = joiner.store.get("workspace_delivery", delivery_id)
    assert original_delivery is not None
    later_delivery = dict(original_delivery)
    later_delivery["id"] = _op(9013)
    later_delivery["created_at"] = float(original_delivery["created_at"]) + 1
    joiner.store.put("workspace_delivery", later_delivery["id"], later_delivery)

    original_list = joiner.store.list
    delivery_scans = 0

    def counted_list(kind: str) -> list[dict[str, Any]]:
        nonlocal delivery_scans
        if kind == "workspace_delivery":
            delivery_scans += 1
        return original_list(kind)

    monkeypatch.setattr(joiner.store, "list", counted_list)
    first = joiner.workspace_snapshot()["workspaces"][0]
    assert first["join_delivery_state"] == DeliveryState.QUEUED.value
    assert delivery_scans == 1
    migrated = joiner.store.get("workspace", record_id)
    assert migrated is not None
    assert migrated["join_delivery_id"] == delivery_id

    second = joiner.workspace_snapshot()["workspaces"][0]
    assert second["join_delivery_state"] == DeliveryState.QUEUED.value
    assert delivery_scans == 1

    owner.close()
    joiner.close()


def test_pending_workspace_join_counts_as_owner_review(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "join-review-owner", owner_identity, "Alex"
    )
    joiner, joiner_network = _service(
        tmp_path / "join-review-joiner", joiner_identity, "Bailey"
    )
    owner_profile = owner._require_profile()
    joiner_profile = joiner._require_profile()
    workspace = owner.create_workspace(_op(9020), "Owner review", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(9021)
    )
    joiner.submit_workspace_join(invitation["text"], _op(9022))

    outgoing = _flush(joiner, joiner_network)
    assert len(outgoing) == 1
    _deliver(
        owner,
        outgoing[0],
        source_profile=joiner_profile,
        recipient_profile=owner_profile,
    )
    owner_snapshot = owner.workspace_snapshot()
    assert len(owner_snapshot["workspace_join_requests"]) == 1
    assert owner_snapshot["workspaces"][0]["pending_owner_review_count"] == 1

    owner.close()
    joiner.close()


def test_workspace_delivery_retries_dirty_signed_route_attachment(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "route-retry-owner", owner_identity, "Alex"
    )
    joiner, _joiner_network = _service(
        tmp_path / "route-retry-joiner", joiner_identity, "Bailey"
    )
    workspace = owner.create_workspace(_op(9030), "Route retry", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(9031)
    )
    joiner.submit_workspace_join(invitation["text"], _op(9032))

    delivery = next(
        item
        for item in joiner.store.list("workspace_delivery")
        if item.get("workspace_id") == workspace["id"]
        and item.get("kind") == "workspace_join"
    )
    delivery_id = delivery["id"]
    hint = {"type": "tcp", "host": "198.51.100.23", "port": 4242}
    delivery["recipient_hints"] = [hint]
    delivery["next_attempt_at"] = 0
    joiner.store.put("workspace_delivery", delivery_id, delivery)

    network = RecoveringWorkspaceRouteNetwork()
    joiner.network = network  # type: ignore[assignment]
    joiner._attempt_workspace_delivery(delivery_id)

    first_attempt = joiner.store.get("workspace_delivery", delivery_id)
    assert first_attempt is not None
    assert first_attempt["state"] == DeliveryState.WAITING_FOR_KEYS.value
    assert joiner.settings.tcp_clients == [hint]
    assert joiner._connection_settings_dirty is True
    assert network.events == ["apply", "prefer", "ready"]
    assert network.preference_timeouts == [0.0]

    first_attempt["next_attempt_at"] = 0
    joiner.store.put("workspace_delivery", delivery_id, first_attempt)
    joiner._attempt_workspace_delivery(delivery_id)

    assert joiner._connection_settings_dirty is False
    assert network.events == [
        "apply",
        "prefer",
        "ready",
        "apply",
        "prefer",
        "ready",
        "send",
    ]
    assert network.preference_timeouts == [0.0, 0.0]
    assert len(network.sent) == 1
    assert network.sent[0]["logical_id"] == delivery_id

    owner.close()
    joiner.close()


def test_workspace_delivery_preference_failure_does_not_starve_due_batch(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "preference-failure-owner", owner_identity, "Alex"
    )
    joiner, _joiner_network = _service(
        tmp_path / "preference-failure-joiner", joiner_identity, "Bailey"
    )
    for index in range(2):
        workspace = owner.create_workspace(
            _op(9040 + index * 3), f"Preference {index}", ""
        )
        invitation = owner.create_workspace_invitation_command(
            workspace["id"], _op(9041 + index * 3)
        )
        joiner.submit_workspace_join(
            invitation["text"], _op(9042 + index * 3)
        )

    network = RaisingPreferenceWorkspaceNetwork()
    joiner.network = network  # type: ignore[assignment]
    joiner._retry_workspace_outbox()

    assert len(network.sent) == 2
    assert network.preference_timeouts == [0.0, 0.0]

    owner.close()
    joiner.close()


def test_terminal_workspace_join_can_be_removed_before_retrying(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, _owner_network = _service(
        tmp_path / "failed-join-owner", owner_identity, "Alex"
    )
    joiner, _joiner_network = _service(
        tmp_path / "failed-join-joiner", joiner_identity, "Bailey"
    )
    workspace = owner.create_workspace(_op(9060), "Failed join", "")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(9061)
    )
    joiner.submit_workspace_join(invitation["text"], _op(9062))

    with pytest.raises(ValidationError, match="Leave or close"):
        joiner.remove_workspace_data(workspace["id"], workspace["id"], _op(9063))

    stored_workspace = joiner._require_workspace(workspace["id"])
    delivery_id = stored_workspace["join_delivery_id"]
    delivery = joiner.store.get("workspace_delivery", delivery_id)
    assert delivery is not None
    delivery["state"] = DeliveryState.FAILED.value
    joiner.store.put("workspace_delivery", delivery_id, delivery)

    removed = joiner.remove_workspace_data(
        workspace["id"], workspace["id"], _op(9064)
    )
    assert removed == {"workspace_id": workspace["id"], "removed": True}
    assert joiner.workspace_snapshot()["workspaces"] == []
    assert joiner.store.get("workspace_delivery", delivery_id) is None

    owner.close()
    joiner.close()


def test_two_member_workspace_create_join_chat_and_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_identity = RNS.Identity()
    joiner_identity = RNS.Identity()
    owner, owner_network = _service(tmp_path / "owner", owner_identity, "Alex")
    joiner, joiner_network = _service(tmp_path / "joiner", joiner_identity, "Bailey")
    owner_profile = owner._require_profile()
    joiner_profile = joiner._require_profile()

    workspace = owner.create_workspace(_op(1), "Lakewatcher", "Field team")
    assert owner.create_workspace(_op(1), "Lakewatcher", "Field team")["id"] == workspace["id"]
    with pytest.raises(ValidationError, match="different input"):
        owner.create_workspace(_op(1), "Another name", "Field team")
    invitation = owner.create_workspace_invitation_command(
        workspace["id"], _op(2)
    )
    joining = joiner.submit_workspace_join(invitation["text"], _op(3))
    assert joining["state"] == "joining"

    outgoing_join = _flush(joiner, joiner_network)
    assert len(outgoing_join) == 1
    assert parse_workspace_payload(
        _native(
            outgoing_join[0],
            source=bytes.fromhex(joiner_profile["destination_hash"]),
            destination=bytes.fromhex(owner_profile["destination_hash"]),
        )
    ).kind == "workspace_join"
    _deliver(
        owner,
        outgoing_join[0],
        source_profile=joiner_profile,
        recipient_profile=owner_profile,
    )
    request = owner.workspace_snapshot()["workspace_join_requests"][0]
    assert bytes.fromhex(request["destination_hash"]) in owner_network.remembered
    approved = owner.approve_workspace_join(
        workspace["id"], request["id"], _op(4)
    )
    assert approved["state"] == "approved"

    controls = _flush(owner, owner_network)
    assert {parse_workspace_payload(_native(item, source=b"\x00" * 16, destination=b"\x01" * 16)).kind for item in controls} == {
        "workspace_manifest_root",
        "workspace_channel_record",
    }
    controls_by_kind = {
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind: item
        for item in controls
    }
    joining_record = joiner._require_workspace(workspace["id"])
    offered_manifest_id = joiner._workspace_manifest_record_id(
        joining_record["manifest_hash"]
    )
    offered_manifest = joiner.store.get("workspace_manifest", offered_manifest_id)
    assert offered_manifest is not None
    joiner.store.delete("workspace_manifest", offered_manifest_id)
    _deliver(
        joiner,
        controls_by_kind["workspace_channel_record"],
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    assert joiner.workspace_snapshot()["workspaces"][0]["general_channel_id"] is None
    assert len(joiner.store.list("workspace_pending_control")) == 1
    assert joiner.workspace_snapshot()["workspaces"][0]["sync_issue"] == "missing_manifest"
    joiner.store.put("workspace_manifest", offered_manifest_id, offered_manifest)
    joiner._drain_workspace_pending_controls(workspace["id"])
    assert joiner.store.list("workspace_pending_control") == []
    assert "sync_issue" not in joiner.workspace_snapshot()["workspaces"][0]
    assert joiner.workspace_snapshot()["workspaces"][0]["general_channel_id"] == (
        workspace["general_channel_id"]
    )
    _deliver(
        joiner,
        controls_by_kind["workspace_manifest_root"],
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    joined = joiner.workspace_snapshot()["workspaces"][0]
    assert joined["state"] == "active"
    assert len(joined["members"]) == 2
    channel_id = joined["general_channel_id"]
    assert isinstance(channel_id, str)

    # A current member can sign its own channel record, but it cannot replace
    # the genesis-owner-managed #general control.
    joined_manifest = joiner._workspace_current_manifest(
        joiner._require_workspace(workspace["id"])
    )
    forged_channel = create_workspace_channel_record(
        joiner_identity,
        workspace_id=workspace["id"],
        channel_id=workspace["general_channel_id"],
        manifest_digest=joined_manifest.digest,
        name="general",
        topic="forged topic",
        manager_member_id=joined["local_member_id"],
        manager_device_id=joined["local_device_id"],
    )
    assert not owner._receive_workspace_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_record",
            logical_id=_op(400),
            workspace_id=workspace["id"],
            expires_at=int(time.time()) + 60,
            document=forged_channel,
        )
    )
    assert owner._require_workspace(workspace["id"])["state"] == "active"

    event = owner.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Water level is stable.",
        _op(5),
        _op(6),
    )
    assert event["delivery_summary"]["devices_total"] == 1
    sent_event = _flush(owner, owner_network)[0]
    _deliver(
        joiner,
        sent_event,
        source_profile=owner_profile,
        recipient_profile=joiner_profile,
    )
    page = joiner.list_workspace_messages(joined["id"], channel_id, limit=50)
    assert [item["text"] for item in page["messages"]] == ["Water level is stable."]
    assert joiner.snapshot()["messages"] == []
    assert "workspace_messages" not in joiner.snapshot()

    delivery = next(
        item
        for item in owner.store.list("workspace_delivery")
        if item.get("event_id") == event["id"]
    )
    original_list = owner.store.list

    def bounded_list(kind: str) -> list[dict[str, Any]]:
        assert kind != "workspace_delivery", "receipt handling must not scan deliveries"
        return original_list(kind)

    monkeypatch.setattr(owner.store, "list", bounded_list)
    assert owner._on_workspace_native_status(
        delivery["id"], DeliveryState.RECEIVED_BY_ENDPOINT, delivery.get("native_message_id")
    )
    owner_page = owner.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )
    assert owner_page["messages"][0]["delivery_summary"] == {
        "people_total": 1,
        "people_reached": 1,
        "people_partial": 0,
        "people_pending": 0,
        "people_failed": 0,
        "devices_total": 1,
        "devices_reached": 1,
        "devices_pending": 0,
        "devices_failed": 0,
        "devices_expired": 0,
        "devices_cancelled": 0,
    }
    monkeypatch.setattr(owner.store, "list", original_list)

    owner.close()
    joiner.close()


def test_workspace_mutations_converge_and_survive_restart_under_posting_policy(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "mutations", base=1_800)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    owner.update_workspace_policies(
        workspace_id, "all_members", "owner_and_admins", _op(1_804)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    message = owner.send_workspace_message(
        workspace_id, channel_id, "Initial field note", _op(1_805), _op(1_806)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    with pytest.raises(ContactNotApproved, match="author"):
        member.edit_workspace_message(
            workspace_id, message["id"], "Unauthorized", _op(1_807), _op(1_808)
        )

    reacted = member.set_workspace_reaction(
        workspace_id, message["id"], "👍", True, _op(1_809), _op(1_810)
    )
    assert reacted["reactions"] == [
        {"emoji": "👍", "count": 1, "reacted_by_self": True}
    ]
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    member.set_workspace_reaction(
        workspace_id, message["id"], "❤️", True, _op(1_817), _op(1_818)
    )
    member.set_workspace_reaction(
        workspace_id, message["id"], "👍", False, _op(1_819), _op(1_820)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    owner_reacted = owner.list_workspace_messages(workspace_id, channel_id)[
        "messages"
    ][0]
    assert owner_reacted["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_self": False}
    ]

    edited = owner.edit_workspace_message(
        workspace_id,
        message["id"],
        "Corrected field note",
        _op(1_811),
        _op(1_812),
    )
    assert edited["text"] == "Corrected field note"
    assert edited["revision"] == 1
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    deleted = owner.delete_workspace_message(
        workspace_id, message["id"], _op(1_813), _op(1_814)
    )
    assert deleted["deleted"] is True
    assert deleted["text"] == ""
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    page = member.list_workspace_messages(workspace_id, channel_id)
    assert page["high_water"] == 1
    assert len(page["messages"]) == 1
    assert page["messages"][0]["deleted"] is True
    assert page["messages"][0]["revision"] == 2
    with pytest.raises(ContactNotApproved, match="deleted"):
        member.set_workspace_reaction(
            workspace_id, message["id"], "❤️", True, _op(1_815), _op(1_816)
        )

    member.close()
    member, _member_network = _service(
        tmp_path / "mutations" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.list_workspace_messages(workspace_id, channel_id)["messages"]
    assert len(restarted) == 1
    assert restarted[0]["deleted"] is True
    assert restarted[0]["revision"] == 2
    assert restarted[0]["reactions"] == [
        {"emoji": "❤️", "count": 1, "reacted_by_self": True}
    ]
    owner.close()
    member.close()


def test_concurrent_workspace_edits_resolve_then_same_device_equivocation_freezes(
    tmp_path: Path,
) -> None:
    (
        owner,
        _owner_network,
        _owner_profile,
        member,
        _member_network,
        _member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "concurrent-mutations", base=1_900)
    workspace_id = workspace["id"]
    message = owner.send_workspace_message(
        workspace_id,
        workspace["general_channel_id"],
        "Shared draft",
        _op(1_906),
        _op(1_907),
    )
    record_id = owner._workspace_message_record_id(message["id"])
    original = owner.store.get("workspace_message_state", record_id)
    assert original is not None

    def edit_candidate(
        event_id: str,
        digest: str,
        destination_byte: int,
        base_revision: int,
        revision: int,
        text: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            event_id=event_id,
            digest=digest,
            event_type="edit",
            base_revision=base_revision,
            revision=revision,
            author_destination=bytes([destination_byte]) * 16,
            created_at=1_800_000_000 + revision,
            text=text,
            reaction_active=None,
        )

    first = edit_candidate(_op(1_908), "aa" * 32, 1, 0, 1, "Device one")
    second = edit_candidate(_op(1_909), "bb" * 32, 2, 0, 1, "Device two")
    first_then_second = owner._apply_workspace_message_mutation(
        owner._apply_workspace_message_mutation(dict(original), first), second
    )
    second_then_first = owner._apply_workspace_message_mutation(
        owner._apply_workspace_message_mutation(dict(original), second), first
    )
    assert first_then_second["text"] == second_then_first["text"]
    assert first_then_second["revision"] == 1
    assert first_then_second["mutation_conflict"] is True

    resolution = edit_candidate(
        _op(1_910), "cc" * 32, 2, 1, 2, "Merged resolution"
    )
    resolved = owner._apply_workspace_message_mutation(
        first_then_second, resolution
    )
    assert resolved["text"] == "Merged resolution"
    assert resolved["mutation_conflict"] is False

    equivocation = edit_candidate(
        _op(1_911), "dd" * 32, 2, 1, 2, "Conflicting device-two value"
    )
    frozen = owner._apply_workspace_message_mutation(resolved, equivocation)
    assert frozen["mutation_frozen"] is True
    owner.store.put("workspace_message_state", record_id, frozen)
    with pytest.raises(ContactNotApproved, match="frozen"):
        owner.edit_workspace_message(
            workspace_id, message["id"], "Too late", _op(1_912), _op(1_913)
        )
    owner.close()
    member.close()


def test_out_of_order_workspace_mutations_wait_for_predecessor_and_converge(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        _member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "out-of-order-mutations", base=1_950)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    message = owner.send_workspace_message(
        workspace_id, channel_id, "Revision zero", _op(1_954), _op(1_955)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    owner.edit_workspace_message(
        workspace_id, message["id"], "Revision one", _op(1_956), _op(1_957)
    )
    owner.edit_workspace_message(
        workspace_id, message["id"], "Revision two", _op(1_958), _op(1_959)
    )
    mutation_packets = _flush(owner, owner_network)
    assert len(mutation_packets) == 2
    _deliver(
        member,
        mutation_packets[1],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    assert member.list_workspace_messages(workspace_id, channel_id)["messages"][0][
        "text"
    ] == "Revision zero"
    _deliver(
        member,
        mutation_packets[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.store.list("workspace_pending_event") == []
    converged = member.list_workspace_messages(workspace_id, channel_id)["messages"]
    assert len(converged) == 1
    assert converged[0]["text"] == "Revision two"
    assert converged[0]["revision"] == 2
    _deliver(
        member,
        mutation_packets[1],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, channel_id)["messages"] == converged
    owner.close()
    member.close()


def test_workspace_direct_chat_hide_reopen_restart_and_removal(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path, base=450)
    workspace_id = workspace["id"]
    owner_view = owner.workspace_snapshot()["workspaces"][0]
    member_id = next(
        item["id"]
        for item in owner_view["members"]
        if item["id"] != owner_view["local_member_id"]
    )
    assert owner.snapshot()["contacts"] == []
    assert member.snapshot()["contacts"] == []

    opened, _ = owner.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-open",
            "command": "open_workspace_direct",
            "payload": {
                "operation_id": _op(454),
                "workspace_id": workspace_id,
                "member_id": member_id,
            },
        }
    )
    direct = opened["result"]
    assert direct["peer_display_name"] == "Bailey"
    assert owner.workspace_snapshot()["workspace_directs"] == [direct]
    assert member.workspace_snapshot()["workspace_directs"] == []

    first = owner.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Private field note",
        _op(455),
        _op(456),
        [member_id],
    )
    assert first["delivery_summary"]["devices_total"] == 1
    outgoing = _flush(owner, owner_network)
    assert len(outgoing) == 1
    _deliver(
        member,
        outgoing[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_direct = member.workspace_snapshot()["workspace_directs"][0]
    assert member_direct["id"] == direct["id"]
    assert member_direct["unread_count"] == 1
    marked, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-read",
            "command": "mark_workspace_direct_read",
            "payload": {
                "operation_id": _op(469),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
                "high_water": 1,
            },
        }
    )
    assert marked["result"]["high_water"] == 1
    assert member.workspace_snapshot()["workspace_directs"][0]["unread_count"] == 0
    assert [
        item["text"]
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note"]

    owner.edit_workspace_message(
        workspace_id,
        first["id"],
        "Private field note revised",
        _op(471),
        _op(472),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, direct["id"])[
        "messages"
    ][0]["text"] == "Private field note revised"
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [first["id"]]
    member.set_workspace_reaction(
        workspace_id, first["id"], "✅", True, _op(473), _op(474)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner.list_workspace_messages(workspace_id, direct["id"])[
        "messages"
    ][0]["reactions"] == [
        {"emoji": "✅", "count": 1, "reacted_by_self": False}
    ]

    reply = member.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Acknowledged",
        _op(457),
        _op(458),
    )
    reply_packets = _flush(member, member_network)
    assert len(reply_packets) == 1
    _deliver(
        owner,
        reply_packets[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert [
        item["text"]
        for item in owner.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note revised", "Acknowledged"]

    hidden, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-hide",
            "command": "hide_workspace_direct",
            "payload": {
                "operation_id": _op(459),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
            },
        }
    )
    assert hidden["result"]["hidden"] is True
    assert member.workspace_snapshot()["workspace_directs"] == []
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []
    member_workspace = member.workspace_snapshot()["workspaces"][0]
    reopened = member.open_workspace_direct(
        workspace_id, member_workspace["owner_member_id"], _op(460)
    )
    assert reopened["id"] == direct["id"]
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [first["id"]]
    saved_draft, _ = member.dispatch(
        {
            "v": 1,
            "id": "workspace-direct-draft",
            "command": "save_workspace_direct_draft",
            "payload": {
                "operation_id": _op(461),
                "workspace_id": workspace_id,
                "conversation_id": direct["id"],
                "text": "Restart-safe draft",
            },
        }
    )
    assert saved_draft["result"]["text"] == "Restart-safe draft"
    member.close()

    member, member_network = _service(
        tmp_path / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.workspace_snapshot()
    assert restarted["workspace_directs"][0]["id"] == direct["id"]
    assert restarted["workspace_drafts"] == [
        {
            "workspace_id": workspace_id,
            "conversation_id": direct["id"],
            "text": "Restart-safe draft",
        }
    ]
    assert [
        item["text"]
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
    ] == ["Private field note revised", "Acknowledged"]

    pending = member.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Queued before removal",
        _op(462),
        _op(463),
    )
    pending_packets = _flush(member, member_network)
    assert len(pending_packets) == 1
    owner.remove_workspace_member(workspace_id, member_id, _op(464))
    removal_packets = _flush(owner, owner_network)
    removal_manifest = next(
        item
        for item in removal_packets
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_manifest_root"
    )
    _deliver(
        member,
        removal_manifest,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    pending_delivery = next(
        item
        for item in member.store.list("workspace_delivery")
        if item.get("event_id") == pending["id"]
    )
    assert pending_delivery["state"] == DeliveryState.CANCELLED.value
    pending_message = next(
        item
        for item in member.list_workspace_messages(
            workspace_id, direct["id"]
        )["messages"]
        if item["id"] == pending["id"]
    )
    assert pending_message["deliveries"] == [
        {
            "device_id": owner._require_workspace(workspace_id)["local_device_id"],
            "device_short_id": owner._require_workspace(workspace_id)[
                "local_device_id"
            ].replace("-", "")[:6],
            "member_id": owner._require_workspace(workspace_id)["local_member_id"],
            "member_display_name": "Alex",
            "state": DeliveryState.CANCELLED.value,
        }
    ]
    assert member.workspace_snapshot()["workspace_directs"][0]["state"] == "read_only"
    assert owner.workspace_snapshot()["workspace_directs"][0]["state"] == "read_only"
    owner_message_count = len(
        owner.list_workspace_messages(workspace_id, direct["id"])["messages"]
    )
    _deliver(
        owner,
        pending_packets[0],
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert len(
        owner.list_workspace_messages(workspace_id, direct["id"])["messages"]
    ) == owner_message_count
    with pytest.raises(ContactNotApproved):
        owner.send_workspace_direct_message(
            workspace_id,
            direct["id"],
            "Too late",
            _op(465),
            _op(466),
        )
    with pytest.raises(ContactNotApproved):
        member.send_workspace_direct_message(
            workspace_id,
            direct["id"],
            "Also too late",
            _op(467),
            _op(468),
        )
    assert owner.snapshot()["contacts"] == []
    assert member.snapshot()["contacts"] == []
    assert reply["conversation_id"] == direct["id"]
    removed = member.remove_workspace_data(workspace_id, workspace_id, _op(470))
    assert removed == {"workspace_id": workspace_id, "removed": True}
    assert member.store.list("workspace_direct") == []
    assert member.store.list("workspace_draft") == []
    owner.close()
    member.close()


def test_unauthorized_manifest_cannot_fork_and_nonmember_sources_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_identity = RNS.Identity()
    attacker = RNS.Identity()
    service, _network = _service(tmp_path / "manifest-guard", owner_identity, "Alex")
    workspace = service.create_workspace(_op(500), "Guarded", "")
    stored = service._require_workspace(workspace["id"])
    genesis = verify_workspace_genesis(stored["genesis"])
    attacker_member_id = _op(501)
    attacker_device_id = _op(502)
    attacker_card = create_workspace_device_card(
        attacker,
        workspace_id=workspace["id"],
        member_id=attacker_member_id,
        device_id=attacker_device_id,
        display_name="Mallory",
    )
    forged = create_workspace_manifest(
        attacker,
        workspace_id=workspace["id"],
        epoch=1,
        previous_manifest_hash=genesis.digest,
        name="Guarded",
        description="",
        authority_device_id=attacker_device_id,
        members=[
            WorkspaceManifestMemberInput(
                attacker_member_id,
                "Mallory",
                "owner",
                [attacker_card],
            )
        ],
    )
    wire = WorkspaceWirePayload(
        kind="workspace_manifest_root",
        logical_id=_op(503),
        workspace_id=workspace["id"],
        expires_at=int(time.time()) + 60,
        document=forged,
    )
    assert not service._receive_workspace_manifest(wire)
    assert service._require_workspace(workspace["id"])["state"] == "active"

    received: list[WorkspaceWirePayload] = []
    monkeypatch.setattr(service, "_receive_workspace_manifest", received.append)
    service._receive_workspace_payload(
        SimpleNamespace(
            source_hash=RNS.Destination.hash(attacker, "lxmf", "delivery")
        ),
        wire,
    )
    assert received == []
    service.close()


def test_workspace_decline_is_scoped_and_terminal_close_invalidates_requests(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "scoped-admin", identity, "Alex")
    first = service.create_workspace(_op(600), "First", "")
    second = service.create_workspace(_op(601), "Second", "")
    request_id = service.store.opaque_id("workspace-join", "fixture")
    service.store.put(
        "workspace_join_request",
        request_id,
        {
            "id": request_id,
            "workspace_id": first["id"],
            "state": "pending",
        },
    )
    with pytest.raises(ValidationError, match="no longer pending"):
        service.decline_workspace_join(second["id"], request_id, _op(602))
    assert service.store.get("workspace_join_request", request_id)["state"] == "pending"

    invitation = service.create_workspace_invitation_command(first["id"], _op(603))
    second_invitation = service.create_workspace_invitation_command(
        first["id"], _op(605)
    )
    assert second_invitation["id"] != invitation["id"]
    assert len(service.workspace_snapshot()["workspace_invitations"]) == 2
    expiring = service.store.get("workspace_invitation", invitation["id"])
    expiring["expires_at"] = time.time() - 1
    service.store.put("workspace_invitation", invitation["id"], expiring)
    service._expire_workspace_invitations()
    assert service.store.get("workspace_invitation", invitation["id"])["state"] == "expired"
    assert [
        item["id"]
        for item in service.workspace_snapshot()["workspace_invitations"]
    ] == [second_invitation["id"]]
    service.revoke_workspace_invitation(
        first["id"], second_invitation["id"], _op(606)
    )
    third_invitation = service.create_workspace_invitation_command(
        first["id"], _op(607)
    )
    service.close_workspace(first["id"], _op(604))
    assert service.store.get("workspace_join_request", request_id)["state"] == "closed"
    assert service.store.get("workspace_invitation", invitation["id"])["state"] == "expired"
    assert service.store.get("workspace_invitation", second_invitation["id"])["state"] == "revoked"
    assert service.store.get("workspace_invitation", third_invitation["id"])["state"] == "closed"
    assert service.workspace_snapshot()["workspace_join_requests"] == []
    service.close()


def test_eight_person_workspace_catches_up_concurrent_invites_and_admin_changes(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    owner_root = tmp_path / "owner-eight"
    owner_vault_key = os.urandom(32)
    owner, owner_network = _service(
        owner_root, owner_identity, "Owner", vault_key=owner_vault_key
    )
    owner_profile = owner._require_profile()
    workspace = owner.create_workspace(_op(700), "Field team", "Initial")
    invitations = [
        owner.create_workspace_invitation_command(
            workspace["id"], _op(701 + index)
        )
        for index in range(7)
    ]
    assert len(owner.workspace_snapshot()["workspace_invitations"]) == 7

    peers: list[tuple[MeshChatService, RecordingWorkspaceNetwork, dict[str, Any]]] = []
    peer_identities: list[RNS.Identity] = []
    peer_vault_keys: list[bytes] = []
    by_destination: dict[str, tuple[MeshChatService, dict[str, Any]]] = {}
    for index, invitation in enumerate(invitations):
        identity = RNS.Identity()
        peer_vault_key = os.urandom(32)
        peer_identities.append(identity)
        peer_vault_keys.append(peer_vault_key)
        peer, peer_network = _service(
            tmp_path / f"peer-{index}",
            identity,
            f"Member {index + 1}",
            vault_key=peer_vault_key,
        )
        profile = peer._require_profile()
        peers.append((peer, peer_network, profile))
        by_destination[profile["destination_hash"]] = (peer, profile)
        peer.submit_workspace_join(invitation["text"], _op(720 + index * 3))
        join_payload = _flush(peer, peer_network)
        assert len(join_payload) == 1
        _deliver(
            owner,
            join_payload[0],
            source_profile=profile,
            recipient_profile=owner_profile,
        )
        pending = owner.workspace_snapshot()["workspace_join_requests"]
        request = next(
            item
            for item in pending
            if item["invitation_id"] == invitation["id"]
        )
        owner.approve_workspace_join(
            workspace["id"], request["id"], _op(721 + index * 3)
        )
        controls = _flush(owner, owner_network)
        assert len(controls) == 2 * (index + 1)
        for sent in controls:
            recipient, recipient_profile = by_destination[
                sent["recipient_destination"].hex()
            ]
            _deliver(
                recipient,
                sent,
                source_profile=owner_profile,
                recipient_profile=recipient_profile,
            )
        assert len(peer.workspace_snapshot()["workspaces"][0]["members"]) == (
            index + 2
        )

    assert len(owner.workspace_snapshot()["workspaces"][0]["members"]) == 8
    assert owner.workspace_snapshot()["workspace_invitations"] == []
    assert all(
        len(peer.workspace_snapshot()["workspaces"][0]["members"]) == 8
        for peer, _network, _profile in peers
    )

    owner.update_workspace_metadata(
        workspace["id"], "Field coordination", "Current conditions", _op(760)
    )
    metadata_controls = _flush(owner, owner_network)
    assert len(metadata_controls) == 7
    for sent in metadata_controls:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert all(
        peer.workspace_snapshot()["workspaces"][0]["name"]
        == "Field coordination"
        for peer, _network, _profile in peers
    )

    requester, requester_network, requester_profile = peers[0]
    requester.request_workspace_display_name(
        workspace["id"], "River lead", _op(761)
    )
    request_payload = _flush(requester, requester_network)
    assert len(request_payload) == 1
    _deliver(
        owner,
        request_payload[0],
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    name_request = owner.workspace_snapshot()[
        "workspace_display_name_requests"
    ][0]
    owner.decide_workspace_display_name(
        workspace["id"], name_request["id"], True, _op(762)
    )
    name_controls = _flush(owner, owner_network)
    assert len(name_controls) == 7
    for sent in name_controls:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert requester.workspace_snapshot()["workspace_display_name_requests"] == []
    assert any(
        member["display_name"] == "River lead"
        for member in owner.workspace_snapshot()["workspaces"][0]["members"]
    )

    requester.request_workspace_display_name(
        workspace["id"], "River watch", _op(768)
    )
    declined_request_payload = _flush(requester, requester_network)
    assert len(declined_request_payload) == 1
    _deliver(
        owner,
        declined_request_payload[0],
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    declined_request = owner.workspace_snapshot()[
        "workspace_display_name_requests"
    ][0]
    owner.decide_workspace_display_name(
        workspace["id"], declined_request["id"], False, _op(769)
    )
    decline_payload = _flush(owner, owner_network)
    assert len(decline_payload) == 1
    _deliver(
        requester,
        decline_payload[0],
        source_profile=owner_profile,
        recipient_profile=requester_profile,
    )
    assert requester.workspace_snapshot()["workspace_display_name_requests"] == []

    target = peers[-1][0].workspace_snapshot()["workspaces"][0]["local_member_id"]
    cancellable = owner.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Membership is changing.",
        _op(763),
        _op(764),
    )
    owner.remove_workspace_member(workspace["id"], target, _op(765))
    materialized = owner.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )["messages"][-1]
    assert materialized["id"] == cancellable["id"]
    assert materialized["delivery_summary"]["devices_cancelled"] == 1
    assert any(
        delivery["member_id"] == target
        and delivery["state"] == DeliveryState.CANCELLED.value
        for delivery in materialized["deliveries"]
    )

    removal_payloads = _flush(owner, owner_network)
    for sent in removal_payloads:
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=owner_profile,
            recipient_profile=recipient_profile,
        )
    assert peers[-1][0].workspace_snapshot()["workspaces"][0]["state"] == "removed"

    # The authority process is actually offline while the member commits this
    # event. Restart the sender before handing off any delivery legs to prove
    # that both the event and its frozen recipient set survive restart.
    owner.close()
    member_message = requester.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Owner can catch up later.",
        _op(766),
        _op(767),
    )
    requester.close()
    requester, requester_network = _service(
        tmp_path / "peer-0",
        peer_identities[0],
        "Member 1",
        vault_key=peer_vault_keys[0],
    )
    peers[0] = (requester, requester_network, requester_profile)
    assert any(
        message["id"] == member_message["id"]
        for message in requester.list_workspace_messages(
            workspace["id"], workspace["general_channel_id"]
        )["messages"]
    )
    member_payloads = _flush(requester, requester_network)
    delivered_without_owner = 0
    owner_payload: dict[str, Any] | None = None
    for sent in member_payloads:
        if sent["recipient_destination"].hex() == owner_profile["destination_hash"]:
            owner_payload = sent
            continue
        recipient, recipient_profile = by_destination[
            sent["recipient_destination"].hex()
        ]
        _deliver(
            recipient,
            sent,
            source_profile=requester_profile,
            recipient_profile=recipient_profile,
        )
        delivered_without_owner += 1
    assert delivered_without_owner == 5
    assert owner_payload is not None
    assert all(
        any(
            message["id"] == member_message["id"]
            for message in peer.list_workspace_messages(
                workspace["id"], workspace["general_channel_id"]
            )["messages"]
        )
        for peer, _network, _profile in peers[1:-1]
    )

    # Reconnect a restarted authority endpoint and deliver the exact canonical
    # event it missed during the partition. The owner catches up without being
    # required for the member-to-member exchange.
    owner, owner_network = _service(
        owner_root, owner_identity, "Owner", vault_key=owner_vault_key
    )
    _deliver(
        owner,
        owner_payload,
        source_profile=requester_profile,
        recipient_profile=owner_profile,
    )
    assert any(
        message["id"] == member_message["id"]
        for message in owner.list_workspace_messages(
            workspace["id"], workspace["general_channel_id"]
        )["messages"]
    )

    owner.close()
    for peer, _network, _profile in peers:
        peer.close()


def test_workspace_messages_are_paged_with_mac_bound_stale_cursors(tmp_path: Path) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "pager", identity, "Alex")
    workspace = service.create_workspace(_op(20), "Pager", "")
    for index in range(55):
        service.send_workspace_message(
            workspace["id"],
            workspace["general_channel_id"],
            f"Message {index}",
            _op(100 + index),
            _op(200 + index),
        )
    first = service.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"], limit=50
    )
    assert len(first["messages"]) == 50
    assert first["messages"][-1]["text"] == "Message 54"
    second = service.list_workspace_messages(
        workspace["id"],
        workspace["general_channel_id"],
        cursor=first["next_cursor"],
        limit=50,
    )
    assert [item["text"] for item in second["messages"]] == [
        f"Message {index}" for index in range(5)
    ]

    stored = service._require_workspace(workspace["id"])
    stored["authorization_generation"] += 1
    service.store.put("workspace", service._workspace_record_id(workspace["id"]), stored)
    with pytest.raises(ValidationError, match="stale"):
        service.list_workspace_messages(
            workspace["id"],
            workspace["general_channel_id"],
            cursor=first["next_cursor"],
        )
    service.close()


def test_local_workspace_removal_redacts_duplicate_operation_results(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "removal", identity, "Alex")
    workspace = service.create_workspace(_op(300), "Private cleanup", "Erase this")
    service.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "Sensitive workspace text",
        _op(301),
        _op(302),
    )
    service.store.remember_command(
        "renderer-request", {"ok": True, "result": {"text": "Sensitive workspace text"}}
    )
    service.close_workspace(workspace["id"], _op(303))
    result = service.remove_workspace_data(
        workspace["id"], workspace["id"], _op(304)
    )
    assert result == {"workspace_id": workspace["id"], "removed": True}
    assert service.workspace_snapshot()["workspaces"] == []
    retained_operations = repr(service.store.items("workspace_operation"))
    assert "Sensitive workspace text" not in retained_operations
    assert "Private cleanup" not in retained_operations
    assert service.store.command_response("renderer-request")["error"]["code"] == (
        "command_result_deleted"
    )
    service.close()


def test_public_channel_control_before_data_unread_restart_and_full_lifecycle(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "lifecycle", base=1_000)
    workspace_id = workspace["id"]
    member_id = member._require_workspace(workspace_id)["local_member_id"]

    channel = owner.create_workspace_channel(
        workspace_id, "Field notes", "Daily observations", _op(1_010)
    )
    channel_controls = _flush(owner, owner_network)
    assert len(channel_controls) == 1
    first = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Control arrives second.",
        _op(1_011),
        _op(1_012),
    )
    first_events = _flush(owner, owner_network)
    assert len(first_events) == 1
    _deliver(
        member,
        first_events[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    _deliver(
        member,
        channel_controls[0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.store.list("workspace_pending_event") == []
    assert [
        item["text"]
        for item in member.list_workspace_messages(workspace_id, channel["id"])[
            "messages"
        ]
    ] == [first["text"]]
    discovered = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert discovered["subscribed"] is False
    assert discovered["unread_count"] == 0

    member.set_workspace_channel_subscription(
        workspace_id, channel["id"], True, _op(1_013)
    )
    owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "Now count this message.",
        _op(1_014),
        _op(1_015),
    )
    message_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in message_items
    ] == ["workspace_event"]
    for item in message_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    subscribed = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert subscribed["unread_count"] == 1
    member.close()
    member, member_network = _service(
        tmp_path / "lifecycle" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    persisted = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert persisted["subscribed"] is True
    assert persisted["unread_count"] == 1

    renamed = owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        "Field reports",
        "Validated daily observations",
        False,
        _op(1_016),
    )
    rename_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in rename_items
    ] == ["workspace_channel_record"]
    for item in rename_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert renamed["version"] == 2
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )["version"] == 2
    offer = owner.offer_workspace_channel_transfer(
        workspace_id, channel["id"], member_id, _op(1_017)
    )
    offer_items = _flush(owner, owner_network)
    assert [
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in offer_items
    ] == ["workspace_channel_transfer_offer"]
    for item in offer_items:
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    transfer = next(
        item
        for item in member.workspace_snapshot()["workspace_channel_transfers"]
        if item["channel_id"] == channel["id"]
        and item["successor_member_id"] == member_id
    )
    accepted = member.accept_workspace_channel_transfer(
        workspace_id, transfer["id"], _op(1_018)
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert accepted["manager_member_id"] == member_id
    managed = member.update_workspace_channel(
        workspace_id,
        channel["id"],
        "Field reports",
        "Managed by Bailey",
        False,
        _op(1_019),
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert managed["topic"] == "Managed by Bailey"
    recovered = owner.recover_workspace_channel(
        workspace_id, channel["id"], _op(1_020)
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert recovered["manager_member_id"] == workspace["local_member_id"]
    archived = owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        recovered["name"],
        recovered["topic"],
        True,
        _op(1_021),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert archived["state"] == "archived"
    with pytest.raises(ContactNotApproved, match="not active"):
        owner.update_workspace_channel(
            workspace_id,
            channel["id"],
            "Cannot reopen",
            "Terminal",
            False,
            _op(1_022),
        )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )["state"] == "archived"
    owner.close()
    member.close()


def test_partitioned_channel_summary_fetch_converges_and_disambiguates_names(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "discovery", base=1_100)
    workspace_id = workspace["id"]
    first = owner.create_workspace_channel(
        workspace_id, "Ops", "North team", _op(1_110)
    )
    second = owner.create_workspace_channel(
        workspace_id, "ops", "South team", _op(1_111)
    )
    assert owner.sync_workspace_channels(workspace_id, _op(1_112))["state"] == (
        "incomplete"
    )
    partitioned = _flush(owner, owner_network)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in partitioned:
        kind = parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        by_kind.setdefault(kind, []).append(item)
    assert len(by_kind["workspace_channel_record"]) == 2
    assert len(by_kind["workspace_channel_summary"]) == 1

    # Simulate a partition dropping the direct controls while the later signed
    # summary reaches the member. The member must explicitly fetch the chain.
    _deliver(
        member,
        by_kind["workspace_channel_summary"][0],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert {
        item["name"] for item in member.workspace_snapshot()["workspace_channels"]
    } == {"general"}
    member_sync = _flush(member, member_network)
    assert {
        parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for item in member_sync
    } == {"workspace_channel_fetch", "workspace_channel_summary"}
    for item in member_sync:
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )

    discovered = [
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] in {first["id"], second["id"]}
    ]
    assert len(discovered) == 2
    assert all(item["duplicate_name"] for item in discovered)
    assert len({item["display_name"] for item in discovered}) == 2
    assert all(item["short_id"] in item["display_name"] for item in discovered)
    assert all(item["subscribed"] is False for item in discovered)
    stable_labels = {item["id"]: item["display_name"] for item in discovered}
    assert member._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert owner._require_workspace(workspace_id)["channel_discovery"] == (
        "incomplete"
    )

    # A second summary after the fetch proves both reachable peers now expose
    # the same bounded directory.
    member.sync_workspace_channels(workspace_id, _op(1_113))
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    assert owner._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert member._require_workspace(workspace_id)["channel_discovery"] == (
        "converged"
    )
    assert {
        item["id"]: item["display_name"]
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] in stable_labels
    } == stable_labels

    member.set_workspace_channel_subscription(
        workspace_id, first["id"], True, _op(1_114)
    )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == first["id"]
    )["subscribed"] is True
    member.set_workspace_channel_subscription(
        workspace_id, first["id"], False, _op(1_115)
    )
    assert next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == first["id"]
    )["subscribed"] is False
    owner.close()
    member.close()


def test_channel_policies_reject_members_and_valid_same_version_conflict_forks_only_channel(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "policies", base=1_200)
    workspace_id = workspace["id"]
    owner.update_workspace_policies(
        workspace_id,
        "owner_and_admins",
        "owner_and_admins",
        _op(1_210),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    with pytest.raises(ContactNotApproved, match="owner"):
        member.create_workspace_channel(
            workspace_id, "Denied", "Policy test", _op(1_211)
        )
    with pytest.raises(ContactNotApproved, match="owner"):
        member.send_workspace_message(
            workspace_id,
            workspace["general_channel_id"],
            "Disallowed post",
            _op(1_212),
            _op(1_213),
        )
    restricted_workspace = member._require_workspace(workspace_id)
    restricted_manifest = member._workspace_current_manifest(restricted_workspace)
    restricted_channel = member._workspace_channel_by_digest(
        member._require_workspace_channel(
            workspace_id, workspace["general_channel_id"]
        )["head_hash"]
    )
    assert member._identity is not None and restricted_channel is not None
    disallowed_event = create_workspace_event(
        member._identity,
        workspace_id=workspace_id,
        conversation_id=workspace["general_channel_id"],
        event_id=_op(1_222),
        author_member_id=restricted_workspace["local_member_id"],
        author_device_id=restricted_workspace["local_device_id"],
        sequence=1,
        previous_event_digest=None,
        manifest_digest=restricted_manifest.digest,
        channel_digest=restricted_channel.digest,
        text="Signed but forbidden by policy",
    )
    assert not owner._accept_workspace_event(
        WorkspaceWirePayload(
            kind="workspace_event",
            logical_id=_op(1_223),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=disallowed_event,
        )
    )
    assert owner.list_workspace_messages(
        workspace_id, workspace["general_channel_id"]
    )["messages"] == []

    owner.update_workspace_policies(
        workspace_id,
        "all_members",
        "all_members",
        _op(1_214),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    member_channel = member.create_workspace_channel(
        workspace_id, "Member channel", "Allowed by policy", _op(1_215)
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    member.send_workspace_message(
        workspace_id,
        member_channel["id"],
        "Member-created and member-posted.",
        _op(1_216),
        _op(1_217),
    )
    for item in _flush(member, member_network):
        _deliver(
            owner,
            item,
            source_profile=member_profile,
            recipient_profile=owner_profile,
        )
    assert owner.list_workspace_messages(
        workspace_id, member_channel["id"]
    )["messages"][0]["text"] == "Member-created and member-posted."

    channel = owner.create_workspace_channel(
        workspace_id, "Fork test", "First head", _op(1_218)
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    initial = owner._workspace_channel_by_digest(channel["head_hash"])
    assert initial is not None
    owner.update_workspace_channel(
        workspace_id,
        channel["id"],
        channel["name"],
        "Accepted second head",
        False,
        _op(1_219),
    )
    for item in _flush(owner, owner_network):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    manifest = owner._workspace_current_manifest(owner._require_workspace(workspace_id))
    assert owner._identity is not None
    conflicting = create_workspace_channel_record(
        owner._identity,
        workspace_id=workspace_id,
        channel_id=channel["id"],
        manifest_digest=manifest.digest,
        name=channel["name"],
        topic="Conflicting second head",
        manager_member_id=initial.manager_member_id,
        manager_device_id=initial.manager_device_id,
        version=2,
        previous_hash=initial.digest,
    )
    assert not member._receive_workspace_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_record",
            logical_id=_op(1_220),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=conflicting,
        )
    )
    assert member._require_workspace(workspace_id)["state"] == "active"
    assert member._require_workspace_channel(workspace_id, channel["id"])[
        "state"
    ] == "forked"
    with pytest.raises(ContactNotApproved, match="always subscribed"):
        member.set_workspace_channel_subscription(
            workspace_id, workspace["general_channel_id"], False, _op(1_221)
        )
    owner.close()
    member.close()


def test_archived_channels_release_active_capacity_and_directory_summary_pages(
    tmp_path: Path,
) -> None:
    identity = RNS.Identity()
    service, _network = _service(tmp_path / "channel-capacity", identity, "Alex")
    workspace = service.create_workspace(_op(1_300), "Capacity", "")
    channels = [
        service.create_workspace_channel(
            workspace["id"], f"channel-{index:02d}", "", _op(1_301 + index)
        )
        for index in range(31)
    ]
    with pytest.raises(ValidationError, match="at most 32"):
        service.create_workspace_channel(
            workspace["id"], "one-too-many", "", _op(1_340)
        )
    first = channels[0]
    service.update_workspace_channel(
        workspace["id"],
        first["id"],
        first["name"],
        first["topic"],
        True,
        _op(1_341),
    )
    service.create_workspace_channel(
        workspace["id"], "replacement", "", _op(1_342)
    )
    stored_workspace = service._require_workspace(workspace["id"])
    manifest = service._workspace_current_manifest(stored_workspace)
    assert service._identity is not None
    pages = service._workspace_channel_summary_documents(
        stored_workspace, manifest, service._identity, _op(1_343)
    )
    assert len(pages) == 2
    snapshot_channels = service.workspace_snapshot()["workspace_channels"]
    assert len(snapshot_channels) == 33
    assert sum(item["state"] == "active" for item in snapshot_channels) == 32
    assert service.sync_workspace_channels(workspace["id"], _op(1_344))[
        "state"
    ] == "converged"
    service.close()


def test_private_channel_membership_audience_transfer_recovery_leave_and_privacy(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path, base=3000)
    workspace_id = workspace["id"]
    owner_workspace = owner._require_workspace(workspace_id)
    member_workspace = member._require_workspace(workspace_id)
    owner_id = owner_workspace["local_member_id"]
    member_id = member_workspace["local_member_id"]

    private = owner.create_workspace_channel(
        workspace_id,
        "incident-room",
        "Need-to-know coordination",
        _op(3010),
        "private",
        [owner_id],
    )
    private_id = private["id"]
    assert private["visibility"] == "private"
    assert private["member_ids"] == [owner_id]
    assert _flush(owner, owner_network) == []
    assert owner._identity is not None
    assert all(
        private_id not in document
        for document in owner._workspace_channel_summary_documents(
            owner_workspace,
            owner._workspace_current_manifest(owner_workspace),
            owner._identity,
            _op(3011),
        )
    )

    owner.send_workspace_message(
        workspace_id, private_id, "before admission", _op(3012), _op(3013)
    )
    assert _flush(owner, owner_network) == []

    owner.update_workspace_private_channel_members(
        workspace_id, private_id, [owner_id, member_id], _op(3014)
    )
    admission_controls = _flush(owner, owner_network)
    assert len(admission_controls) == 1
    assert {
        parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        for packet in admission_controls
    } == {"workspace_channel_manifest"}
    after_admission_message = owner.send_workspace_message(
        workspace_id, private_id, "after admission", _op(3015), _op(3016)
    )
    post_admission = _flush(owner, owner_network)
    assert len(post_admission) == 1
    # Data can arrive before its private admission checkpoint. It remains
    # encrypted and inert across restart until the signed control validates.
    _deliver_all(
        member,
        post_admission,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert len(member.store.list("workspace_pending_event")) == 1
    assert private_id not in str(member.workspace_snapshot())
    member.close()
    member, member_network = _service(
        tmp_path / "member", member_identity, "Bailey", vault_key=member_key
    )
    member_profile = member._require_profile()
    assert len(member.store.list("workspace_pending_event")) == 1
    _deliver_all(
        member,
        admission_controls,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_private = next(
        channel
        for channel in member.workspace_snapshot()["workspace_channels"]
        if channel["id"] == private_id
    )
    assert member_private["member_ids"] == sorted([owner_id, member_id])
    assert member_private["unread_count"] == 1
    assert member.store.list("workspace_pending_control") == []
    assert member.store.list("workspace_pending_event") == []
    _deliver_all(
        member,
        admission_controls,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission"]

    owner.edit_workspace_message(
        workspace_id,
        after_admission_message["id"],
        "after admission revised",
        _op(3033),
        _op(3034),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, private_id)["messages"][0][
        "text"
    ] == "after admission revised"

    owner.send_workspace_message(
        workspace_id, private_id, "delayed across metadata", _op(3026), _op(3027)
    )
    owner.update_workspace_channel(
        workspace_id,
        private_id,
        "incident-room",
        "Updated need-to-know coordination",
        False,
        _op(3028),
    )
    delayed_packets = _flush(owner, owner_network)
    delayed_controls = [
        packet
        for packet in delayed_packets
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_channel_manifest"
    ]
    delayed_events = [
        packet
        for packet in delayed_packets
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_event"
    ]
    assert len(delayed_controls) == len(delayed_events) == 1
    _deliver_all(
        member,
        [*delayed_controls, *delayed_events],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission revised", "delayed across metadata"]

    owner.offer_workspace_channel_transfer(
        workspace_id, private_id, member_id, _op(3017)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    transfer = next(
        item
        for item in member.workspace_snapshot()["workspace_channel_transfers"]
        if item["channel_id"] == private_id
    )
    member.accept_workspace_channel_transfer(
        workspace_id, transfer["id"], _op(3018)
    )
    _deliver_all(
        owner,
        _flush(member, member_network),
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner._require_workspace_channel(workspace_id, private_id)[
        "manager_member_id"
    ] == member_id

    # The channel manager is not a message relay. Existing members keep
    # chatting while that manager is offline, and a rostered owner can sign a
    # recovery that validates when the manager reconnects.
    member.close()
    owner.send_workspace_message(
        workspace_id, private_id, "manager offline", _op(3031), _op(3032)
    )
    manager_offline_event = _flush(owner, owner_network)
    assert len(manager_offline_event) == 1
    owner.recover_workspace_channel(workspace_id, private_id, _op(3019))
    recovery_controls = _flush(owner, owner_network)
    assert len(recovery_controls) == 1
    member, member_network = _service(
        tmp_path / "member", member_identity, "Bailey", vault_key=member_key
    )
    member_profile = member._require_profile()
    _deliver_all(
        member,
        [*recovery_controls, *manager_offline_event],
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member._require_workspace_channel(workspace_id, private_id)[
        "manager_member_id"
    ] == owner_id
    assert [
        message["text"]
        for message in member.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
    ] == ["after admission revised", "delayed across metadata", "manager offline"]

    owner.send_workspace_message(
        workspace_id, private_id, "cancelled on departure", _op(3029), _op(3030)
    )
    member.save_workspace_draft(
        workspace_id,
        private_id,
        "@Alex private draft",
        _op(3035),
        [owner_id],
    )
    assert member.workspace_snapshot()["workspace_drafts"]
    member.leave_workspace_private_channel(workspace_id, private_id, _op(3020))
    assert member.workspace_snapshot()["workspace_drafts"] == []
    leave_packets = _flush(member, member_network)
    assert len(leave_packets) == 1
    _deliver_all(
        owner,
        leave_packets,
        source_profile=member_profile,
        recipient_profile=owner_profile,
    )
    assert owner._require_workspace_channel(workspace_id, private_id)[
        "member_ids"
    ] == [owner_id]
    assert member._require_workspace_channel(workspace_id, private_id)[
        "state"
    ] == "leaving"
    assert _flush(owner, owner_network) == []
    cancelled = next(
        message
        for message in owner.list_workspace_messages(workspace_id, private_id)[
            "messages"
        ]
        if message["text"] == "cancelled on departure"
    )
    assert cancelled["delivery_summary"]["devices_cancelled"] == 1
    owner.send_workspace_message(
        workspace_id, private_id, "after departure", _op(3021), _op(3022)
    )
    assert _flush(owner, owner_network) == []
    owner.update_workspace_channel(
        workspace_id,
        private_id,
        "incident-room",
        "Need-to-know coordination",
        True,
        _op(3023),
    )
    assert owner._require_workspace_channel(workspace_id, private_id)["state"] == "archived"

    member_only = member.create_workspace_channel(
        workspace_id,
        "member-only",
        "Owner is not a member",
        _op(3024),
        "private",
        [member_id],
    )
    member_only_id = member_only["id"]
    assert _flush(member, member_network) == []
    assert owner.store.get(
        "workspace_channel", owner._workspace_channel_record_id(member_only_id)
    ) is None
    assert member_only_id not in str(owner.workspace_snapshot())
    with pytest.raises(ValidationError, match="does not exist"):
        owner.recover_workspace_channel(workspace_id, member_only_id, _op(3025))

    owner.close()
    member.close()


def test_private_channel_fork_is_scoped_and_does_not_freeze_workspace(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    owner, _network = _service(tmp_path / "owner", owner_identity, "Alex")
    workspace = owner.create_workspace(_op(3100), "Fork lab", "Private controls")
    workspace_id = workspace["id"]
    owner_record = owner._require_workspace(workspace_id)
    owner_id = owner_record["local_member_id"]
    original_record = owner.create_workspace_channel(
        workspace_id,
        "incident-room",
        "Original",
        _op(3101),
        "private",
        [owner_id],
    )
    original = owner._workspace_channel_by_digest(original_record["head_hash"])
    assert original is not None
    owner.update_workspace_channel(
        workspace_id,
        original.channel_id,
        "incident-room",
        "First branch",
        False,
        _op(3102),
    )
    conflicting = create_workspace_channel_manifest(
        owner_identity,
        workspace_id=workspace_id,
        channel_id=original.channel_id,
        manifest_digest=original.manifest_digest,
        name="incident-room",
        topic="Conflicting branch",
        manager_member_id=original.manager_member_id,
        manager_device_id=original.manager_device_id,
        member_ids=original.member_ids,
        version=original.version + 1,
        previous_hash=original.digest,
        now=time.time(),
    )
    assert not owner._receive_workspace_private_channel(
        WorkspaceWirePayload(
            kind="workspace_channel_manifest",
            logical_id=_op(3103),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 3600,
            document=conflicting,
        )
    )
    assert owner._require_workspace_channel(workspace_id, original.channel_id)[
        "state"
    ] == "forked"
    assert owner._require_workspace(workspace_id)["state"] == "active"
    owner.close()


def test_structured_mentions_unsubscribed_mute_read_draft_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "mentions", base=4_000)
    workspace_id = workspace["id"]
    owner_workspace = owner.workspace_snapshot()["workspaces"][0]
    member_workspace = member.workspace_snapshot()["workspaces"][0]
    owner_id = owner_workspace["local_member_id"]
    member_id = member_workspace["local_member_id"]

    channel = owner.create_workspace_channel(
        workspace_id, "field-alerts", "Unsubscribed alerts", _op(4_010)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    member_channel = next(
        item
        for item in member.workspace_snapshot()["workspace_channels"]
        if item["id"] == channel["id"]
    )
    assert member_channel["subscribed"] is False
    assert member_channel["mentions_muted"] is False

    raw_text = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey raw text does not create a mention",
        _op(4_011),
        _op(4_012),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []

    first = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey inspect the north gauge",
        _op(4_013),
        _op(4_014),
        [member_id],
    )
    second = owner.send_workspace_message(
        workspace_id,
        channel["id"],
        "@Bailey confirm the reading",
        _op(4_015),
        _op(4_016),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    snapshot = member.workspace_snapshot()
    assert snapshot["workspaces"][0]["mention_unread_count"] == 2
    assert member._require_workspace(workspace_id)["mention_unread_count"] == 2
    original_get = member.store.get
    with monkeypatch.context() as patch:
        def no_message_body_reads(kind: str, record_id: str) -> Any:
            if kind == "workspace_message_state":
                raise AssertionError("workspace startup decrypted a message body")
            return original_get(kind, record_id)

        patch.setattr(member.store, "get", no_message_body_reads)
        assert member.workspace_snapshot()["workspaces"][0][
            "mention_unread_count"
        ] == 2
    assert next(
        item for item in snapshot["workspace_channels"] if item["id"] == channel["id"]
    )["unread_count"] == 0
    first_page = member.list_workspace_mentions(workspace_id, limit=1)
    assert first_page["mentions"][0]["message"]["id"] == second["id"]
    assert first_page["mentions"][0]["read"] is False
    assert first_page["next_cursor"] is not None

    member.set_workspace_channel_mentions_muted(
        workspace_id, channel["id"], True, _op(4_017)
    )
    assert member.workspace_snapshot()["workspaces"][0]["mention_unread_count"] == 0
    assert member.list_workspace_mentions(workspace_id)["mentions"] == []
    with pytest.raises(ValidationError, match="cursor is stale"):
        member.list_workspace_mentions(
            workspace_id, cursor=first_page["next_cursor"], limit=1
        )
    member.set_workspace_channel_mentions_muted(
        workspace_id, channel["id"], False, _op(4_018)
    )
    restored = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in restored["mentions"]] == [
        second["id"],
        first["id"],
    ]
    member.mark_workspace_mentions_read(
        workspace_id, restored["high_water"], _op(4_019)
    )
    assert member.workspace_snapshot()["workspaces"][0]["mention_unread_count"] == 0

    owner.edit_workspace_message(
        workspace_id,
        first["id"],
        "Mention removed by a signed edit",
        _op(4_030),
        _op(4_031),
        [],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert [
        item["message"]["id"]
        for item in member.list_workspace_mentions(workspace_id)["mentions"]
    ] == [second["id"]]

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "@Bailey now added by the structured picker",
        _op(4_032),
        _op(4_033),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    added = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in added["mentions"]] == [
        raw_text["id"],
        second["id"],
    ]
    assert added["unread_count"] == 1

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "Structured mention removed again",
        _op(4_034),
        _op(4_035),
        [],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_mentions(workspace_id)["unread_count"] == 0

    owner.edit_workspace_message(
        workspace_id,
        raw_text["id"],
        "@Bailey re-added without reviving the stale inbox entry",
        _op(4_036),
        _op(4_037),
        [member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    readded = member.list_workspace_mentions(workspace_id)
    assert [item["message"]["id"] for item in readded["mentions"]] == [
        raw_text["id"],
        second["id"],
    ]
    assert readded["unread_count"] == 1
    member.mark_workspace_mentions_read(
        workspace_id, readded["high_water"], _op(4_038)
    )

    draft = member.save_workspace_draft(
        workspace_id,
        channel["id"],
        "@Alex restart-safe structured draft",
        _op(4_020),
        [owner_id],
    )
    assert draft["mention_member_ids"] == [owner_id]
    member.close()
    member, member_network = _service(
        tmp_path / "mentions" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.workspace_snapshot()
    assert restarted["workspaces"][0]["mention_unread_count"] == 0
    assert restarted["workspace_drafts"] == [draft]
    assert all(
        item["read"] for item in member.list_workspace_mentions(workspace_id)["mentions"]
    )

    with pytest.raises(ContactNotApproved, match="cannot read"):
        member.save_workspace_draft(
            workspace_id,
            channel["id"],
            "Invalid structured target",
            _op(4_021),
            [_op(4_099)],
        )
    owner.close()
    member.close()


def test_workspace_threads_out_of_order_mentions_mutations_drafts_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        member_key,
        member_identity,
    ) = _joined_pair(tmp_path / "threads", base=5_000)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    owner_id = owner.workspace_snapshot()["workspaces"][0]["local_member_id"]
    member_id = member.workspace_snapshot()["workspaces"][0]["local_member_id"]

    root = owner.send_workspace_message(
        workspace_id,
        channel_id,
        "Inspect the north relay",
        _op(5_010),
        _op(5_011),
    )
    reply = owner.send_workspace_thread_reply(
        workspace_id,
        channel_id,
        root["id"],
        "@Bailey the thread carries exact audience state",
        _op(5_012),
        _op(5_013),
        [member_id],
    )
    outgoing = _flush(owner, owner_network)
    event_deliveries = []
    for item in outgoing:
        payload = parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        )
        if payload.kind == "workspace_event":
            event_deliveries.append((json.loads(payload.document)["thread_root"], item))
    assert len(event_deliveries) == 2
    delayed_reply = next(item for thread_root, item in event_deliveries if thread_root)
    delayed_root = next(item for thread_root, item in event_deliveries if thread_root is None)
    _deliver(
        member,
        delayed_reply,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_messages(workspace_id, channel_id)["messages"] == []
    _deliver(
        member,
        delayed_root,
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )

    timeline = member.list_workspace_messages(workspace_id, channel_id)
    assert [message["id"] for message in timeline["messages"]] == [root["id"]]
    assert timeline["messages"][0]["reply_count"] == 1
    assert timeline["messages"][0]["thread_unread_count"] == 1
    activity = member.list_workspace_threads(workspace_id)
    assert activity["unread_count"] == 1
    assert activity["threads"][0]["root"]["id"] == root["id"]
    assert activity["threads"][0]["reply_count"] == 1
    thread = member.list_workspace_thread_messages(
        workspace_id, root["id"], limit=1
    )
    assert thread["root"]["text"] == "Inspect the north relay"
    assert [message["id"] for message in thread["replies"]] == [reply["id"]]
    assert thread["conversation"]["kind"] == "channel"
    assert thread["unread_count"] == 1
    mention = member.list_workspace_mentions(workspace_id)["mentions"][0]
    assert mention["message"]["id"] == reply["id"]
    assert mention["thread_root_id"] == root["id"]

    with pytest.raises(ContactNotApproved, match="unavailable"):
        member.send_workspace_thread_reply(
            workspace_id,
            channel_id,
            reply["id"],
            "Nested replies are forbidden",
            _op(5_014),
            _op(5_015),
        )

    hidden_reply = owner.send_workspace_thread_reply(
        workspace_id,
        channel_id,
        root["id"],
        "Hide this reply exactly once",
        _op(5_018),
        _op(5_019),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.list_workspace_thread_messages(workspace_id, root["id"])[
        "unread_count"
    ] == 2
    member.hide_workspace_message(workspace_id, hidden_reply["id"], _op(5_040))
    assert member.list_workspace_thread_messages(workspace_id, root["id"])[
        "unread_count"
    ] == 1
    member.hide_workspace_message(workspace_id, hidden_reply["id"], _op(5_041))
    thread = member.list_workspace_thread_messages(workspace_id, root["id"])
    assert thread["unread_count"] == 1

    member.mark_workspace_thread_read(
        workspace_id, root["id"], thread["high_water"], _op(5_016)
    )
    assert member.workspace_snapshot()["workspaces"][0]["thread_unread_count"] == 0
    draft = member.save_workspace_thread_draft(
        workspace_id,
        channel_id,
        root["id"],
        "@Alex restart-safe reply",
        _op(5_017),
        [owner_id],
    )
    assert draft["thread_root_id"] == root["id"]

    original_get = member.store.get
    with monkeypatch.context() as patch:
        def no_message_body_reads(kind: str, record_id: str) -> Any:
            if kind in {"workspace_message_state", "workspace_event"}:
                raise AssertionError("ordinary startup opened thread message content")
            return original_get(kind, record_id)

        patch.setattr(member.store, "get", no_message_body_reads)
        startup = member.workspace_snapshot()
        assert startup["workspaces"][0]["thread_unread_count"] == 0
        assert startup["workspace_drafts"] == [draft]

    member.close()
    member, member_network = _service(
        tmp_path / "threads" / "member",
        member_identity,
        "Bailey",
        vault_key=member_key,
    )
    restarted = member.workspace_snapshot()
    assert restarted["workspace_drafts"] == [draft]
    assert member.list_workspace_thread_messages(workspace_id, root["id"])[
        "unread_count"
    ] == 0

    owner.edit_workspace_message(
        workspace_id,
        reply["id"],
        "Edited reply converges",
        _op(5_020),
        _op(5_021),
    )
    owner.set_workspace_reaction(
        workspace_id,
        reply["id"],
        "👍",
        True,
        _op(5_022),
        _op(5_023),
    )
    mutations = _flush(owner, owner_network)
    assert len(mutations) == 2
    for item in reversed(mutations):
        _deliver(
            member,
            item,
            source_profile=owner_profile,
            recipient_profile=member_profile,
        )
    converged = member.list_workspace_thread_messages(workspace_id, root["id"])
    assert converged["replies"][0]["text"] == "Edited reply converges"
    assert converged["replies"][0]["reactions"][0]["emoji"] == "👍"

    owner.remove_workspace_member(workspace_id, member_id, _op(5_030))
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.workspace_snapshot()["workspaces"][0]["thread_unread_count"] == 0
    retained_archive = member.list_workspace_thread_messages(
        workspace_id, root["id"]
    )
    assert retained_archive["root"]["id"] == root["id"]
    assert retained_archive["replies"][0]["text"] == "Edited reply converges"
    archived_search = member.search_workspace(
        workspace_id, "edited reply converges", scope="threads"
    )
    assert archived_search["results"][0]["id"] == reply["id"]
    with pytest.raises(ContactNotApproved):
        member.send_workspace_thread_reply(
            workspace_id,
            channel_id,
            root["id"],
            "Former members cannot send",
            _op(5_031),
            _op(5_032),
        )
    owner.close()
    member.close()


def test_workspace_threads_preserve_private_rosters_and_direct_participants(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "thread-audiences", base=5_100)
    workspace_id = workspace["id"]
    owner_id = owner.workspace_snapshot()["workspaces"][0]["local_member_id"]
    member_id = member.workspace_snapshot()["workspaces"][0]["local_member_id"]

    private = owner.create_workspace_channel(
        workspace_id,
        "thread-private",
        "Signed roster",
        _op(5_110),
        "private",
        [owner_id, member_id],
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    private_root = owner.send_workspace_message(
        workspace_id,
        private["id"],
        "Private root",
        _op(5_111),
        _op(5_112),
    )
    owner.send_workspace_thread_reply(
        workspace_id,
        private["id"],
        private_root["id"],
        "Private reply",
        _op(5_113),
        _op(5_114),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    private_thread = member.list_workspace_thread_messages(
        workspace_id, private_root["id"]
    )
    assert private_thread["conversation"]["visibility"] == "private"
    private_search = member.search_workspace(workspace_id, "Private", limit=1)
    assert private_search["results"][0]["id"] in {
        private_root["id"],
        private_thread["replies"][0]["id"],
    }
    assert private_search["next_cursor"] is not None

    owner.update_workspace_private_channel_members(
        workspace_id, private["id"], [owner_id], _op(5_115)
    )
    # Removed recipients are not sent future private controls. Model a device
    # that learned the signed removal through a retained control copy.
    assert _flush(owner, owner_network) == []
    removed_record = owner._require_workspace_channel(workspace_id, private["id"])
    removed_control = owner._workspace_channel_by_digest(removed_record["head_hash"])
    assert removed_control is not None
    member.store.put_many(
        [
            (
                "workspace_channel",
                member._workspace_channel_record_id(private["id"]),
                member._channel_record(removed_control),
            ),
            (
                "workspace_channel_control",
                member._workspace_channel_control_id(removed_control.digest),
                member._workspace_channel_control_record(
                    removed_control, document_type="workspace_channel_manifest"
                ),
            ),
            member._workspace_channel_version_record(removed_control),
        ]
    )
    member._workspace_changed(workspace_id, conversation_id=private["id"])
    with pytest.raises(ContactNotApproved):
        member.list_workspace_thread_messages(workspace_id, private_root["id"])
    assert member.search_workspace(
        workspace_id, "Private", scope="messages"
    )["results"] == []
    with pytest.raises(StaleCursor):
        member.search_workspace(
            workspace_id,
            "Private",
            cursor=private_search["next_cursor"],
            limit=1,
        )
    owner.update_workspace_private_channel_members(
        workspace_id, private["id"], [owner_id, member_id], _op(5_116)
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    # A later re-admission does not disclose a root from the earlier roster era.
    with pytest.raises(ContactNotApproved):
        member.list_workspace_thread_messages(workspace_id, private_root["id"])
    assert member.search_workspace(
        workspace_id, "Private", scope="messages"
    )["results"] == []

    # A current member cannot resurrect that inaccessible root by signing a new
    # reply against the current roster checkpoint.
    owner_workspace = owner._require_workspace(workspace_id)
    owner_manifest = owner._workspace_current_manifest(owner_workspace)
    owner_channel_record = owner._require_workspace_channel(
        workspace_id, private["id"]
    )
    owner_channel = owner._workspace_channel_by_digest(
        owner_channel_record["head_hash"]
    )
    stream_head = owner.store.get(
        "workspace_stream_coverage",
        owner._workspace_stream_head_id(
            workspace_id, private["id"], owner_workspace["local_device_id"]
        ),
    )
    assert owner._identity is not None and owner_channel is not None
    resurrecting_event_id = _op(5_117)
    resurrecting_reply = create_workspace_event(
        owner._identity,
        workspace_id=workspace_id,
        conversation_id=private["id"],
        event_id=resurrecting_event_id,
        author_member_id=owner_id,
        author_device_id=owner_workspace["local_device_id"],
        sequence=int(stream_head["high_water"]) + 1,
        previous_event_digest=stream_head["head_digest"],
        manifest_digest=owner_manifest.digest,
        channel_digest=owner_channel.digest,
        text="Must not resurrect an old private root",
        thread_root=private_root["id"],
        audience_member_ids=[owner_id, member_id],
    )
    assert not member._accept_workspace_event(
        WorkspaceWirePayload(
            kind="workspace_event",
            logical_id=_op(5_118),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=resurrecting_reply,
        )
    )
    assert member.store.get(
        "workspace_event",
        member._workspace_event_record_id(resurrecting_event_id),
    ) is None

    resurrecting_mutation_id = _op(5_119)
    resurrecting_mutation = create_workspace_mutation_event(
        owner._identity,
        workspace_id=workspace_id,
        conversation_id=private["id"],
        event_id=resurrecting_mutation_id,
        event_type="edit",
        author_member_id=owner_id,
        author_device_id=owner_workspace["local_device_id"],
        sequence=int(stream_head["high_water"]) + 1,
        previous_event_digest=stream_head["head_digest"],
        manifest_digest=owner_manifest.digest,
        channel_digest=owner_channel.digest,
        target_event_id=_op(5_113),
        base_revision=0,
        revision=1,
        text="Must not mutate an inaccessible private thread",
        thread_root=private_root["id"],
        audience_member_ids=[owner_id, member_id],
    )
    assert not member._accept_workspace_event(
        WorkspaceWirePayload(
            kind="workspace_event",
            logical_id=_op(5_126),
            workspace_id=workspace_id,
            expires_at=int(time.time()) + 60,
            document=resurrecting_mutation,
        )
    )
    assert member.store.get(
        "workspace_event",
        member._workspace_event_record_id(resurrecting_mutation_id),
    ) is None

    direct = owner.open_workspace_direct(workspace_id, member_id, _op(5_120))
    direct_root = owner.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "Participant-only root",
        _op(5_121),
        _op(5_122),
    )
    owner.send_workspace_thread_reply(
        workspace_id,
        direct["id"],
        direct_root["id"],
        "Participant-only reply",
        _op(5_123),
        _op(5_124),
    )
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    direct_thread = member.list_workspace_thread_messages(
        workspace_id, direct_root["id"]
    )
    assert direct_thread["conversation"]["kind"] == "direct"
    member.hide_workspace_direct(workspace_id, direct["id"], _op(5_125))
    with pytest.raises(ContactNotApproved):
        member.list_workspace_thread_messages(workspace_id, direct_root["id"])
    assert all(
        item["root"]["id"] != direct_root["id"]
        for item in member.list_workspace_threads(workspace_id)["threads"]
    )
    owner.close()
    member.close()


def test_workspace_retention_policy_is_owner_signed_and_invalidates_cursors(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        member,
        _member_network,
        member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "retention-policy", base=6_000)
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    owner.send_workspace_message(
        workspace_id, channel_id, "first retained message", _op(6_010), _op(6_011)
    )
    owner.send_workspace_message(
        workspace_id, channel_id, "second retained message", _op(6_012), _op(6_013)
    )
    cursor = owner.list_workspace_messages(workspace_id, channel_id, limit=1)[
        "next_cursor"
    ]
    assert cursor is not None
    before_generation = owner._require_workspace(workspace_id)[
        "retention_generation"
    ]
    updated = owner.update_workspace_retention(workspace_id, 30, _op(6_014))
    assert updated["retention_days"] == 30
    assert updated["retention_generation"] == before_generation + 1
    assert updated["retention_pruning_state"] == "pending"
    with pytest.raises(StaleCursor, match="stale"):
        owner.list_workspace_messages(workspace_id, channel_id, cursor=cursor)
    _deliver_all(
        member,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=member_profile,
    )
    assert member.workspace_snapshot()["workspaces"][0]["retention_days"] == 30
    with pytest.raises(ContactNotApproved, match="owner"):
        member.update_workspace_retention(workspace_id, 365, _op(6_015))
    owner.close()
    member.close()


def test_workspace_search_normalization_is_frozen_and_bounded() -> None:
    assert normalize_workspace_search_text("  Café ＴＥＡＭ  ") == "  café team  "
    assert tokenize_workspace_search_text("Café—TEAM, team; a _ 42") == (
        "café",
        "team",
        "42",
    )
    assert tokenize_workspace_search_text("e\u0301lan") == ("élan",)


def test_workspace_search_is_incremental_encrypted_and_stale_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _network = _service(tmp_path / "search", RNS.Identity(), "Alex Rivera")
    workspace = service.create_workspace(_op(7_100), "Search lab", "")
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    first = service.send_workspace_message(
        workspace_id,
        channel_id,
        "Café launch zephyr",
        _op(7_101),
        _op(7_102),
    )
    second = service.send_workspace_message(
        workspace_id,
        channel_id,
        "Café launch planning cedar",
        _op(7_103),
        _op(7_104),
    )
    reply = service.send_workspace_thread_reply(
        workspace_id,
        channel_id,
        first["id"],
        "Thread zephyr followup",
        _op(7_105),
        _op(7_106),
    )

    page = service.search_workspace(workspace_id, "CAFÉ", limit=1)
    assert page["coverage"] == "retained"
    assert page["next_cursor"] is not None
    older = service.search_workspace(
        workspace_id, "cafe\u0301", cursor=page["next_cursor"], limit=1
    )
    assert {page["results"][0]["id"], older["results"][0]["id"]} == {
        first["id"],
        second["id"],
    }
    thread = service.search_workspace(workspace_id, "followup", scope="threads")
    assert len(thread["results"]) == 1
    assert thread["results"][0]["id"] == reply["id"]
    assert thread["results"][0]["kind"] == "thread"
    assert thread["results"][0]["is_reply"] is True
    assert thread["results"][0]["thread_root_id"] == first["id"]

    service.edit_workspace_message(
        workspace_id,
        first["id"],
        "Café launch aurora",
        _op(7_107),
        _op(7_108),
    )
    assert service.search_workspace(workspace_id, "zephyr", scope="messages")[
        "results"
    ] == []
    assert service.search_workspace(workspace_id, "aurora", scope="messages")[
        "results"
    ][0]["id"] == first["id"]
    service.hide_workspace_message(workspace_id, second["id"], _op(7_109))
    assert service.search_workspace(workspace_id, "cedar")["results"] == []
    service.delete_workspace_message(
        workspace_id, reply["id"], _op(7_110), _op(7_111)
    )
    assert service.search_workspace(workspace_id, "followup")["results"] == []

    assert service.search_workspace(workspace_id, "Alex", scope="people")[
        "results"
    ][0]["member_id"] == workspace["local_member_id"]
    assert service.search_workspace(workspace_id, "general", scope="channels")[
        "results"
    ][0]["id"] == channel_id

    cursor = service.search_workspace(workspace_id, "café", limit=1)["next_cursor"]
    assert cursor is None  # the other matching result is locally hidden
    service.send_workspace_message(
        workspace_id,
        channel_id,
        "launch glacier",
        _op(7_112),
        _op(7_113),
    )
    cursor = service.search_workspace(workspace_id, "launch", limit=1)["next_cursor"]
    assert cursor is not None
    cursor_value = service.store.open_cursor(cursor)
    assert "query" not in cursor_value
    assert "launch" not in json.dumps(cursor_value)
    assert cursor_value["workspace_id"] == workspace_id
    assert cursor_value["authorization_generation"] == 1
    assert cursor_value["retention_generation"] == 1
    assert cursor_value["search_generation"] >= 1
    assert isinstance(cursor_value["token_shard_id"], str)
    assert cursor_value["offset"] == 1
    with pytest.raises(StaleCursor):
        service.search_workspace(workspace_id, "café", cursor=cursor, limit=1)
    with pytest.raises(StaleCursor):
        service.search_workspace(
            workspace_id, "launch", scope="threads", cursor=cursor, limit=1
        )
    tampered = f"{cursor[:-1]}{'A' if cursor[-1] != 'A' else 'B'}"
    with pytest.raises(ValidationError, match="Cursor is invalid"):
        service.search_workspace(workspace_id, "launch", cursor=tampered, limit=1)
    service.send_workspace_message(
        workspace_id,
        channel_id,
        "launch tundra",
        _op(7_114),
        _op(7_115),
    )
    with pytest.raises(StaleCursor):
        service.search_workspace(workspace_id, "launch", cursor=cursor, limit=1)

    for invalid_query in ("a", " ".join(f"token{index}" for index in range(9)), "z" * 65, "z" * 257):
        with pytest.raises(ValidationError):
            service.search_workspace(workspace_id, invalid_query)
    with pytest.raises(ValidationError):
        service.search_workspace(workspace_id, "launch", scope="unknown")
    with pytest.raises(ValidationError):
        service.search_workspace(workspace_id, "launch", limit=51)

    def reject_whole_kind_scan(kind: str) -> list[dict[str, Any]]:
        raise AssertionError(f"search attempted a whole-kind scan: {kind}")

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "list", reject_whole_kind_scan)
        bounded = service.search_workspace(workspace_id, "glacier")
    assert bounded["results"][0]["id"]
    assert bounded["candidate_count"] <= 256
    assert bounded["shard_pages_opened"] <= 8

    database = tmp_path / "search" / "mesh-chat.vault"
    raw = database.read_bytes()
    for plaintext in (b"zephyr", b"aurora", b"Alex Rivera", b"general"):
        assert plaintext not in raw
    service.close()


def test_workspace_search_rechecks_direct_participants_even_for_owner(
    tmp_path: Path,
) -> None:
    (
        owner,
        _owner_network,
        _owner_profile,
        member,
        _member_network,
        _member_profile,
        workspace,
        _member_key,
        _member_identity,
    ) = _joined_pair(tmp_path / "search-direct-authorization", base=7_200)
    workspace_id = workspace["id"]
    member_id = member.workspace_snapshot()["workspaces"][0]["local_member_id"]
    direct = owner.open_workspace_direct(workspace_id, member_id, _op(7_210))
    message = owner.send_workspace_direct_message(
        workspace_id,
        direct["id"],
        "participant-only solarwind",
        _op(7_211),
        _op(7_212),
    )
    visible = owner.search_workspace(workspace_id, "solarwind")
    assert visible["results"][0]["id"] == message["id"]
    assert owner._require_workspace(workspace_id)["local_role"] == "owner"

    # Treat the keyed index as a hostile hint: even if an old result remains
    # indexed, current direct participants are checked before presentation.
    direct_record = owner._require_workspace_direct(workspace_id, direct["id"])
    direct_record["participant_member_ids"] = [member_id, _op(7_213)]
    owner.store.put(
        "workspace_direct",
        owner._workspace_direct_record_id(direct["id"]),
        direct_record,
    )
    assert owner.search_workspace(workspace_id, "solarwind")["results"] == []
    owner.close()
    member.close()


def test_workspace_search_candidate_and_shard_bounds_are_explicit(
    tmp_path: Path,
) -> None:
    service, _network = _service(tmp_path / "search-bounds", RNS.Identity(), "Alex")
    workspace = service.create_workspace(_op(7_300), "Bounded search", "")
    workspace_id = workspace["id"]
    stored_workspace = service._require_workspace(workspace_id)
    staged: dict[tuple[str, str], dict[str, Any]] = {}
    for index in range(530):
        service._workspace_search_document_records(
            stored_workspace,
            category="message",
            entity_id=_op(7_400 + index),
            text="commonbound",
            active=True,
            sort_at=float(index),
            conversation_id=workspace["general_channel_id"],
            staged=staged,
        )
    service.store.put_many(
        (kind, record_id, value)
        for (kind, record_id), value in staged.items()
    )

    result = service.search_workspace(workspace_id, "commonbound", limit=50)
    assert result["results"] == []
    assert result["candidate_count"] == 256
    assert result["candidate_limit_reached"] is True
    assert result["shard_pages_opened"] <= 8
    assert result["coverage"] == "incomplete"
    token_index = service.store.get(
        "workspace_search_index",
        service._workspace_search_token_id(workspace_id, "commonbound"),
    )
    assert token_index is not None
    page_id = token_index["head_page"]
    page_count = 0
    entry_count = 0
    while isinstance(page_id, str):
        page = service.store.get("workspace_search_index", page_id)
        assert page is not None
        assert len(page["entries"]) <= 100
        page_count += 1
        entry_count += len(page["entries"])
        page_id = page["previous_page"]
    assert page_count == 6
    assert entry_count == 530
    service.close()


def test_workspace_revision_and_tombstone_views_are_bounded_and_authorized(
    tmp_path: Path,
) -> None:
    service, _network = _service(tmp_path / "revision-view", RNS.Identity(), "Alex")
    workspace = service.create_workspace(_op(6_100), "Revision view", "")
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]
    message = service.send_workspace_message(
        workspace_id, channel_id, "initial", _op(6_101), _op(6_102)
    )
    service.edit_workspace_message(
        workspace_id, message["id"], "edited", _op(6_103), _op(6_104)
    )
    service.set_workspace_reaction(
        workspace_id, message["id"], "👍", True, _op(6_105), _op(6_106)
    )
    service.delete_workspace_message(
        workspace_id, message["id"], _op(6_107), _op(6_108)
    )
    revisions = service.list_workspace_message_revisions(
        workspace_id, message["id"], limit=2
    )
    assert [item["event_type"] for item in revisions["revisions"]] == [
        "delete",
        "reaction",
    ]
    assert revisions["next_cursor"] is not None
    older = service.list_workspace_message_revisions(
        workspace_id,
        message["id"],
        cursor=revisions["next_cursor"],
        limit=2,
    )
    assert older["revisions"][0]["text"] == "edited"
    tombstones = service.list_workspace_tombstones(workspace_id, channel_id)
    assert tombstones["tombstones"][0]["message"]["id"] == message["id"]
    assert tombstones["tombstones"][0]["message"]["text"] == ""
    service.close()


def test_workspace_pruning_resumes_after_restart_without_resurrection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mesh_chat.workspace_protocol as workspace_protocol_module
    import mesh_chat.workspace_service as workspace_service_module

    identity = RNS.Identity()
    key = os.urandom(32)
    profile = tmp_path / "prune-restart"
    service, _network = _service(profile, identity, "Alex", vault_key=key)
    now = time.time()
    old = now - 31 * 24 * 60 * 60
    with monkeypatch.context() as patch:
        patch.setattr(workspace_service_module.time, "time", lambda: old)
        patch.setattr(workspace_protocol_module.time, "time", lambda: old)
        workspace = service.create_workspace(_op(6_200), "Prune restart", "")
        for index in range(150):
            service.send_workspace_message(
                workspace["id"],
                workspace["general_channel_id"],
                f"expired-{index}",
                _op(6_300 + index),
                _op(6_500 + index),
            )
    workspace_id = workspace["id"]
    channel_id = workspace["general_channel_id"]

    # Model an upgrade from 0.2.29 by removing only derived search records.
    # Startup recreates directory metadata, while message bodies are indexed in
    # bounded batches and the saved page/offset survives a restart.
    for kind in (
        "workspace_search_state",
        "workspace_search_catalog",
        "workspace_search_document",
        "workspace_search_index",
    ):
        for record_id, _value in list(service.store.items(kind)):
            service.store.delete(kind, record_id)
    migrated = service.workspace_snapshot()["workspaces"][0]["search_index"]
    assert migrated["status"] == "rebuilding"
    first_search = service.search_workspace(workspace_id, "expired 149")
    assert first_search["results"][0]["snippet"] == "expired-149"
    assert first_search["coverage"] == "indexing"
    assert first_search["indexed_events"] == 128
    service.close()

    service, _network = _service(profile, identity, "Alex", vault_key=key)
    resumed = service.search_workspace(workspace_id, "expired 0")
    assert resumed["results"][0]["snippet"] == "expired-0"
    assert resumed["coverage"] == "retained"
    assert resumed["indexed_events"] == 150
    expired_index = service.store.get(
        "workspace_search_index",
        service._workspace_search_token_id(workspace_id, "expired"),
    )
    assert expired_index is not None
    assert expired_index["count"] == 150

    cursor = service.list_workspace_messages(workspace_id, channel_id, limit=1)[
        "next_cursor"
    ]
    service.update_workspace_retention(workspace_id, 30, _op(6_700))
    first = service.prune_workspace_history(
        workspace_id, _op(6_701), max_events=100
    )
    assert first["needs_more"] is True
    assert 0 < first["pruned_this_batch"] <= 100
    with pytest.raises(StaleCursor):
        service.list_workspace_messages(workspace_id, channel_id, cursor=cursor)
    service.close()

    service, _network = _service(profile, identity, "Alex", vault_key=key)
    result = first
    operation = 6_702
    while result["needs_more"]:
        result = service.prune_workspace_history(
            workspace_id, _op(operation), max_events=100
        )
        operation += 1
    assert result["status"] == "complete"
    assert result["pruned"] == 150
    page = service.list_workspace_messages(workspace_id, channel_id)
    assert page["messages"] == []
    assert page["history_status"] == "pruned"
    pruned_search = service.search_workspace(workspace_id, "expired 149")
    assert pruned_search["results"] == []
    assert pruned_search["coverage"] == "pruned"
    tombstones = service.store.list("workspace_event_tombstone")
    assert len(tombstones) == 150
    retired_id = tombstones[0]["event_id"]
    with pytest.raises(ValidationError, match="already used"):
        service.send_workspace_message(
            workspace_id,
            channel_id,
            "resurrection attempt",
            retired_id,
            _op(6_900),
        )
    service.close()


def test_workspace_pruning_keeps_fresh_deletion_tombstone_for_live_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mesh_chat.workspace_protocol as workspace_protocol_module
    import mesh_chat.workspace_service as workspace_service_module

    service, _network = _service(tmp_path / "tombstone-window", RNS.Identity(), "Alex")
    now = time.time()
    old = now - 31 * 24 * 60 * 60
    with monkeypatch.context() as patch:
        patch.setattr(workspace_service_module.time, "time", lambda: old)
        patch.setattr(workspace_protocol_module.time, "time", lambda: old)
        workspace = service.create_workspace(_op(7_000), "Tombstone window", "")
        message = service.send_workspace_message(
            workspace["id"],
            workspace["general_channel_id"],
            "old plaintext",
            _op(7_001),
            _op(7_002),
        )
    service.delete_workspace_message(
        workspace["id"], message["id"], _op(7_003), _op(7_004)
    )
    service.update_workspace_retention(workspace["id"], 30, _op(7_005))
    result = service.prune_workspace_history(
        workspace["id"], _op(7_006), max_events=100
    )
    assert result["pruned"] == 0
    retained = service.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )["messages"]
    assert retained[0]["deleted"] is True
    assert retained[0]["text"] == ""
    service.close()


def test_administrator_offline_channels_and_owner_approved_invitation(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        admin,
        admin_network,
        admin_profile,
        workspace,
        _admin_key,
        _admin_identity,
    ) = _joined_pair(tmp_path / "administrator", base=140_000)
    workspace_id = workspace["id"]
    admin_member_id = admin._require_workspace(workspace_id)["local_member_id"]

    promoted = owner.change_workspace_role(
        workspace_id, admin_member_id, "admin", _op(140_010)
    )
    assert next(
        item for item in promoted["members"] if item["id"] == admin_member_id
    )["role"] == "admin"
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    assert admin._require_workspace(workspace_id)["local_role"] == "admin"

    owner.update_workspace_policies(
        workspace_id,
        "owner_and_admins",
        "owner_and_admins",
        _op(140_011),
        "owner_and_admins",
    )
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    # The owner does not participate in these local commands. The administrator
    # signs and commits the channel plus message before any route is attempted.
    channel = admin.create_workspace_channel(
        workspace_id, "offline-ops", "Owner is offline", _op(140_012)
    )
    message = admin.send_workspace_message(
        workspace_id,
        channel["id"],
        "Administrator-managed operations continue.",
        _op(140_013),
        _op(140_014),
    )
    assert message["text"].startswith("Administrator-managed")

    before_invites = len(
        [
            item for item in owner.workspace_snapshot()["workspace_invitations"]
            if item["workspace_id"] == workspace_id
        ]
    )
    submitted = admin.submit_workspace_admin_request(
        workspace_id, "invitation", _op(140_015), note="Field observer"
    )
    assert submitted["state"] == "pending"
    request_packets = [
        item
        for item in _flush(admin, admin_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_admin_request"
    ]
    assert len(request_packets) == 1
    _deliver(
        owner,
        request_packets[0],
        source_profile=admin_profile,
        recipient_profile=owner_profile,
    )
    owner_snapshot = owner.workspace_snapshot()
    pending = next(
        item
        for item in owner_snapshot["workspace_admin_requests"]
        if item["workspace_id"] == workspace_id and item["state"] == "pending"
    )
    assert pending["effective_role"] is None
    assert len(
        [
            item for item in owner_snapshot["workspace_invitations"]
            if item["workspace_id"] == workspace_id
        ]
    ) == before_invites

    approved = owner.decide_workspace_admin_request(
        workspace_id, pending["id"], True, _op(140_016)
    )
    assert approved["state"] == "approved"
    assert approved["invitation"]["text"].startswith("MESHWORKSPACE1:")
    decision_packets = [
        item
        for item in _flush(owner, owner_network)
        if parse_workspace_payload(
            _native(item, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_admin_request"
    ]
    assert len(decision_packets) == 1
    _deliver(
        admin,
        decision_packets[0],
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    # Duplicate endpoint delivery is idempotent and never creates a second
    # invitation or authority result.
    _deliver(
        admin,
        decision_packets[0],
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    outgoing = admin.list_workspace_admin_requests(
        workspace_id, "outgoing"
    )["requests"]
    completed = next(item for item in outgoing if item["id"] == submitted["id"])
    assert completed["state"] == "approved"
    assert completed["invitation"]["text"] == approved["invitation"]["text"]
    assert len(admin.store.list("workspace_admin_decision")) == 1

    owner.change_workspace_role(
        workspace_id, admin_member_id, "member", _op(140_017)
    )
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    assert admin._require_workspace(workspace_id)["local_role"] == "member"
    with pytest.raises(ContactNotApproved, match="owners and administrators"):
        admin.create_workspace_channel(
            workspace_id, "after-demotion", "", _op(140_018)
        )
    owner.close()
    admin.close()


def test_linked_desktop_recovers_history_and_removal_revokes_only_that_device(
    tmp_path: Path,
) -> None:
    owner_identity = RNS.Identity()
    linked_identity = RNS.Identity()
    owner, owner_network = _service(tmp_path / "owner-device", owner_identity, "Alex")
    linked, linked_network = _service(tmp_path / "linked-device", linked_identity, "Alex")
    owner_profile = owner._require_profile()
    linked_profile = linked._require_profile()
    workspace = owner.create_workspace(_op(160_000), "Device lab", "Increment 14")
    earlier = owner.send_workspace_message(
        workspace["id"],
        workspace["general_channel_id"],
        "canonical history from before this device existed",
        _op(160_001),
        _op(160_002),
    )
    advanced = owner.update_workspace_metadata(
        workspace["id"], "Device lab", "Increment 14 after epoch one", _op(160_100)
    )
    assert advanced["epoch"] == 2
    link = owner.create_workspace_device_link(workspace["id"], _op(160_003))
    linking = linked.submit_workspace_device_link(link["text"], _op(160_004))
    assert linking["state"] == "linking"
    _deliver_all(
        owner,
        _flush(linked, linked_network),
        source_profile=linked_profile,
        recipient_profile=owner_profile,
    )
    pending = next(
        item
        for item in owner.workspace_snapshot()["workspace_device_transitions"]
        if item["transition_kind"] == "link" and item["state"] == "pending"
    )
    owner.approve_workspace_device_link(
        workspace["id"], pending["id"], _op(160_005)
    )
    _deliver_all(
        linked,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=linked_profile,
    )
    linked_workspace = linked._require_workspace(workspace["id"])
    assert linked_workspace["state"] == "active"
    assert linked_workspace["local_member_id"] == workspace["local_member_id"]
    assert linked_workspace["local_device_id"] != workspace["local_device_id"]
    assert len(linked_workspace["members"][0]["devices"]) == 2
    assert linked._require_workspace_channel(
        workspace["id"], workspace["general_channel_id"]
    )["state"] == "active"

    history = linked.start_workspace_history(
        workspace["id"], workspace["general_channel_id"], _op(160_006)
    )
    assert history["status"] == "requesting"
    requests = [
        packet
        for packet in _flush(linked, linked_network)
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_history_request"
    ]
    assert requests
    _deliver_all(
        owner,
        requests,
        source_profile=linked_profile,
        recipient_profile=owner_profile,
    )
    responses = [
        packet
        for packet in _flush(owner, owner_network)
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_history_response"
    ]
    assert responses
    _deliver_all(
        linked,
        responses,
        source_profile=owner_profile,
        recipient_profile=linked_profile,
    )
    assert linked.store.get(
        "workspace_event", linked._workspace_event_record_id(earlier["id"])
    ) is not None

    owner.set_workspace_read_hint_sync(workspace["id"], True, _op(160_010))
    linked.set_workspace_read_hint_sync(workspace["id"], True, _op(160_011))
    owner_page = owner.list_workspace_messages(
        workspace["id"], workspace["general_channel_id"]
    )
    owner.mark_workspace_read(
        workspace["id"],
        workspace["general_channel_id"],
        owner_page["high_water"],
        _op(160_012),
    )
    read_hints = [
        packet
        for packet in _flush(owner, owner_network)
        if parse_workspace_payload(
            _native(packet, source=b"\x00" * 16, destination=b"\x01" * 16)
        ).kind
        == "workspace_read_hint"
    ]
    assert read_hints
    _deliver_all(
        linked,
        read_hints,
        source_profile=owner_profile,
        recipient_profile=linked_profile,
    )
    linked_read = linked.store.get(
        "workspace_read_state",
        linked.store.opaque_id(
            "workspace-read-state",
            workspace["id"],
            workspace["general_channel_id"],
        ),
    )
    assert linked_read["source"] == "linked_device_hint"

    with pytest.raises(ValidationError, match="Rotate workspace authority"):
        linked.request_workspace_device_removal(
            workspace["id"], workspace["local_device_id"], _op(160_013)
        )
    requested = owner.request_workspace_device_removal(
        workspace["id"], linked_workspace["local_device_id"], _op(160_014)
    )
    assert requested["state"] == "pending"
    owner.approve_workspace_device_removal(
        workspace["id"], requested["id"], _op(160_015)
    )
    _deliver_all(
        linked,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=linked_profile,
    )
    assert linked._require_workspace(workspace["id"])["state"] == "device_removed"
    owner.close()
    linked.close()


def test_workspace_ownership_transfer_requires_acceptance_and_converges(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        successor,
        successor_network,
        successor_profile,
        created,
        _successor_key,
        _successor_identity,
    ) = _joined_pair(tmp_path / "authority-transfer", base=150_000)
    workspace_id = created["id"]
    successor_workspace = successor._require_workspace(workspace_id)
    successor_member_id = successor_workspace["local_member_id"]
    successor_device_id = successor_workspace["local_device_id"]

    offered = owner.offer_workspace_authority_transition(
        workspace_id,
        "ownership_transfer",
        successor_member_id,
        successor_device_id,
        "admin",
        _op(150_010),
    )
    assert owner._require_workspace(workspace_id)["local_role"] == "owner"
    _deliver_all(
        successor,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=successor_profile,
    )
    incoming = successor.list_workspace_authority_transitions(workspace_id)[
        "transitions"
    ][0]
    assert incoming["state"] == "waiting_for_acceptance"
    successor.accept_workspace_authority_transition(
        workspace_id, offered["id"], _op(150_011)
    )
    assert successor._require_workspace(workspace_id)["local_role"] == "member"
    _deliver_all(
        owner,
        _flush(successor, successor_network),
        source_profile=successor_profile,
        recipient_profile=owner_profile,
    )
    accepted = owner.list_workspace_authority_transitions(workspace_id)[
        "transitions"
    ][0]
    assert accepted["state"] == "accepted_waiting_finalization"

    owner.finalize_workspace_authority_transition(
        workspace_id, offered["id"], _op(150_012)
    )
    owner_state = owner._require_workspace(workspace_id)
    assert owner_state["local_role"] == "admin"
    assert owner_state["authority_device_id"] == successor_device_id
    packets = _flush(owner, owner_network)
    _deliver_all(
        successor,
        packets,
        source_profile=owner_profile,
        recipient_profile=successor_profile,
    )
    successor_state = successor._require_workspace(workspace_id)
    assert successor_state["local_role"] == "owner"
    assert successor_state["authority_device_id"] == successor_device_id
    general = successor._require_workspace_channel(
        workspace_id, successor_state["general_channel_id"]
    )
    assert general["manager_device_id"] == successor_device_id
    assert len(successor_state["authority_chain"]) == 1
    owner.close()
    successor.close()


def test_workspace_same_owner_rotation_uses_exact_admitted_device(
    tmp_path: Path,
) -> None:
    original_identity = RNS.Identity()
    successor_identity = RNS.Identity()
    service, _network = _service(
        tmp_path / "same-owner-rotation", original_identity, "Alex"
    )
    created = service.create_workspace(_op(150_050), "Rotating authority", "")
    workspace_id = created["id"]
    workspace = dict(service._require_workspace(workspace_id))
    current = service._workspace_current_manifest(workspace)
    owner = next(member for member in current.members if member.role.value == "owner")
    successor_device_id = _op(150_051)
    successor_card = create_workspace_device_card(
        successor_identity,
        workspace_id=workspace_id,
        member_id=owner.member_id,
        device_id=successor_device_id,
        display_name=owner.display_name,
    )
    seeded_raw = create_workspace_manifest(
        original_identity,
        workspace_id=workspace_id,
        epoch=current.epoch + 1,
        previous_manifest_hash=current.digest,
        name=current.name,
        description=current.description,
        authority_device_id=current.authority_device_id,
        members=[
            WorkspaceManifestMemberInput(
                member.member_id,
                member.display_name,
                member.role,
                [device.serialized for device in member.devices]
                + ([successor_card] if member.member_id == owner.member_id else []),
                member.status,
            )
            for member in current.members
        ],
        status=current.status,
        retention_days=current.retention_days,
        channel_creation=current.channel_creation,
        posting=current.posting,
        invitation_requests=current.invitation_requests,
        removal_checkpoint_digests=current.removal_checkpoint_digests,
    )
    seeded = verify_workspace_manifest(
        seeded_raw,
        expected_workspace_id=workspace_id,
        expected_epoch=current.epoch + 1,
        expected_previous_hash=current.digest,
        expected_authority_destination=current.authority_destination,
    )
    service._apply_manifest_to_workspace(workspace, seeded)
    service._apply_manifest_public_identities(workspace, seeded)
    service.store.put_many(
        [
            ("workspace", service._workspace_record_id(workspace_id), workspace),
            (
                "workspace_manifest",
                service._workspace_manifest_record_id(seeded.digest),
                service._manifest_record(seeded),
            ),
            service._manifest_epoch_record(seeded),
        ]
    )

    offered = service.offer_workspace_authority_transition(
        workspace_id,
        "same_owner_rotation",
        owner.member_id,
        successor_device_id,
        None,
        _op(150_052),
    )
    assert service._require_workspace(workspace_id)["authority_device_id"] == (
        current.authority_device_id
    )

    successor_workspace = dict(service._require_workspace(workspace_id))
    successor_workspace["local_device_id"] = successor_device_id
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), successor_workspace
    )
    service._identity = successor_identity
    accepted = service.accept_workspace_authority_transition(
        workspace_id, offered["id"], _op(150_053)
    )
    assert accepted["state"] == "accepted_waiting_finalization"
    assert service._require_workspace(workspace_id)["authority_device_id"] == (
        current.authority_device_id
    )

    authority_workspace = dict(service._require_workspace(workspace_id))
    authority_workspace["local_device_id"] = current.authority_device_id
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), authority_workspace
    )
    service._identity = original_identity
    finalized = service.finalize_workspace_authority_transition(
        workspace_id, offered["id"], _op(150_054)
    )
    assert finalized["state"] == "applied"
    assert service._require_workspace(workspace_id)["authority_device_id"] == (
        successor_device_id
    )
    with pytest.raises((ContactNotApproved, IdentityMismatch)):
        service.update_workspace_metadata(
            workspace_id, "Old authority rejected", "", _op(150_055)
        )

    successor_workspace = dict(service._require_workspace(workspace_id))
    successor_workspace["local_device_id"] = successor_device_id
    service.store.put(
        "workspace", service._workspace_record_id(workspace_id), successor_workspace
    )
    service._identity = successor_identity
    updated = service.update_workspace_metadata(
        workspace_id, "Successor authority", "", _op(150_056)
    )
    assert updated["name"] == "Successor authority"
    assert service._workspace_current_manifest(
        service._require_workspace(workspace_id)
    ).authority_device_id == successor_device_id
    service.close()


def test_permanent_authority_loss_freezes_administration_but_not_chat(
    tmp_path: Path,
) -> None:
    service, _network = _service(tmp_path / "authority-loss", RNS.Identity(), "Alex")
    created = service.create_workspace(_op(150_100), "Frozen authority", "")
    workspace_id = created["id"]

    frozen = service.report_workspace_authority_loss(workspace_id, _op(150_101))
    assert frozen["authority_loss"] is True
    assert frozen["authority_administration_state"] == "permanently_frozen"
    message = service.send_workspace_message(
        workspace_id,
        created["general_channel_id"],
        "Ordinary authorized chat still works.",
        _op(150_102),
        _op(150_103),
    )
    assert message["text"] == "Ordinary authorized chat still works."
    with pytest.raises(ContactNotApproved, match="permanently frozen"):
        service.update_workspace_metadata(
            workspace_id, "Must not change", "", _op(150_104)
        )
    with pytest.raises(ContactNotApproved, match="permanently frozen"):
        service.create_workspace_invitation_command(workspace_id, _op(150_105))
    service.close()


def test_administrative_request_lifecycle_permissions_and_conflict_fail_closed(
    tmp_path: Path,
) -> None:
    (
        owner,
        owner_network,
        owner_profile,
        admin,
        admin_network,
        admin_profile,
        workspace,
        _admin_key,
        _admin_identity,
    ) = _joined_pair(tmp_path / "admin-lifecycle", base=141_000)
    workspace_id = workspace["id"]
    admin_member_id = admin._require_workspace(workspace_id)["local_member_id"]
    owner.change_workspace_role(
        workspace_id, admin_member_id, "admin", _op(141_010)
    )
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )

    # The baseline policy remains exact: an administrator is not silently
    # treated as the owner under owner_only.
    with pytest.raises((ContactNotApproved, IdentityMismatch)):
        admin.submit_workspace_admin_request(
            workspace_id, "invitation", _op(141_011)
        )
    for callback in (
        lambda: admin.update_workspace_metadata(
            workspace_id, "Changed", "", _op(141_012)
        ),
        lambda: admin.update_workspace_retention(
            workspace_id, 30, _op(141_013)
        ),
        lambda: admin.update_workspace_policies(
            workspace_id, "all_members", "all_members", _op(141_014)
        ),
        lambda: admin.close_workspace(workspace_id, _op(141_015)),
    ):
        with pytest.raises(ContactNotApproved):
            callback()

    owner.update_workspace_policies(
        workspace_id,
        "owner_and_admins",
        "owner_and_admins",
        _op(141_016),
        "owner_and_admins",
    )
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )

    cancelled = admin.submit_workspace_admin_request(
        workspace_id, "invitation", _op(141_017), note="Not handed off"
    )
    cancelled = admin.cancel_workspace_admin_request(
        workspace_id, cancelled["id"], _op(141_018)
    )
    assert cancelled["state"] == "cancelled"
    assert _flush(admin, admin_network) == []

    declined = admin.submit_workspace_admin_request(
        workspace_id,
        "member_removal",
        _op(141_019),
        target_member_id=admin_member_id,
        note="Audit a declined removal",
    )
    request_packets = _flush(admin, admin_network)
    assert len(request_packets) == 1
    with pytest.raises(ValidationError, match="handed-off"):
        admin.cancel_workspace_admin_request(
            workspace_id, declined["id"], _op(141_020)
        )
    _deliver_all(
        owner,
        request_packets,
        source_profile=admin_profile,
        recipient_profile=owner_profile,
    )
    incoming = owner.list_workspace_admin_requests(
        workspace_id, "incoming"
    )["requests"]
    pending_decline = next(
        item for item in incoming if item["request_kind"] == "member_removal"
    )
    owner.decide_workspace_admin_request(
        workspace_id, pending_decline["id"], False, _op(141_021)
    )
    decision_packets = _flush(owner, owner_network)
    _deliver_all(
        admin,
        decision_packets,
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    declined_status = admin.get_workspace_admin_request(
        workspace_id, declined["id"]
    )
    assert declined_status["state"] == "declined"
    assert admin._require_workspace(workspace_id)["local_role"] == "admin"

    approved = admin.submit_workspace_admin_request(
        workspace_id, "invitation", _op(141_022), note="Conflict probe"
    )
    _deliver_all(
        owner,
        _flush(admin, admin_network),
        source_profile=admin_profile,
        recipient_profile=owner_profile,
    )
    owner_request = next(
        item for item in owner.list_workspace_admin_requests(
            workspace_id, "incoming"
        )["requests"]
        if item["request_kind"] == "invitation"
    )
    owner.decide_workspace_admin_request(
        workspace_id, owner_request["id"], True, _op(141_023)
    )
    approved_packets = _flush(owner, owner_network)
    _deliver_all(
        admin,
        approved_packets,
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    stored = admin.store.get("workspace_admin_request", approved["id"])
    assert stored is not None
    base = admin._workspace_manifest_by_digest(stored["base_manifest_digest"])
    assert base is not None and owner._identity is not None
    request = verify_workspace_admin_request(
        stored["document"], manifest=base, allow_expired=True
    )
    conflicting_raw = create_workspace_admin_decision(
        owner._identity,
        authority_manifest=base,
        request=request,
        outcome="declined",
        created_at=int(time.time()),
    )
    assert admin._receive_workspace_admin_request(WorkspaceWirePayload(
        kind="workspace_admin_request",
        logical_id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        expires_at=int(time.time()) + 3600,
        document=conflicting_raw,
    )) is False
    assert admin._require_workspace(workspace_id)["security_error"] == "admin_decision_conflict"
    assert admin.get_workspace_admin_request(
        workspace_id, approved["id"]
    )["state"] == "failed"

    # A direct owner authority transition wins. The related request is
    # superseded and the delivered manifest removes admin access immediately.
    role_request = admin.submit_workspace_admin_request(
        workspace_id,
        "role_change",
        _op(141_024),
        target_member_id=admin_member_id,
        requested_role="member",
    )
    _deliver_all(
        owner,
        _flush(admin, admin_network),
        source_profile=admin_profile,
        recipient_profile=owner_profile,
    )
    owner_role_request = next(
        item for item in owner.list_workspace_admin_requests(
            workspace_id, "incoming"
        )["requests"]
        if item["request_kind"] == "role_change"
    )
    owner.change_workspace_role(
        workspace_id, admin_member_id, "member", _op(141_025)
    )
    assert owner.get_workspace_admin_request(
        workspace_id, owner_role_request["id"]
    )["state"] == "superseded"
    _deliver_all(
        admin,
        _flush(owner, owner_network),
        source_profile=owner_profile,
        recipient_profile=admin_profile,
    )
    assert admin._require_workspace(workspace_id)["local_role"] == "member"
    with pytest.raises(ContactNotApproved, match="owners and administrators"):
        admin.create_workspace_channel(
            workspace_id, "demoted", "", _op(141_026)
        )
    owner.close()
    admin.close()
