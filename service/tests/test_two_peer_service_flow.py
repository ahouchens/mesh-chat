from __future__ import annotations

import base64
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import LXMF
import pytest
import RNS

from mesh_chat.app_protocol import build_fields, conversation_id, parse_payload
from mesh_chat.errors import ValidationError
from mesh_chat.invitations import verify_invitation
from mesh_chat.models import Contact, DeliveryState, MessageKind, TrustState
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


@dataclass(slots=True)
class QueuedWireMessage:
    sender: "DeterministicPeerNetwork"
    recipient_destination: bytes
    text: str
    fields: dict[int, Any]
    native_id: str


class DeterministicPeerHub:
    """A queued, in-memory stand-in for Reticulum's asynchronous handoff."""

    def __init__(self) -> None:
        self.peers: dict[bytes, DeterministicPeerNetwork] = {}
        self.pending: list[QueuedWireMessage] = []
        self.delivered_kinds: list[MessageKind] = []
        self._next_native_id = 1

    def register(self, peer: "DeterministicPeerNetwork") -> None:
        profile = peer.service.store.get("profile", "local")
        assert profile is not None
        destination = bytes.fromhex(profile["destination_hash"])
        assert destination not in self.peers
        self.peers[destination] = peer

    def queue(
        self,
        sender: "DeterministicPeerNetwork",
        recipient_destination: bytes,
        text: str,
        fields: dict[int, Any],
    ) -> str:
        native_id = f"{self._next_native_id:064x}"
        self._next_native_id += 1
        self.pending.append(
            QueuedWireMessage(sender, recipient_destination, text, fields, native_id)
        )
        return native_id

    def drain(self) -> None:
        # Delivery is intentionally queued instead of re-entrant. Reticulum
        # callbacks arrive after send() returns; matching that ordering catches
        # state-transition bugs without sockets, timers, or host networking.
        while self.pending:
            wire = self.pending.pop(0)
            recipient = self.peers[wire.recipient_destination]
            sender_profile = wire.sender.service.store.get("profile", "local")
            assert sender_profile is not None
            source = bytes.fromhex(sender_profile["destination_hash"])
            native = LXMF.LXMessage(
                None,
                None,
                content=wire.text,
                fields=wire.fields,
                desired_method=LXMF.LXMessage.DIRECT,
                destination_hash=wire.recipient_destination,
                source_hash=source,
            )
            parsed = parse_payload(native)
            if parsed.kind == MessageKind.CONTACT_REQUEST:
                invitation = verify_invitation(parsed.invitation or "")
                assert invitation.destination_hash == source

            recipient.service._on_inbound(native)
            wire.sender.service._on_native_status(
                parsed.logical_id,
                DeliveryState.RECEIVED_BY_ENDPOINT,
                wire.native_id,
            )
            self.delivered_kinds.append(parsed.kind)


