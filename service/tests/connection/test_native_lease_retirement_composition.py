"""Real manual adoption/Core dispatch/Windows leases; loopback component only.

Contact approval rows and Reticulum registration/path are explicit models;
native_pairing disables real Reticulum networking. These controls do not execute
Controller.path_case/exchange, establish message receipts, or qualify Android or
packaged transports. The future per-case retirement port is not faked here.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from native_interop_controller import Controller
from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.core_api.session import Grant
from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
from test_pairing_runtime import native_pairing
from test_reconnect_service import _add_contact


class ServicePeer:
    """Forward the controller's existing private binding, without DTO substitutes."""
    def __init__(self, service, *, private_native=True):
        self.service = service
        self.port = QualificationControl(lambda: service)
        self.session = bind_service_session(service, lambda: Grant(
            "lease-composition", frozenset({"observe", "approve", "read"}), ("local",)),
            private_native=private_native)
        self.replies = []
        assert self.request("runtime.capabilities")["ok"]

    def request(self, operation, params=None, key=None):
        frame = {"api_version": 1, "request_id": uuid4().hex,
                 "operation": operation, "params": params or {}}
        if key is not None:
            frame["idempotency_key"] = key
        return self.session.request(frame)

    def core(self, operation, params, key=None):
        reply = self.request(operation, params, key)
        self.replies.append((operation, deepcopy(params), deepcopy(reply)))
        assert reply["ok"], reply.get("error", {}).get("code")
        return reply["result"]

    def inventory(self):
        return self.port.dispatch("qualification.inventory", {})

    def path(self, logical, physical, sample_request):
        return self.port.dispatch("qualification.path_evidence", {
            "logical_session": logical, "expected_physical": physical,
            "sample_request": sample_request})


def drive(services, condition, *, timeout=12):
    deadline = monotonic() + timeout
    trace = []
    while not condition() and monotonic() < deadline:
        for service in services.values():
            service._connection_runtime.step()
        current = {role: [(state.reason, state.desired.value,
            state.negotiation.phase.value if state.negotiation else None, state.carrier is not None)
            for state in service._connection_runtime.owner.snapshots()] for role, service in services.items()}
        if not trace or current != trace[-1]:
            trace.append(current)
            trace = trace[-10:]
        Event().wait(0.002)
    if not condition():
        raise AssertionError(json.dumps(trace))


