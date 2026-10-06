from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import RNS
import pytest

from mesh_chat.errors import NetworkUnavailable
from mesh_chat.invitations import MAX_HINTS, readable_fingerprint
from mesh_chat.models import Contact, DeliveryState, MessageKind, TrustState
from mesh_chat.network import ReticulumNetwork, install_embedded_runtime_guards
from mesh_chat.reticulum_config import NetworkSettings
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


def test_runtime_guard_makes_reverse_tcp_route_attachment_nonblocking() -> None:
    """A full signed-hint set must not consume the desktop command timeout.

    Upstream TCP clients synchronously perform their first connection attempt
    by default. With the eight allowed invitation hints, serial five-second
    dials can keep ``approve_request`` inside the sidecar beyond the desktop's
    command deadline. The embedded runtime setup must select upstream's
    asynchronous start path before any configured or dynamically attached TCP
    client is constructed.
    """

    class FakeTCPClient:
        SYNCHRONOUS_START = True

    class FakeTCPServer:
        def incoming_connection(self, _handler: Any) -> None:
            pass

    class FakeTransport:
        interfaces: list[Any] = []

        @classmethod
        def remove_interface(cls, interface: Any) -> None:
            cls.interfaces.remove(interface)

    class FakeReticulum:
        def _synthesize_interface(self) -> None:
            pass

    fake_module = SimpleNamespace(
        Interfaces=SimpleNamespace(
            TCPInterface=SimpleNamespace(
                TCPClientInterface=FakeTCPClient,
                TCPServerInterface=FakeTCPServer,
            )
        ),
        Reticulum=FakeReticulum,
        Transport=FakeTransport,
        panic=lambda: None,
        exit=lambda _code=0: None,
    )

    install_embedded_runtime_guards(fake_module)

    assert FakeTCPClient.SYNCHRONOUS_START is False