class DeterministicPeerNetwork:
    interface_available = True

    def __init__(self, hub: DeterministicPeerHub) -> None:
        self.hub = hub
        self.service: MeshChatService
        self.remembered: dict[bytes, bytes] = {}
        self.cancelled: list[set[str]] = []

    def invitation_hints(self) -> list[dict[str, Any]]:
        return []

    def remember_contact(self, public_key: bytes, destination: bytes) -> None:
        identity = RNS.Identity(create_keys=False)
        assert identity.load_public_key(public_key)
        assert RNS.Destination.hash(identity, "lxmf", "delivery") == destination
        self.remembered[destination] = public_key

    def recipient_ready(self, destination: bytes) -> bool:
        return destination in self.remembered and destination in self.hub.peers

    def path_known(self, destination: bytes) -> bool:
        return destination in self.hub.peers

    def request_path(self, _destination: bytes) -> None:
        pass

    def apply_connection_settings(self, _settings: NetworkSettings) -> None:
        pass

    def send(
        self,
        *,
        logical_id: str,
        conversation_id: str,
        recipient_public_key: bytes,
        recipient_destination: bytes,
        kind: MessageKind,
        text: str,
        expires_at: int,
        receipt_for: str | None = None,
        invitation: str | None = None,
        propagated: bool = False,
        reaction_for: str | None = None,
        reaction_emoji: str | None = None,
        reaction_active: bool | None = None,
        reaction_revision: int | None = None,
    ) -> str:
        assert propagated is False
        assert self.remembered[recipient_destination] == recipient_public_key
        recipient_profile = self.hub.peers[recipient_destination].service.store.get(
            "profile", "local"
        )
        assert recipient_profile is not None
        assert base64.urlsafe_b64decode(recipient_profile["public_identity"]) == (
            recipient_public_key
        )
        fields = build_fields(
            kind=kind,
            logical_id=logical_id,
            conversation=conversation_id,
            expires_at=expires_at,
            receipt_for=receipt_for,
            invitation=invitation,
            reaction_for=reaction_for,
            reaction_emoji=reaction_emoji,
            reaction_active=reaction_active,
            reaction_revision=reaction_revision,
        )
        return self.hub.queue(self, recipient_destination, text, fields)

    def snapshot(self) -> dict[str, Any]:
        return {"interface_available": True, "interfaces": []}

    def cancel_outbound(self, logical_ids: set[str]) -> int:
        self.cancelled.append(set(logical_ids))
        kept: list[QueuedWireMessage] = []
        removed = 0
        for wire in self.hub.pending:
            if wire.sender is not self:
                kept.append(wire)
                continue
            app = parse_payload(
                LXMF.LXMessage(
                    None,
                    None,
                    content=wire.text,
                    fields=wire.fields,
                    desired_method=LXMF.LXMessage.DIRECT,
                    destination_hash=wire.recipient_destination,
                    source_hash=b"\x00" * 16,
                )
            )
            if app.logical_id in logical_ids:
                removed += 1
            else:
                kept.append(wire)
        self.hub.pending = kept
        return removed

    def shutdown(self) -> None:
        pass


def _peer(
    root: Path, hub: DeterministicPeerHub
) -> tuple[MeshChatService, DeterministicPeerNetwork]:
    store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)
    store.put(
        "settings",
        "network",
        NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict(),
    )
    service = MeshChatService(store, root, lambda _event: None)
    service._shutdown.set()
    network = DeterministicPeerNetwork(hub)
    network.service = service
    service.network = network  # type: ignore[assignment]
    return service, network


