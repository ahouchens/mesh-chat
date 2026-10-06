from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import RNS

from mesh_chat.models import Contact, TrustState
from mesh_chat.network import ReticulumNetwork
from mesh_chat.service import MeshChatService
from mesh_chat.vault import VaultStore


class StubNetwork:
    def __init__(
        self,
        *,
        interface_available: bool,
        recipient_ready: bool = False,
        path_known: bool = False,
    ) -> None:
        self.interface_available = interface_available
        self._recipient_ready = recipient_ready
        self._path_known = path_known
        self.path_requests: list[bytes] = []

    def snapshot(self) -> dict[str, object]:
        return {
            "interface_available": self.interface_available,
            "interfaces": [],
        }

    def recipient_ready(self, _destination: bytes) -> bool:
        return self._recipient_ready

    def request_path(self, destination: bytes) -> None:
        self.path_requests.append(destination)

    def path_known(self, _destination: bytes) -> bool:
        return self._path_known

    def shutdown(self) -> None:
        pass


def _service(tmp_path: Path) -> MeshChatService:
    store = VaultStore(
        tmp_path, os.urandom(32), allow_unprotected_for_tests=True
    )
    return MeshChatService(store, tmp_path, lambda _event: None)


def _add_contact(service: MeshChatService) -> bytes:
    destination = bytes.fromhex("42" * 16)
    contact = Contact(
        id="alex",
        display_name="Alex",
        public_identity="public",
        identity_hash="identity",
        destination_hash=destination.hex(),
        fingerprint="fingerprint",
        trust=TrustState.AWAITING_CONSENT,
    ).to_dict()
    service.store.put("contact", contact["id"], contact)
    return destination


@pytest.mark.parametrize(
    ("interfaces", "expected"),
    [
        ([], False),
        ([SimpleNamespace(online=False, receives=True)], False),
        ([SimpleNamespace(online=True, receives=False)], False),
        ([SimpleNamespace(online=True, receives=True)], True),
    ],
)
def test_interface_availability_requires_online_receiving_interface(
    monkeypatch: pytest.MonkeyPatch,
    interfaces: list[SimpleNamespace],
    expected: bool,
) -> None:
    monkeypatch.setattr(RNS.Transport, "interfaces", interfaces)
    network = ReticulumNetwork.__new__(ReticulumNetwork)

    assert network.interface_available is expected


def test_snapshot_tracks_interface_loss_and_recovery_live(tmp_path: Path) -> None:
    service = _service(tmp_path)
    network = StubNetwork(interface_available=False)
    service.network = network  # type: ignore[assignment]
    try:
        snapshot = service.snapshot()
        assert snapshot["service_error"] == "network_interface_unavailable"
        assert snapshot["network"] == {
            "interface_available": False,
            "interfaces": [],
        }

        network.interface_available = True
        recovered = service.snapshot()
        assert recovered["service_error"] is None
        assert recovered["network"] == {
            "interface_available": True,
            "interfaces": [],
        }
    finally:
        service.close()


def test_connection_help_stops_when_no_interface_is_available(tmp_path: Path) -> None:
    service = _service(tmp_path)
    destination = _add_contact(service)
    network = StubNetwork(interface_available=False)
    service.network = network  # type: ignore[assignment]
    try:
        assert service.connection_help("alex") == {
            "code": "service_unavailable",
            "action": "restart_app",
        }
        assert network.path_requests == []
        assert destination not in network.path_requests
    finally:
        service.close()


def test_connection_help_requests_path_when_recipient_keys_are_missing(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    destination = _add_contact(service)
    network = StubNetwork(interface_available=True, recipient_ready=False)
    service.network = network  # type: ignore[assignment]
    try:
        assert service.connection_help("alex") == {
            "code": "waiting_for_keys",
            "action": "ask_contact_to_open_app",
        }
        assert network.path_requests == [destination]
    finally:
        service.close()


@pytest.mark.parametrize(
    ("path_known", "expected"),
    [
        (False, {"code": "no_route", "action": "check_network_or_fresh_invite"}),
        (True, {"code": "connecting", "action": None}),
    ],
)
def test_connection_help_reports_route_state_after_keys_are_ready(
    tmp_path: Path,
    path_known: bool,
    expected: dict[str, str | None],
) -> None:
    service = _service(tmp_path)
    _add_contact(service)
    network = StubNetwork(
        interface_available=True,
        recipient_ready=True,
        path_known=path_known,
    )
    service.network = network  # type: ignore[assignment]
    try:
        assert service.connection_help("alex") == expected
        assert network.path_requests == []
    finally:
        service.close()