def test_eight_reverse_routes_attach_within_command_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dynamic route attachment must not serially wait on eight TCP dials."""

    install_embedded_runtime_guards()

    class TimedAttacher:
        def __init__(self) -> None:
            self.attached: list[str] = []

        def attach_interface(self, name: str) -> bool:
            self.attached.append(name)
            if RNS.Interfaces.TCPInterface.TCPClientInterface.SYNCHRONOUS_START:
                # Eight serial waits would take 1.6 seconds. The production
                # guard must select upstream's asynchronous path first.
                time.sleep(0.2)
            return True

        def detach_interface(self, _name: str) -> bool:
            return True

    monkeypatch.setattr(RNS.Transport, "interfaces", [])
    attacher = TimedAttacher()
    network = object.__new__(ReticulumNetwork)
    network.rns_dir = tmp_path
    network.reticulum = attacher
    network.settings = NetworkSettings()
    settings = NetworkSettings(
        tcp_clients=[
            {
                "type": "tcp",
                "host": f"192.0.2.{index + 1}",
                "port": 42000 + index,
            }
            for index in range(MAX_HINTS)
        ]
    )

    started = time.monotonic()
    network.apply_connection_settings(settings)
    elapsed = time.monotonic() - started

    assert attacher.attached == [
        f"Private TCP peer {index + 1}" for index in range(MAX_HINTS)
    ]
    assert elapsed < 0.5


class ApprovalNetwork:
    interface_available = True

    def __init__(self) -> None:
        self.applied_settings: list[dict[str, Any]] = []
        self.sent_kinds: list[MessageKind] = []

    def apply_connection_settings(self, settings: NetworkSettings) -> None:
        self.applied_settings.append(settings.to_dict())

    def recipient_ready(self, _destination: bytes) -> bool:
        return True

    def path_known(self, _destination: bytes) -> bool:
        return True

    def request_path(self, _destination: bytes) -> None:
        pass

    def send(self, **value: Any) -> str:
        self.sent_kinds.append(value["kind"])
        return f"native-{len(self.sent_kinds)}"

    def snapshot(self) -> dict[str, Any]:
        return {"interface_available": True, "interfaces": []}

    def shutdown(self) -> None:
        pass


class FailingApprovalNetwork(ApprovalNetwork):
    def send(self, **value: Any) -> str:
        self.sent_kinds.append(value["kind"])
        raise RuntimeError("untyped upstream transport failure")


class FailingRecipientReadyNetwork(ApprovalNetwork):
    def __init__(self) -> None:
        super().__init__()
        self.ready_attempts = 0

    def recipient_ready(self, _destination: bytes) -> bool:
        self.ready_attempts += 1
        raise RuntimeError("untyped recipient readiness failure")


class RecoveringRouteNetwork(ApprovalNetwork):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.route_attempts = 0

    def apply_connection_settings(self, settings: NetworkSettings) -> None:
        self.route_attempts += 1
        if self.route_attempts <= self.failures:
            raise RuntimeError("temporary dynamic route failure")
        super().apply_connection_settings(settings)


class SwitchingSignedRouteNetwork(ApprovalNetwork):
    """Record signed-route selection before normal recipient readiness."""

    def __init__(self) -> None:
        super().__init__()
        self.route_checks: list[tuple[bytes, list[dict[str, Any]]]] = []
        self.readiness_checks: list[bytes] = []

    def prefer_signed_route(
        self,
        destination: bytes,
        connection_hints: list[dict[str, Any]],
    ) -> bool:
        self.route_checks.append(
            (destination, [dict(hint) for hint in connection_hints])
        )
        # The real adapter intentionally returns False after its bounded wait
        # when the signed route did not answer. Service delivery must then use
        # normal Reticulum fallback rather than pinning the durable outbox.
        return False

    def recipient_ready(self, destination: bytes) -> bool:
        assert self.route_checks
        self.readiness_checks.append(destination)
        return True


class SynchronousStatusNetwork(ApprovalNetwork):
    def __init__(self, state: DeliveryState) -> None:
        super().__init__()
        self.state = state
        self.service: MeshChatService | None = None

    def send(self, **value: Any) -> str:
        self.sent_kinds.append(value["kind"])
        native_id = f"native-{len(self.sent_kinds)}"
        assert self.service is not None
        # Exercise the ordering used by the real adapter, where callbacks can
        # update the durable record before send() returns to _attempt().
        self.service._on_native_status(value["logical_id"], self.state, native_id)
        return native_id


class SynchronousStatusThenRaiseNetwork(SynchronousStatusNetwork):
    def __init__(self, state: DeliveryState, error: Exception) -> None:
        super().__init__(state)
        self.error = error

    def send(self, **value: Any) -> str:
        self.sent_kinds.append(value["kind"])
        native_id = f"native-{len(self.sent_kinds)}"
        assert self.service is not None
        self.service._on_native_status(value["logical_id"], self.state, native_id)
        raise self.error


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


def _approved_direct_service(
    tmp_path: Path, network: ApprovalNetwork
) -> tuple[MeshChatService, VaultStore, dict[str, Any]]:
    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.APPROVED,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    service.network = network  # type: ignore[assignment]
    return service, store, contact


def test_first_chat_prefers_signed_tcp_before_handoff_but_allows_fallback(
    tmp_path: Path,
) -> None:
    """Route refresh runs first, without letting a bad hint pin the outbox."""

    network = SwitchingSignedRouteNetwork()
    service, store, contact = _approved_direct_service(tmp_path, network)
    hints = [{"type": "tcp", "host": "192.168.4.24", "port": 43123}]
    contact["connection_hints"] = hints
    store.put("contact", contact["id"], contact)

    try:
        outbound = service.send_message(contact["id"], "first phone message")
        destination = bytes.fromhex(contact["destination_hash"])

        assert outbound["state"] == DeliveryState.SENDING.value
        assert network.route_checks == [(destination, hints)]
        assert network.readiness_checks == [destination]
        assert network.sent_kinds == [MessageKind.CHAT]
        stored = store.get("message", outbound["id"])

        assert stored is not None
        assert stored["state"] == DeliveryState.SENDING.value
        assert stored["native_message_id"] == "native-1"
    finally:
        service.close()


@pytest.mark.parametrize(
    "callback_state",
    [DeliveryState.RECEIVED_BY_ENDPOINT, DeliveryState.DELIVERED],
)
def test_send_preserves_synchronous_stronger_native_status(
    tmp_path: Path, callback_state: DeliveryState
) -> None:
    network = SynchronousStatusNetwork(callback_state)
    service, store, contact = _approved_direct_service(tmp_path, network)
    network.service = service

    try:
        outbound = service.send_message(contact["id"], "fast callback")
        stored = store.get("message", outbound["id"])

        assert stored is not None
        assert outbound["state"] == callback_state.value
        assert stored["state"] == callback_state.value
        assert stored["native_message_id"] == "native-1"
        assert network.sent_kinds == [MessageKind.CHAT]
    finally:
        service.close()


@pytest.mark.parametrize(
    ("callback_state", "error"),
    [
        (DeliveryState.RECEIVED_BY_ENDPOINT, RuntimeError("raw send unwind")),
        (DeliveryState.DELIVERED, RuntimeError("raw send unwind")),
        (
            DeliveryState.RECEIVED_BY_ENDPOINT,
            NetworkUnavailable("typed send unwind"),
        ),
        (DeliveryState.DELIVERED, NetworkUnavailable("typed send unwind")),
    ],
)
def test_send_exception_cannot_retract_synchronous_endpoint_evidence(
    tmp_path: Path, callback_state: DeliveryState, error: Exception
) -> None:
    network = SynchronousStatusThenRaiseNetwork(callback_state, error)
    service, store, contact = _approved_direct_service(tmp_path, network)
    network.service = service

    try:
        outbound = service.send_message(contact["id"], "callback before unwind")
        stored = store.get("message", outbound["id"])

        assert stored is not None
        assert outbound["state"] == callback_state.value
        assert stored["state"] == callback_state.value
        assert stored["native_message_id"] == "native-1"
        assert network.sent_kinds == [MessageKind.CHAT]
    finally:
        service.close()


@pytest.mark.parametrize(
    "stale_state",
    [DeliveryState.QUEUED, DeliveryState.SENDING, DeliveryState.RECEIVED_BY_ENDPOINT],
)
def test_stale_prior_attempt_callback_cannot_rewrite_current_direct_attempt(
    tmp_path: Path, stale_state: DeliveryState
) -> None:
    network = ApprovalNetwork()
    service, store, contact = _approved_direct_service(tmp_path, network)

    try:
        outbound = service.send_message(contact["id"], "retry correlation")
        first_native_id = outbound["native_message_id"]
        assert first_native_id == "native-1"

        service._on_native_status(
            outbound["id"], DeliveryState.QUEUED, first_native_id
        )
        service._attempt(outbound["id"])
        current = store.get("message", outbound["id"])
        assert current is not None
        assert current["state"] == DeliveryState.SENDING.value
        assert current["native_message_id"] == "native-2"

        service._on_native_status(outbound["id"], stale_state, first_native_id)
        after_stale = store.get("message", outbound["id"])

        assert after_stale is not None
        assert after_stale["state"] == DeliveryState.SENDING.value
        assert after_stale["native_message_id"] == "native-2"
        assert network.sent_kinds == [MessageKind.CHAT, MessageKind.CHAT]
    finally:
        service.close()


def test_current_direct_attempt_status_cannot_regress_from_endpoint_evidence(
    tmp_path: Path,
) -> None:
    network = ApprovalNetwork()
    service, store, contact = _approved_direct_service(tmp_path, network)

    try:
        outbound = service.send_message(contact["id"], "monotonic evidence")
        native_id = outbound["native_message_id"]
        service._on_native_status(
            outbound["id"], DeliveryState.RECEIVED_BY_ENDPOINT, native_id
        )

        service._on_native_status(outbound["id"], DeliveryState.SENDING, native_id)
        service._on_native_status(outbound["id"], DeliveryState.QUEUED, native_id)
        stored = store.get("message", outbound["id"])

        assert stored is not None
        assert stored["state"] == DeliveryState.RECEIVED_BY_ENDPOINT.value
        assert stored["native_message_id"] == native_id
    finally:
        service.close()


def test_approve_request_sends_one_contact_accept_after_applying_reverse_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flushing queued chat must not immediately send CONTACT_ACCEPT twice."""

    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    reverse_hints = [
        {
            "type": "tcp",
            "host": f"192.168.50.{index + 1}",
            "port": 42000 + index,
        }
        for index in range(MAX_HINTS)
    ]
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.PENDING_REQUEST,
        connection_hints=reverse_hints,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    network = ApprovalNetwork()
    service.network = network  # type: ignore[assignment]
    transactions: list[list[tuple[str, str, dict[str, Any]]]] = []
    original_put_many = store.put_many

    def recording_put_many(
        records: Any,
    ) -> None:
        transaction = list(records)
        transactions.append(transaction)
        original_put_many(transaction)

    monkeypatch.setattr(store, "put_many", recording_put_many)

    try:
        approved = service.approve_request(contact["id"])

        assert approved["trust"] == TrustState.APPROVED.value
        assert network.applied_settings[-1]["tcp_clients"] == reverse_hints
        assert network.sent_kinds == [MessageKind.CONTACT_ACCEPT]
        accepts = [
            message
            for message in store.list("message")
            if message["kind"] == MessageKind.CONTACT_ACCEPT.value
        ]
        assert len(accepts) == 1
        assert accepts[0]["state"] == "sending"
        approval_transactions = [
            transaction
            for transaction in transactions
            if any(
                kind == "contact"
                and record_id == contact["id"]
                and value["trust"] == TrustState.APPROVED.value
                for kind, record_id, value in transaction
            )
        ]
        assert len(approval_transactions) == 1
        assert len(approval_transactions[0]) == 2
        assert any(
            kind == "message"
            and value["kind"] == MessageKind.CONTACT_ACCEPT.value
            for kind, _record_id, value in approval_transactions[0]
        )
    finally:
        service.close()