def _command(
    service: MeshChatService,
    command_id: str,
    command: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    response, should_stop = service.dispatch(
        {
            "v": 1,
            "id": command_id,
            "command": command,
            "payload": payload or {},
        }
    )
    assert should_stop is False
    assert response["ok"] is True
    return response["result"]


def _approved_pair(
    root: Path,
) -> tuple[
    DeterministicPeerHub,
    MeshChatService,
    DeterministicPeerNetwork,
    dict[str, Any],
    MeshChatService,
    DeterministicPeerNetwork,
    dict[str, Any],
]:
    hub = DeterministicPeerHub()
    alex, alex_network = _peer(root / "alex", hub)
    blair, blair_network = _peer(root / "blair", hub)
    alex_profile = _command(
        alex, "setup-alex-profile", "create_profile", {"display_name": "Alex"}
    )
    blair_profile = _command(
        blair, "setup-blair-profile", "create_profile", {"display_name": "Blair"}
    )
    hub.register(alex_network)
    hub.register(blair_network)
    invitation = _command(alex, "setup-invite", "create_invitation")
    _command(
        blair,
        "setup-accept",
        "accept_invitation",
        {"invitation": invitation["text"]},
    )
    hub.drain()
    pending = alex.snapshot()["contacts"][0]
    alex_contact = _command(
        alex,
        "setup-approve",
        "approve_request",
        {"contact_id": pending["id"]},
    )
    hub.drain()
    blair_contact = blair.snapshot()["contacts"][0]
    assert alex_contact["destination_hash"] == blair_profile["destination_hash"]
    assert blair_contact["destination_hash"] == alex_profile["destination_hash"]
    return (
        hub,
        alex,
        alex_network,
        alex_contact,
        blair,
        blair_network,
        blair_contact,
    )


def _direct_reaction_native(
    *,
    source_profile: dict[str, Any],
    destination_profile: dict[str, Any],
    target_id: str,
    logical_id: str | None = None,
    emoji: str = "👍",
    active: bool = True,
    revision: int = 1,
) -> LXMF.LXMessage:
    source = bytes.fromhex(source_profile["destination_hash"])
    destination = bytes.fromhex(destination_profile["destination_hash"])
    return LXMF.LXMessage(
        None,
        None,
        content="",
        fields=build_fields(
            kind=MessageKind.REACTION,
            logical_id=logical_id or str(uuid.uuid4()),
            conversation=conversation_id(source, destination),
            expires_at=int(time.time()) + 60,
            reaction_for=target_id,
            reaction_emoji=emoji,
            reaction_active=active,
            reaction_revision=revision,
        ),
        desired_method=LXMF.LXMessage.DIRECT,
        destination_hash=destination,
        source_hash=source,
    )


def test_two_peers_complete_invitation_approval_and_chat_flow(tmp_path: Path) -> None:
    hub = DeterministicPeerHub()
    alex, alex_network = _peer(tmp_path / "alex", hub)
    blair, blair_network = _peer(tmp_path / "blair", hub)

    try:
        alex_profile = _command(
            alex, "alex-profile", "create_profile", {"display_name": "Alex"}
        )
        blair_profile = _command(
            blair, "blair-profile", "create_profile", {"display_name": "Blair"}
        )
        hub.register(alex_network)
        hub.register(blair_network)

        invitation = _command(alex, "alex-invite", "create_invitation")
        preview = _command(
            blair,
            "blair-preview",
            "preview_invitation",
            {"invitation": invitation["text"]},
        )
        assert preview["destination_hash"] == alex_profile["destination_hash"]

        awaiting = _command(
            blair,
            "blair-accept",
            "accept_invitation",
            {"invitation": invitation["text"]},
        )
        assert awaiting["trust"] == "awaiting_consent"
        assert hub.pending

        hub.drain()
        alex_snapshot = _command(alex, "alex-pending-snapshot", "snapshot")
        pending = alex_snapshot["contacts"][0]
        assert pending["display_name"] == "Blair"
        assert pending["trust"] == "pending_request"
        assert pending["destination_hash"] == blair_profile["destination_hash"]

        approved = _command(
            alex,
            "alex-approve",
            "approve_request",
            {"contact_id": pending["id"]},
        )
        assert approved["trust"] == "approved"
        hub.drain()

        blair_snapshot = _command(blair, "blair-approved-snapshot", "snapshot")
        blair_contact = blair_snapshot["contacts"][0]
        assert blair_contact["trust"] == "approved"

        outbound = _command(
            blair,
            "blair-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "North gate is secured."},
        )
        assert outbound["state"] == "sending"
        hub.drain()

        alex_final = _command(alex, "alex-final-snapshot", "snapshot")
        blair_final = _command(blair, "blair-final-snapshot", "snapshot")
        inbound = alex_final["messages"][0]
        delivered = blair_final["messages"][0]

        assert inbound["direction"] == "inbound"
        assert inbound["text"] == "North gate is secured."
        assert inbound["state"] == "delivered"
        assert delivered["direction"] == "outbound"
        assert delivered["id"] == inbound["id"]
        assert delivered["conversation_id"] == inbound["conversation_id"]
        assert delivered["state"] == "delivered"
        assert hub.delivered_kinds[0] == MessageKind.CONTACT_REQUEST
        assert MessageKind.CONTACT_ACCEPT in hub.delivered_kinds
        assert hub.delivered_kinds[-2:] == [MessageKind.CHAT, MessageKind.RECEIPT]
        assert alex_final["groups"] == []
        assert blair_final["groups"] == []

        _command(
            blair,
            "blair-private-draft",
            "save_draft",
            {"contact_id": blair_contact["id"], "text": "discard this draft"},
        )
        deleted = _command(
            blair,
            "blair-delete-chat",
            "delete_conversation",
            {"kind": "direct", "id": blair_contact["id"]},
        )
        assert deleted["deleted_messages"] == 1
        replayed_send, _ = blair.dispatch(
            {
                "v": 1,
                "id": "blair-chat",
                "command": "send_message",
                "payload": {
                    "contact_id": blair_contact["id"],
                    "text": "North gate is secured.",
                },
            }
        )
        replayed_draft, _ = blair.dispatch(
            {
                "v": 1,
                "id": "blair-private-draft",
                "command": "save_draft",
                "payload": {
                    "contact_id": blair_contact["id"],
                    "text": "discard this draft",
                },
            }
        )
        assert replayed_send["ok"] is False
        assert replayed_send["error"]["code"] == "command_result_deleted"
        assert replayed_draft["ok"] is False
        assert replayed_draft["error"]["code"] == "command_result_deleted"
        after_replays = _command(blair, "blair-after-delete", "snapshot")
        assert after_replays["messages"] == []
        assert after_replays["drafts"] == []
        assert not hub.pending
    finally:
        alex.close()
        blair.close()


def test_direct_reactions_are_idempotent_ordered_authorized_and_cross_device(
    tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        _alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        message = _command(
            blair,
            "reaction-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Gate checked"},
        )
        _command(
            blair,
            "reaction-before-chat",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "👍",
                "active": True,
            },
        )
        # Exercise the bounded pending path: the authenticated reaction reaches
        # the receiver before the chat it names, then is applied atomically when
        # that target arrives.
        assert len(hub.pending) == 2
        hub.pending.reverse()
        hub.drain()
        alex_message = alex.snapshot()["messages"][0]
        assert alex_message["id"] == message["id"]
        assert alex_message["reactions"] == [
            {"emoji": "👍", "count": 1, "reacted_by_self": False}
        ]
        assert alex.store.list("pending_reaction") == []

        # One actor owns one reaction slot. A newer emoji replaces the older
        # value even if native delivery is reversed; the stale update is still
        # acknowledged and therefore stops retrying.
        _command(
            alex,
            "alex-reaction-one",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "😂",
                "active": True,
            },
        )
        superseded_wire = hub.pending[0]
        _command(
            alex,
            "alex-reaction-two",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "❤️",
                "active": True,
            },
        )
        # The adapter normally cancels the superseded native attempt. A late
        # copy already in flight can still arrive after the newer revision, so
        # inject that captured packet explicitly after draining the current one.
        assert len(hub.pending) == 1
        hub.drain()
        alex_profile = alex.store.get("profile", "local")
        blair_profile = blair.store.get("profile", "local")
        assert alex_profile is not None and blair_profile is not None
        blair._on_inbound(
            LXMF.LXMessage(
                None,
                None,
                content=superseded_wire.text,
                fields=superseded_wire.fields,
                desired_method=LXMF.LXMessage.DIRECT,
                destination_hash=bytes.fromhex(
                    blair_profile["destination_hash"]
                ),
                source_hash=bytes.fromhex(alex_profile["destination_hash"]),
            )
        )
        blair_reactions = blair.snapshot()["messages"][0]["reactions"]
        assert blair_reactions == [
            {"emoji": "👍", "count": 1, "reacted_by_self": True},
            {"emoji": "❤️", "count": 1, "reacted_by_self": False},
        ]

        # A conflicting packet at the already-applied revision cannot rewrite
        # state, but is acknowledged so it cannot create an endless retry.
        conflicting_id = str(uuid.uuid4())
        conflicting = LXMF.LXMessage(
            None,
            None,
            content="",
            fields=build_fields(
                kind=MessageKind.REACTION,
                logical_id=conflicting_id,
                conversation=conversation_id(
                    bytes.fromhex(alex_profile["destination_hash"]),
                    bytes.fromhex(blair_profile["destination_hash"]),
                ),
                expires_at=int(time.time()) + 60,
                reaction_for=message["id"],
                reaction_emoji="😢",
                reaction_active=True,
                reaction_revision=2,
            ),
            desired_method=LXMF.LXMessage.DIRECT,
            destination_hash=bytes.fromhex(blair_profile["destination_hash"]),
            source_hash=bytes.fromhex(alex_profile["destination_hash"]),
        )
        blair._on_inbound(conflicting)
        assert blair.snapshot()["messages"][0]["reactions"] == blair_reactions
        assert any(
            item.get("kind") == MessageKind.RECEIPT.value
            and item.get("receipt_for") == conflicting_id
            for item in blair.store.list("message")
        )
        hub.drain()

        before_remove_retry = len(hub.pending)
        _command(
            alex,
            "alex-reaction-remove",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "❤️",
                "active": False,
            },
        )
        hub.drain()
        assert blair.snapshot()["messages"][0]["reactions"] == [
            {"emoji": "👍", "count": 1, "reacted_by_self": True}
        ]
        _command(
            alex,
            "alex-reaction-remove-idempotent",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "❤️",
                "active": False,
            },
        )
        assert len(hub.pending) == before_remove_retry

        unknown_source = os.urandom(16)
        unauthorized = LXMF.LXMessage(
            None,
            None,
            content="",
            fields=build_fields(
                kind=MessageKind.REACTION,
                logical_id=str(uuid.uuid4()),
                conversation=conversation_id(
                    unknown_source,
                    bytes.fromhex(blair_profile["destination_hash"]),
                ),
                expires_at=int(time.time()) + 60,
                reaction_for=message["id"],
                reaction_emoji="🎉",
                reaction_active=True,
                reaction_revision=99,
            ),
            desired_method=LXMF.LXMessage.DIRECT,
            destination_hash=bytes.fromhex(blair_profile["destination_hash"]),
            source_hash=unknown_source,
        )
        blair._on_inbound(unauthorized)
        assert blair.snapshot()["messages"][0]["reactions"] == [
            {"emoji": "👍", "count": 1, "reacted_by_self": True}
        ]

        with pytest.raises(ValidationError, match="active state"):
            alex.dispatch(
                {
                    "v": 1,
                    "id": "malformed-reaction",
                    "command": "set_message_reaction",
                    "payload": {
                        "kind": "direct",
                        "message_id": message["id"],
                        "emoji": "👍",
                        "active": "yes",
                    },
                }
            )
    finally:
        alex.close()
        blair.close()


