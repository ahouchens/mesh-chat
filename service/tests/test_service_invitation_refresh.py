from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import RNS

from mesh_chat.invitations import MAX_HINTS, create_invitation, readable_fingerprint
from mesh_chat.models import Contact, DeliveryState, Message, MessageKind, TrustState
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class RecordingNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.events: list[str] = []
        self.applied_settings: list[dict[str, object]] = []
        self.path_requests: list[bytes] = []

    def apply_connection_settings(self, settings: NetworkSettings) -> None:
        self.events.append("apply_settings")
        self.applied_settings.append(settings.to_dict())

    def recipient_ready(self, _destination: bytes) -> bool:
        self.events.append("retry_request")
        return False

    def request_path(self, destination: bytes) -> None:
        self.path_requests.append(destination)

    def shutdown(self) -> None:
        pass


def test_reimport_existing_contact_refreshes_hints_and_retries_request(
    tmp_path: Path,
) -> None:
    old_hint = {"type": "tcp", "host": "192.0.2.10", "port": 4242}
    new_hint = {"type": "tcp", "host": "192.168.4.24", "port": 4242}
    peer = RNS.Identity()
    public_key = peer.get_public_key()
    destination = RNS.Destination.hash(peer, "lxmf", "delivery")
    contact = Contact(
        id="alex",
        display_name="Alex",
        public_identity=base64.urlsafe_b64encode(public_key).decode("ascii"),
        identity_hash=peer.hash.hex(),
        destination_hash=destination.hex(),
        fingerprint=readable_fingerprint(public_key),
        trust=TrustState.AWAITING_CONSENT,
        connection_hints=[old_hint],
        created_at=10,
        updated_at=10,
    ).to_dict()
    request = Message(
        id="pending-request",
        conversation_id="conversation",
        contact_id=contact["id"],
        direction="outbound",
        kind=MessageKind.CONTACT_REQUEST,
        text="",
        state=DeliveryState.QUEUED,
        created_at=time.time(),
        expires_at=time.time() + 3600,
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    store.put(
        "settings",
        "network",
        NetworkSettings(tcp_clients=[old_hint]).to_dict(),
    )
    store.put("contact", contact["id"], contact)
    store.put("message", request["id"], request)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    # Add the minimal local profile after construction so the import guard is
    # exercised without starting a real Reticulum interface in this unit test.
    store.put("profile", "local", {"destination_hash": "11" * 16})
    # This test drives retries synchronously and does not need the background
    # outbox loop racing its ordering assertions.
    service._shutdown.set()
    network = RecordingNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        refreshed = service.accept_invitation(
            create_invitation(peer, "Alex", hints=[new_hint])["text"]
        )

        assert refreshed["connection_hints"] == [new_hint]
        assert refreshed["updated_at"] > contact["updated_at"]
        persisted = store.get("contact", contact["id"])
        assert persisted is not None
        assert persisted["connection_hints"] == [new_hint]

        persisted_settings = store.get("settings", "network")
        assert persisted_settings is not None
        assert persisted_settings["tcp_clients"] == [new_hint]
        assert network.applied_settings[-1]["tcp_clients"] == [new_hint]
        assert network.events[:2] == ["apply_settings", "retry_request"]
        assert network.path_requests == [destination]
        assert store.get("message", request["id"])["state"] == "waiting_for_keys"
    finally:
        service.close()


def test_reimport_without_hints_removes_stale_route_live_and_from_storage(
    tmp_path: Path,
) -> None:
    old_hint = {"type": "tcp", "host": "192.168.4.24", "port": 4242}
    peer = RNS.Identity()
    public_key = peer.get_public_key()
    destination = RNS.Destination.hash(peer, "lxmf", "delivery")
    contact = Contact(
        id="alex",
        display_name="Alex",
        public_identity=base64.urlsafe_b64encode(public_key).decode("ascii"),
        identity_hash=peer.hash.hex(),
        destination_hash=destination.hex(),
        fingerprint=readable_fingerprint(public_key),
        trust=TrustState.APPROVED,
        connection_hints=[old_hint],
        created_at=10,
        updated_at=10,
    ).to_dict()
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(tcp_clients=[old_hint]).to_dict())
    store.put("contact", contact["id"], contact)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    store.put("profile", "local", {"destination_hash": "11" * 16})
    service._shutdown.set()
    network = RecordingNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        refreshed = service.accept_invitation(create_invitation(peer, "Alex")["text"])

        assert refreshed["connection_hints"] == []
        assert service.settings.tcp_clients == []
        assert store.get("settings", "network")["tcp_clients"] == []
        assert network.applied_settings[-1]["tcp_clients"] == []
    finally:
        service.close()