@pytest.mark.parametrize(
    "state",
    [
        DeliveryState.SENDING,
        DeliveryState.STORED_FOR_DELIVERY,
        DeliveryState.RECEIVED_BY_ENDPOINT,
    ],
)
def test_attempt_does_not_resend_in_flight_direct_messages(
    tmp_path: Path, state: DeliveryState
) -> None:
    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.APPROVED,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    network = ApprovalNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        message = service._create_outbound(contact, MessageKind.CHAT, "hello")
        message["state"] = state.value
        store.put("message", message["id"], message)

        service._attempt(message["id"])

        assert network.sent_kinds == []
        assert store.get("message", message["id"])["state"] == state.value
    finally:
        service.close()


def test_approve_request_contains_raw_transport_failure_and_keeps_accept_queued(
    tmp_path: Path,
) -> None:
    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.PENDING_REQUEST,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    network = FailingApprovalNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        approved = service.approve_request(contact["id"])

        assert approved["trust"] == TrustState.APPROVED.value
        assert network.sent_kinds == [MessageKind.CONTACT_ACCEPT]
        accepts = [
            message
            for message in store.list("message")
            if message["kind"] == MessageKind.CONTACT_ACCEPT.value
        ]
        assert len(accepts) == 1
        assert accepts[0]["state"] == DeliveryState.QUEUED.value
    finally:
        service.close()