def test_direct_reaction_snapshot_includes_custom_unicode_emoji(
    tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        _alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        message = _command(
            blair,
            "unicode-reaction-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Field update"},
        )
        hub.drain()

        # These values are outside the original six-option quick set. Each
        # actor still owns one slot, and arbitrary supported emoji must not be
        # dropped by snapshot aggregation.
        alex.set_message_reaction("direct", message["id"], "🧑🏽\u200d🌾", True)
        blair.set_message_reaction("direct", message["id"], "🫨", True)
        hub.drain()

        alex_reactions = alex.snapshot()["messages"][0]["reactions"]
        blair_reactions = blair.snapshot()["messages"][0]["reactions"]
        assert alex_reactions == [
            {"emoji": "🧑🏽\u200d🌾", "count": 1, "reacted_by_self": True},
            {"emoji": "🫨", "count": 1, "reacted_by_self": False},
        ]
        assert blair_reactions == [
            {"emoji": "🧑🏽\u200d🌾", "count": 1, "reacted_by_self": False},
            {"emoji": "🫨", "count": 1, "reacted_by_self": True},
        ]
    finally:
        alex.close()
        blair.close()


def test_offline_direct_reaction_outbox_and_tombstone_survive_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        _alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    restarted: MeshChatService | None = None
    try:
        message = _command(
            blair,
            "offline-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Offline reaction target"},
        )
        hub.drain()
        key = bytes(alex.store._key)
        alex.network = None
        _command(
            alex,
            "offline-reaction",
            "set_message_reaction",
            {
                "kind": "direct",
                "message_id": message["id"],
                "emoji": "😮",
                "active": True,
            },
        )
        queued = [
            item
            for item in alex.store.list("message")
            if item.get("kind") == MessageKind.REACTION.value
        ]
        assert len(queued) == 1 and queued[0]["state"] == "queued"
        alex.close()

        monkeypatch.setattr(
            MeshChatService, "_start_network", lambda _self, _name: None
        )
        store = VaultStore(
            tmp_path / "alex", key, allow_unprotected_for_tests=True
        )
        restarted = MeshChatService(store, tmp_path / "alex", lambda _event: None)
        restarted._shutdown.set()
        snapshot = restarted.snapshot()
        assert snapshot["messages"][0]["reactions"] == [
            {"emoji": "😮", "count": 1, "reacted_by_self": True}
        ]
        assert len(
            [
                item
                for item in restarted.store.list("message")
                if item.get("kind") == MessageKind.REACTION.value
                and item.get("state") == "queued"
            ]
        ) == 1

        # Reissuing the same desired state after restart is idempotent and does
        # not create a second durable operation.
        restarted.set_message_reaction("direct", message["id"], "😮", True)
        assert len(
            [
                item
                for item in restarted.store.list("message")
                if item.get("kind") == MessageKind.REACTION.value
            ]
        ) == 1
    finally:
        if restarted is not None:
            restarted.close()
        else:
            alex.close()
        blair.close()