@pytest.fixture
def manual_carriers(native_pairing, monkeypatch, initiator):
    # No STUN/TURN, mailbox HTTP or off-host packets. Only host-address discovery
    # is constrained; real aiortc/Windows host creation and disposal execute.
    import aioice.ice
    monkeypatch.setattr(aioice.ice, "get_host_addresses", lambda *_a, **_k: ["127.0.0.1"])
    create, _ = native_pairing
    services, hosts = {}, {}
    for role in ("windows", "android"):
        service, *_ = create()
        service.update_call_settings({**service._call_settings.to_dict(), "stun_urls": [],
            "turn_url": None, "turn_username": None, "turn_credential": None,
            "turn_broker_url": None, "turn_broker_consent": False, "relay_only": False})
        host = WindowsNativeWebRTCHost(service.native_webrtc_event)
        service._native_host = host
        services[role], hosts[role] = service, host
    try:
        other = "android" if initiator == "windows" else "windows"
        intents = {role: str(uuid4()) for role in services}
        offer, answer = services[initiator], services[other]
        offer.native_pairing_begin(intents[initiator], role="offer", authorized=lambda: True,
                                   allow_direct_ip_disclosure=True)
        drive(services, lambda: bool(offer.native_pairing_status(intents[initiator])["pairing_code"]))
        code = offer.native_pairing_status(intents[initiator])["pairing_code"]
        answer.native_pairing_begin(intents[other], role="answer", pairing_code=code,
                                    authorized=lambda: True, allow_direct_ip_disclosure=True)
        drive(services, lambda: answer.native_pairing_status(intents[other])["state"] == "awaiting_approval")
        drive(services, lambda: offer.native_pairing_status(intents[initiator])["state"] == "awaiting_approval")
        contacts = {}
        for role, service in services.items():
            peer = services["android" if role == "windows" else "windows"]
            contact = "contact-" + role
            _add_contact(service, contact, peer._identity, peer._require_profile()["destination_hash"])
            service.reconnect_consent_set(contact, False, True)
            contacts[role] = contact
        for role, service in services.items():
            other_role = "android" if role == "windows" else "windows"
            peer = services[other_role]
            context = service._native_pairing_contexts[intents[role]]
            capability = peer._reconnect_profile_for_contact(contacts[other_role])["local_capabilities"]
            service._native_control_receive(context["session"], "mesh-onboarding", json.dumps({
                "type": "connection_capabilities", "document": capability}))
        # Model the external network/Reticulum registration boundary only after
        # approval, so no isolated contact-bootstrap worker is allocated. Real
        # service bridge creation, attachment and owner readiness still execute.
        original_interfaces = RNS.Transport.interfaces
        monkeypatch.setattr(RNS.Transport, "interfaces", list(original_interfaces))
        def add_interface(interface, **_):
            RNS.Transport.interfaces.append(interface)
        for service in services.values():
            service.network = SimpleNamespace(
                destination_hash=bytes.fromhex(service._require_profile()["destination_hash"]),
                reticulum=SimpleNamespace(_add_interface=add_interface), reannounce=lambda: None,
                path_known=lambda _: True, recipient_ready=lambda _: True,
                invitation_hints=lambda: [], shutdown=lambda: True)
        def adopted():
            return all(service._native_pairing_contexts[intents[role]]["state"] == "transferred"
                and service._native_carrier_authorized(service._native_pairing_contexts[intents[role]]["session"])
                for role, service in services.items())
        drive(services, adopted)
        peers = {role: ServicePeer(service) for role, service in services.items()}
        controllers = {role: Controller(role, peers[role], None, None, {}) for role in services}
        sessions = {role: service._native_pairing_contexts[intents[role]]["session"]
                    for role, service in services.items()}
        physical = {role: services[role]._native_resources.require(session) for role, session in sessions.items()}
        yield SimpleNamespace(services=services, hosts=hosts, contacts=contacts, peers=peers,
            controllers=controllers, sessions=sessions, physical=physical, drive=lambda check: drive(services, check))
    finally:
        for service in services.values():
            service.close()
        for host in hosts.values():
            host.shutdown()


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_actual_managed_close_guard_cannot_satisfy_controller_zero_leases(manual_carriers):
    state = manual_carriers
    for role, observer in state.controllers.items():
        service = state.services[role]
        identity = service._identity.get_public_key()
        contact = deepcopy(service.store.get("contact", state.contacts[role]))
        before = state.peers[role].inventory()
        assert before["host_accounting"]["active_count"] == 1
        assert observer.native("native_webrtc_close", session_id=state.sessions[role]) == {"state": "managed"}
        assert observer.retired() is None
        assert service._native_carrier_authorized(state.sessions[role])
        assert service._native_resources.current(state.sessions[role], state.physical[role])
        assert state.peers[role].inventory()["host_accounting"] == before["host_accounting"]
        assert service._identity.get_public_key() == identity
        assert service.store.get("contact", state.contacts[role]) == contact
        profile = service._reconnect_profile_for_contact(state.contacts[role])
        assert profile["auto_reconnect"] is False and profile["remote_auto_reconnect"] is False
        public = ServicePeer(service, private_native=False)
        assert public.request("native.command", {"command": "native_webrtc_close",
            "payload": {"session_id": state.sessions[role]}})["ok"] is False


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_owner_stop_waits_exact_disposal_and_start_does_not_invent_auto_consent(manual_carriers, monkeypatch, initiator):
    state = manual_carriers
    role = initiator
    service, host = state.services[role], state.hosts[role]
    observer = state.controllers[role]
    pc = host._sessions[state.physical[role]].pc
    close = pc.close
    entered, release = Event(), Event()
    async def gated_close():
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.002)
        await close()
    monkeypatch.setattr(pc, "close", gated_close)
    try:
        observer.native("reconnect_stop", contact_id=state.contacts[role])
        state.drive(entered.is_set)
        counts = state.peers[role].inventory()["host_accounting"]
        assert counts["reserved_count"] == counts["allocated_count"] == counts["retiring_count"] == 1
        assert observer.retired() is None
        assert not service._native_carrier_authorized(state.sessions[role])
    finally:
        release.set()
    state.drive(lambda: observer.retired() is not None)
    counts = observer.retired()
    assert all(counts[name] == 0 for name in (
        "reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count"))
    observer.native("reconnect_start", contact_id=state.contacts[role])
    profile = service._reconnect_profile_for_contact(state.contacts[role])
    assert profile["state"] == "stopped" and profile["active"] is False
    assert profile["auto_reconnect"] is False and profile["remote_auto_reconnect"] is False
    assert observer.retired() is not None