def test_send_message_contains_raw_recipient_ready_failure_without_duplicate(
    tmp_path: Path,
) -> None:
    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.APPROVED,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    network = FailingRecipientReadyNetwork()
    service.network = network  # type: ignore[assignment]

    try:
        outbound = service.send_message(contact["id"], "saved once")

        assert outbound["state"] == DeliveryState.QUEUED.value
        assert network.ready_attempts == 1
        assert network.sent_kinds == []
        messages = [
            message
            for message in store.list("message")
            if message["kind"] == MessageKind.CHAT.value
        ]
        assert len(messages) == 1
        assert messages[0]["id"] == outbound["id"]

        service._attempt(outbound["id"])

        assert network.ready_attempts == 2
        assert len(
            [
                message
                for message in store.list("message")
                if message["kind"] == MessageKind.CHAT.value
            ]
        ) == 1
        assert store.get("message", outbound["id"])["state"] == DeliveryState.QUEUED.value
    finally:
        service.close()


def test_approve_request_survives_route_failure_and_retries_without_duplicate_accept(
    tmp_path: Path,
) -> None:
    local_identity = RNS.Identity()
    peer_identity = RNS.Identity()
    peer_profile = _profile(peer_identity, "Phone")
    reverse_hints = [
        {
            "type": "tcp",
            "host": f"192.0.2.{index + 1}",
            "port": 43000 + index,
        }
        for index in range(MAX_HINTS)
    ]
    contact = Contact(
        id="phone",
        display_name="Phone",
        public_identity=peer_profile["public_identity"],
        identity_hash=peer_profile["identity_hash"],
        destination_hash=peer_profile["destination_hash"],
        fingerprint=peer_profile["fingerprint"],
        trust=TrustState.PENDING_REQUEST,
        connection_hints=reverse_hints,
        created_at=time.time(),
        updated_at=time.time(),
    ).to_dict()

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    store.put("profile", "local", _profile(local_identity, "Desktop"))
    store.put("contact", contact["id"], contact)
    # Approval attempts route activation once directly and once while flushing
    # its durable acceptance. Both fail, while the message send remains usable.
    network = RecoveringRouteNetwork(failures=2)
    service.network = network  # type: ignore[assignment]

    try:
        approved = service.approve_request(contact["id"])

        accepts = [
            message
            for message in store.list("message")
            if message["kind"] == MessageKind.CONTACT_ACCEPT.value
        ]
        assert approved["trust"] == TrustState.APPROVED.value
        assert len(accepts) == 1
        assert accepts[0]["state"] == DeliveryState.SENDING.value
        assert network.sent_kinds == [MessageKind.CONTACT_ACCEPT]
        assert network.route_attempts == 2
        assert service._connection_settings_dirty is True

        queued = service._create_outbound(contact, MessageKind.CHAT, "route retry")
        service._attempt(queued["id"])

        assert network.route_attempts == 3
        assert network.applied_settings[-1]["tcp_clients"] == reverse_hints
        assert service._connection_settings_dirty is False
        assert network.sent_kinds == [MessageKind.CONTACT_ACCEPT, MessageKind.CHAT]
        assert len(
            [
                message
                for message in store.list("message")
                if message["kind"] == MessageKind.CONTACT_ACCEPT.value
            ]
        ) == 1
    finally:
        service.close()