def test_reaction_command_is_idempotent_and_replay_after_delete_fails_closed(
    tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        _alex_contact,
        blair,
        blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    blair_closed = False
    try:
        message = _command(
            blair,
            "reaction-cache-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Cache target"},
        )
        hub.drain()
        payload = {
            "kind": "direct",
            "message_id": message["id"],
            "emoji": "🎉",
            "active": True,
        }
        first = _command(
            blair, "reaction-cache-command", "set_message_reaction", payload
        )
        first_state = blair.store.list("reaction")
        first_operations = [
            item
            for item in blair.store.list("message")
            if item.get("kind") == MessageKind.REACTION.value
        ]
        replay = _command(
            blair, "reaction-cache-command", "set_message_reaction", payload
        )
        assert replay == first
        assert blair.store.list("reaction") == first_state
        assert [
            item
            for item in blair.store.list("message")
            if item.get("kind") == MessageKind.REACTION.value
        ] == first_operations

        _command(
            blair,
            "reaction-cache-delete",
            "delete_conversation",
            {"kind": "direct", "id": blair_contact["id"]},
        )
        rejected, _ = blair.dispatch(
            {
                "v": 1,
                "id": "reaction-cache-command",
                "command": "set_message_reaction",
                "payload": payload,
            }
        )
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "command_result_deleted"
        assert blair.store.list("reaction") == []
        assert not any(
            item.get("kind") == MessageKind.REACTION.value
            for item in blair.store.list("message")
        )
        assert not hub.pending

        actor = blair.store.get("profile", "local")["destination_hash"]
        vault_path = tmp_path / "blair" / "mesh-chat.vault"
        blair.close()
        blair_closed = True
        raw = vault_path.read_bytes()
        assert message["id"].encode("ascii") not in raw
        assert "🎉".encode("utf-8") not in raw
        assert actor.encode("ascii") not in raw
    finally:
        alex.close()
        if not blair_closed:
            blair.close()