def test_contact_routes_are_prioritized_and_bounded_to_valid_settings(
    tmp_path: Path,
) -> None:
    existing = [
        {"type": "tcp", "host": f"192.168.1.{index}", "port": 42000 + index}
        for index in range(1, MAX_HINTS + 1)
    ]
    newest = [
        {"type": "tcp", "host": "192.168.4.24", "port": 43123},
        {"type": "tcp", "host": "192.168.4.25", "port": 43123},
    ]
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(tcp_clients=existing).to_dict())
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    network = RecordingNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        service._apply_contact_hints({"connection_hints": newest})

        assert service.settings.tcp_clients[:2] == newest
        assert len(service.settings.tcp_clients) == MAX_HINTS
        persisted = store.get("settings", "network")
        assert persisted is not None
        assert NetworkSettings.from_dict(persisted).tcp_clients == service.settings.tcp_clients
        assert network.applied_settings[-1]["tcp_clients"] == service.settings.tcp_clients
    finally:
        service.close()


def test_attempt_restores_all_evicted_contact_routes_before_requesting_keys(
    tmp_path: Path,
) -> None:
    restored = [
        {"type": "tcp", "host": "192.168.4.24", "port": 43123},
        {"type": "tcp", "host": "192.168.4.25", "port": 43123},
    ]
    # The preferred route is still active, but the alternate was evicted. This
    # specifically verifies that any missing stored hint restores the complete
    # route set instead of checking only the first address.
    existing = [
        restored[0],
        *[
            {"type": "tcp", "host": f"192.168.1.{index}", "port": 42000 + index}
            for index in range(1, MAX_HINTS)
        ],
    ]
    peer = RNS.Identity()
    destination = RNS.Destination.hash(peer, "lxmf", "delivery")
    contact = Contact(
        id="older-contact",
        display_name="Older contact",
        public_identity=base64.urlsafe_b64encode(peer.get_public_key()).decode("ascii"),
        identity_hash=peer.hash.hex(),
        destination_hash=destination.hex(),
        fingerprint=readable_fingerprint(peer.get_public_key()),
        trust=TrustState.APPROVED,
        connection_hints=restored,
        created_at=10,
        updated_at=10,
    ).to_dict()
    outbound = Message(
        id="queued-chat",
        conversation_id="conversation",
        contact_id=contact["id"],
        direction="outbound",
        kind=MessageKind.CHAT,
        text="hello",
        state=DeliveryState.QUEUED,
        created_at=time.time(),
        expires_at=time.time() + 3600,
    ).to_dict()
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    store.put("settings", "network", NetworkSettings(tcp_clients=existing).to_dict())
    store.put("contact", contact["id"], contact)
    store.put("message", outbound["id"], outbound)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    network = RecordingNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        service._attempt(outbound["id"])

        assert service.settings.tcp_clients[:2] == restored
        assert len(service.settings.tcp_clients) == MAX_HINTS
        assert network.events[:2] == ["apply_settings", "retry_request"]
        assert network.path_requests == [destination]
        persisted = store.get("settings", "network")
        assert persisted is not None
        assert NetworkSettings.from_dict(persisted).tcp_clients == service.settings.tcp_clients
    finally:
        service.close()