class OneCycleShutdown:
    def __init__(self) -> None:
        self.stopped = threading.Event()
        self.outer_waits = 0

    def set(self) -> None:
        self.stopped.set()

    def wait(self, timeout: float) -> bool:
        if self.stopped.is_set():
            return True
        if timeout >= 1:
            self.outer_waits += 1
            return self.outer_waits > 1
        return self.stopped.wait(timeout)


def test_retry_backlog_releases_dispatch_lock_between_messages(tmp_path: Path) -> None:
    """A historical outbox cannot keep a live renderer command locked out."""

    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    service._retry_thread.join(timeout=2)
    for message_id in ("old-one", "old-two"):
        store.put(
            "message",
            message_id,
            {
                "id": message_id,
                "direction": "outbound",
                "state": DeliveryState.QUEUED.value,
            },
        )

    first_attempt = threading.Event()
    release_first = threading.Event()
    second_attempt = threading.Event()
    command_entered = threading.Event()
    release_command = threading.Event()

    def attempt(message_id: str) -> None:
        if message_id == "old-one":
            first_attempt.set()
            assert release_first.wait(2)
        elif message_id == "old-two":
            second_attempt.set()

    service._attempt = attempt  # type: ignore[method-assign]
    service.network = object()  # type: ignore[assignment]
    cycle_shutdown = OneCycleShutdown()
    service._shutdown = cycle_shutdown  # type: ignore[assignment]
    retry = threading.Thread(target=service._retry_loop)

    def renderer_command() -> None:
        with service._dispatch_lock:
            command_entered.set()
            assert release_command.wait(2)

    command = threading.Thread(target=renderer_command)
    try:
        retry.start()
        assert first_attempt.wait(1)
        command.start()
        release_first.set()

        assert command_entered.wait(1)
        assert not second_attempt.is_set()
        release_command.set()
        assert second_attempt.wait(1)
    finally:
        release_first.set()
        release_command.set()
        cycle_shutdown.set()
        command.join(timeout=2)
        retry.join(timeout=2)
        service.network = None
        service.close()