def test_direct_reaction_receipts_are_bounded_and_hidden_random_targets_are_ignored(
    tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        alex_network,
        alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        message = _command(
            blair,
            "receipt-cap-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Receipt target"},
        )
        hub.drain()
        alex_profile = alex.store.get("profile", "local")
        blair_profile = blair.store.get("profile", "local")
        assert alex_profile is not None and blair_profile is not None

        alex._on_inbound(
            _direct_reaction_native(
                source_profile=blair_profile,
                destination_profile=alex_profile,
                target_id=message["id"],
                revision=10,
                emoji="😮",
            )
        )
        for revision in range(1, 8):
            alex._on_inbound(
                _direct_reaction_native(
                    source_profile=blair_profile,
                    destination_profile=alex_profile,
                    target_id=message["id"],
                    revision=revision,
                )
            )
        receipts = [
            item
            for item in alex.store.list("message")
            if item.get("reaction_receipt") is True
            and item.get("reaction_target_message_id") == message["id"]
        ]
        assert len(receipts) == 4
        assert max(item["reaction_ack_revision"] for item in receipts) == 10
        assert alex_network.cancelled
        assert len(set().union(*alex_network.cancelled)) >= 4

        alex.delete_conversation("direct", alex_contact["id"])
        assert not any(
            item.get("reaction_receipt") is True
            for item in alex.store.list("message")
        )
        pending_before = len(hub.pending)
        for _ in range(300):
            alex._on_inbound(
                _direct_reaction_native(
                    source_profile=blair_profile,
                    destination_profile=alex_profile,
                    target_id=str(uuid.uuid4()),
                )
            )
        assert not any(
            item.get("reaction_receipt") is True
            for item in alex.store.list("message")
        )
        assert alex.store.list("pending_reaction") == []
        assert len(hub.pending) == pending_before
    finally:
        alex.close()
        blair.close()