def test_contact_flush_bounds_immediate_retry_work(tmp_path: Path) -> None:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    service._retry_thread.join(timeout=2)
    attempted: list[str] = []
    for index in range(10):
        message_id = f"queued-{index}"
        store.put(
            "message",
            message_id,
            {
                "id": message_id,
                "contact_id": "phone",
                "direction": "outbound",
                "state": DeliveryState.QUEUED.value,
            },
        )
    service._attempt = attempted.append  # type: ignore[method-assign]

    try:
        service._flush_contact("phone")
        assert attempted == [f"queued-{index}" for index in range(4)]
    finally:
        service.close()


def test_group_retry_backlog_releases_dispatch_lock_between_deliveries(
    tmp_path: Path,
) -> None:
    store = VaultStore(tmp_path, os.urandom(32), allow_unprotected_for_tests=True)
    service = MeshChatService(store, tmp_path, lambda _event: None)
    service._shutdown.set()
    service._retry_thread.join(timeout=2)
    for delivery_id in ("group-old-one", "group-old-two"):
        store.put("group_delivery", delivery_id, {"id": delivery_id})

    first_attempt = threading.Event()
    release_first = threading.Event()
    second_attempt = threading.Event()
    command_entered = threading.Event()
    release_command = threading.Event()

    def attempt(delivery_id: str) -> None:
        if delivery_id == "group-old-one":
            first_attempt.set()
            assert release_first.wait(2)
        elif delivery_id == "group-old-two":
            second_attempt.set()

    service._expire_group_invitation_state = lambda _now: None  # type: ignore[method-assign]
    service._retry_group_delivery_if_due = attempt  # type: ignore[method-assign]
    service.network = object()  # type: ignore[assignment]
    cycle_shutdown = OneCycleShutdown()
    service._shutdown = cycle_shutdown  # type: ignore[assignment]
    retry = threading.Thread(target=service._retry_loop)

    def renderer_command() -> None:
        with service._dispatch_lock:
            command_entered.set()
            assert release_command.wait(2)

    command = threading.Thread(target=renderer_command)
    try:
        retry.start()
        assert first_attempt.wait(1)
        command.start()
        release_first.set()

        assert command_entered.wait(1)
        assert not second_attempt.is_set()
        release_command.set()
        assert second_attempt.wait(1)
    finally:
        release_first.set()
        release_command.set()
        cycle_shutdown.set()
        command.join(timeout=2)
        retry.join(timeout=2)
        service.network = None
        service.close()