def test_deleted_direct_reaction_target_stays_deleted_after_restore_and_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    restarted: MeshChatService | None = None
    alex_closed = False
    try:
        message = _command(
            blair,
            "deleted-target-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Delete this target"},
        )
        hub.drain()
        alex_profile = alex.store.get("profile", "local")
        blair_profile = blair.store.get("profile", "local")
        assert alex_profile is not None and blair_profile is not None
        key = bytes(alex.store._key)
        alex.delete_conversation("direct", alex_contact["id"])
        alex.restore_conversation("direct", alex_contact["id"])

        alex._on_inbound(
            _direct_reaction_native(
                source_profile=blair_profile,
                destination_profile=alex_profile,
                target_id=message["id"],
            )
        )
        assert alex.store.list("reaction") == []
        assert alex.store.list("pending_reaction") == []
        alex.close()
        alex_closed = True

        monkeypatch.setattr(
            MeshChatService, "_start_network", lambda _self, _name: None
        )
        reopened_store = VaultStore(
            tmp_path / "alex", key, allow_unprotected_for_tests=True
        )
        restarted = MeshChatService(
            reopened_store, tmp_path / "alex", lambda _event: None
        )
        restarted._shutdown.set()
        restarted._on_inbound(
            _direct_reaction_native(
                source_profile=blair_profile,
                destination_profile=alex_profile,
                target_id=message["id"],
                revision=2,
            )
        )
        assert restarted.store.list("reaction") == []
        assert restarted.store.list("pending_reaction") == []
        assert restarted.snapshot()["messages"] == []
    finally:
        if restarted is not None:
            restarted.close()
        elif not alex_closed:
            alex.close()
        blair.close()


def test_direct_reaction_receipt_lookup_is_bound_to_contact_and_conversation(
    tmp_path: Path,
) -> None:
    (
        _hub,
        alex,
        _alex_network,
        alex_contact,
        blair,
        _blair_network,
        _blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        fake_identity = RNS.Identity()
        fake_public = fake_identity.get_public_key()
        fake_destination = RNS.Destination.hash(
            fake_identity, "lxmf", "delivery"
        )
        other = Contact(
            id="other-contact",
            display_name="Other",
            public_identity=base64.urlsafe_b64encode(fake_public).decode("ascii"),
            identity_hash=fake_identity.hash.hex(),
            destination_hash=fake_destination.hex(),
            fingerprint="other",
            trust=TrustState.APPROVED,
        ).to_dict()
        alex.store.put("contact", other["id"], other)
        profile = alex.store.get("profile", "local")
        assert profile is not None
        app = SimpleNamespace(
            logical_id=str(uuid.uuid4()),
            conversation_id=conversation_id(
                bytes.fromhex(profile["destination_hash"]),
                bytes.fromhex(alex_contact["destination_hash"]),
            ),
            reaction_for=str(uuid.uuid4()),
            reaction_revision=1,
        )
        wrong = alex._direct_reaction_receipt_record(other, app)
        alex.store.put("message", wrong["id"], wrong)

        alex._ensure_direct_reaction_receipt(alex_contact, app)

        matches = [
            item
            for item in alex.store.list("message")
            if item.get("reaction_receipt") is True
            and item.get("receipt_for") == app.logical_id
        ]
        assert {item["contact_id"] for item in matches} == {
            other["id"],
            alex_contact["id"],
        }
    finally:
        alex.close()
        blair.close()


def test_direct_callback_then_raise_does_not_resurrect_reaction_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        alex_network,
        alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        target = _command(
            blair,
            "callback-race-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Race target"},
        )
        hub.drain()

        def callback_then_raise(**values: Any) -> str:
            alex._on_native_status(
                values["logical_id"],
                DeliveryState.RECEIVED_BY_ENDPOINT,
                "native-sync",
            )
            raise RuntimeError("adapter unwound after callback")

        monkeypatch.setattr(alex_network, "send", callback_then_raise)
        alex.set_message_reaction("direct", target["id"], "👍", True)
        assert not any(
            item.get("kind") == MessageKind.REACTION.value
            for item in alex.store.list("message")
        )

        alex_profile = alex.store.get("profile", "local")
        blair_profile = blair.store.get("profile", "local")
        assert alex_profile is not None and blair_profile is not None
        alex._on_inbound(
            _direct_reaction_native(
                source_profile=blair_profile,
                destination_profile=alex_profile,
                target_id=target["id"],
                emoji="🎉",
            )
        )
        assert not any(
            item.get("reaction_receipt") is True
            for item in alex.store.list("message")
        )
        assert alex.store.list("reaction")
        assert alex_contact["id"] == alex.snapshot()["messages"][0]["contact_id"]
    finally:
        alex.close()
        blair.close()


def test_direct_reaction_only_terminal_rows_are_removed_on_recovery(
    tmp_path: Path,
) -> None:
    (
        hub,
        alex,
        _alex_network,
        _alex_contact,
        blair,
        _blair_network,
        blair_contact,
    ) = _approved_pair(tmp_path)
    try:
        target = _command(
            blair,
            "terminal-chat",
            "send_message",
            {"contact_id": blair_contact["id"], "text": "Terminal target"},
        )
        hub.drain()
        alex.network = None
        alex.set_message_reaction("direct", target["id"], "😢", True)
        operation = next(
            item
            for item in alex.store.list("message")
            if item.get("kind") == MessageKind.REACTION.value
        )
        operation["state"] = DeliveryState.DELIVERED.value
        alex.store.put("message", operation["id"], operation)
        alex._recover_outbox()
        assert alex.store.get("message", operation["id"]) is None

        receipt = dict(operation)
        receipt.update(
            {
                "id": str(uuid.uuid4()),
                "kind": MessageKind.RECEIPT.value,
                "reaction_receipt": True,
                "state": DeliveryState.EXPIRED.value,
                "expires_at": time.time() - 1,
            }
        )
        alex.store.put("message", receipt["id"], receipt)
        alex._recover_outbox()
        assert alex.store.get("message", receipt["id"]) is None
        assert alex.store.list("reaction")
    finally:
        alex.close()
        blair.close()
