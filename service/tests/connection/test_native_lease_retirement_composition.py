"""Real manual adoption/Core dispatch/Windows leases; loopback component only.

Contact approval rows and Reticulum registration/path are explicit models;
native_pairing disables real Reticulum networking. These controls do not execute
Controller.path_case/exchange, establish message receipts, or qualify Android or
packaged transports. The future per-case retirement port is not faked here.
"""
import asyncio
import base64
from contextlib import contextmanager
from copy import deepcopy
import json
import os
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
from mesh_chat.core_api.qualification_host import (
    QualificationControl, mark_initialized_profile, reserve_fresh_profile,
)
from mesh_chat.core_api.session import Grant
from mesh_chat.errors import ContactNotApproved
from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
from test_pairing_runtime import native_pairing
from test_reconnect_service import _add_contact


@contextmanager
def owned_cleanup():
    """Attempt every exact owner; preserve primary failure and secondary facts."""
    callbacks = []
    def register(priority, label, close):
        callbacks.append((priority, label, close))
    def finish():
        failures = []
        for _, label, close in sorted(callbacks, key=lambda item: item[0]):
            try:
                close()
            except BaseException as error:
                error.add_note("fixture cleanup: " + label)
                failures.append(error)
        return failures
    try:
        yield register
    except BaseException as primary:
        failures = finish()
        if failures:
            primary.fixture_cleanup_failures = tuple(failures)
            for error in failures:
                primary.add_note("secondary fixture cleanup failure: " + type(error).__name__
                                 + "; " + error.__notes__[-1])
        raise
    else:
        failures = finish()
        if failures:
            raise BaseExceptionGroup("fixture cleanup failed", failures)


def qualified_service(create, directory, register, role):
    key = os.urandom(32)
    initial = {"v": 1, "command": "initialize", "payload": {
        "profile_dir": str(directory), "vault_key": base64.b64encode(key).decode(),
        "display_name": "Mesh qualification", "parent_pid": os.getpid()}}
    reserve_fresh_profile(initial)
    service, *_ = create(directory, key)
    register(0, role + " service.close", service.close)
    mark_initialized_profile(initial)
    return service


class ServicePeer:
    """Forward the controller's existing private binding, without DTO substitutes."""
    def __init__(self, service, *, private_native=True):
        self.service = service
        self.authorized = Event()
        self.authorized.set()
        self.port = QualificationControl(lambda: service, authorize=self.authorized.is_set,
                                         caller="lease-composition")
        self.session = bind_service_session(service, lambda: Grant(
            "lease-composition", frozenset({"observe", "approve", "read"}), ("local",)),
            private_native=private_native)
        self.replies = []
        self.contexts = {}
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

    def pairing_begin(self, operation, role, *, pairing_code=None, direct=True):
        payload = {"operation_id": operation, "role": role, "allow_direct_ip_disclosure": direct}
        if pairing_code is not None:
            payload["pairing_code"] = pairing_code
        before = set(getattr(self.service, "_native_pairing_contexts", {}))
        result = self.port.dispatch("qualification.pairing_begin", payload)
        if operation not in self.contexts:
            created = set(self.service._native_pairing_contexts) - before
            assert len(created) == 1
            # Observe the actual newly derived context; never derive authority,
            # write its state or insert an adopted/retired owner in the fixture.
            self.contexts[operation] = self.service._native_pairing_contexts[created.pop()]
        return result

    def pairing_status(self, operation):
        return self.port.dispatch("qualification.pairing_status", {"operation_id": operation})

    def pairing_cancel(self, operation):
        return self.port.dispatch("qualification.pairing_cancel", {"operation_id": operation})


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
def manual_carriers(native_pairing, monkeypatch, initiator, tmp_path):
    # No STUN/TURN, mailbox HTTP or off-host packets. Only host-address discovery
    # is constrained; real aiortc/Windows host creation and disposal execute.
    import aioice.ice
    monkeypatch.setattr(aioice.ice, "get_host_addresses", lambda *_a, **_k: ["127.0.0.1"])
    create, _ = native_pairing
    services, hosts, peers = {}, {}, {}
    with owned_cleanup() as register:
        for role in ("windows", "android"):
            service = qualified_service(create, tmp_path / ("mesh-qualification-" + role), register, role)
            service.update_call_settings({**service._call_settings.to_dict(), "stun_urls": [],
                "turn_url": None, "turn_username": None, "turn_credential": None,
                "turn_broker_url": None, "turn_broker_consent": False, "relay_only": False})
            host = WindowsNativeWebRTCHost(service.native_webrtc_event)
            register(1, role + " host.shutdown", host.shutdown)
            service._native_host = host
            services[role], hosts[role] = service, host
            peers[role] = ServicePeer(service)
        other = "android" if initiator == "windows" else "windows"
        intents = {role: str(uuid4()) for role in services}
        offer, answer = peers[initiator], peers[other]
        offer.pairing_begin(intents[initiator], "offer")
        drive(services, lambda: bool(offer.pairing_status(intents[initiator])["pairing_code"]))
        code = offer.pairing_status(intents[initiator])["pairing_code"]
        answer.pairing_begin(intents[other], "answer", pairing_code=code)
        drive(services, lambda: answer.pairing_status(intents[other])["state"] == "awaiting_approval")
        drive(services, lambda: offer.pairing_status(intents[initiator])["state"] == "awaiting_approval")
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
            context = peers[role].contexts[intents[role]]
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
            return all(peers[role].pairing_status(intents[role])["state"] == "transferred"
                and service._native_carrier_authorized(peers[role].contexts[intents[role]]["session"])
                for role, service in services.items())
        drive(services, adopted)
        controllers = {role: Controller(role, peers[role], None, None, {}) for role in services}
        sessions = {role: peer.contexts[intents[role]]["session"] for role, peer in peers.items()}
        physical = {role: services[role]._native_resources.require(session) for role, session in sessions.items()}
        yield SimpleNamespace(services=services, hosts=hosts, contacts=contacts, peers=peers, intents=intents,
            controllers=controllers, sessions=sessions, physical=physical, drive=lambda check: drive(services, check))


@pytest.mark.parametrize("primary_failure", [False, True])
def test_fixture_cleanup_attempts_all_real_hosts_and_preserves_failures(request, primary_failure):
    hosts, attempts = [], []
    primary = ValueError("controlled setup failure")
    secondary = OSError("controlled cleanup failure")
    def fail_cleanup():
        attempts.append("failing callback")
        raise secondary
    def exercise():
        with owned_cleanup() as register:
            register(0, "controlled failure", fail_cleanup)
            for role in ("first", "second"):
                host = WindowsNativeWebRTCHost(lambda *_: None)
                request.addfinalizer(host.shutdown)  # Independent backstop if this control fails.
                hosts.append(host)
                def close(exact=host, label=role):
                    attempts.append(label)
                    exact.shutdown()
                register(1, role + " host.shutdown", close)
            if primary_failure:
                raise primary
    with pytest.raises(ValueError if primary_failure else ExceptionGroup) as caught:
        exercise()
    assert attempts == ["failing callback", "first", "second"]
    assert all(not host._thread.is_alive() and host._loop.is_closed() for host in hosts)
    if primary_failure:
        assert caught.value is primary
        assert primary.fixture_cleanup_failures == (secondary,)
        assert any("OSError" in note for note in primary.__notes__)
    else:
        assert caught.value.exceptions == (secondary,)


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_actual_managed_close_guard_cannot_satisfy_controller_zero_leases(manual_carriers):
    state = manual_carriers
    for role, observer in state.controllers.items():
        service = state.services[role]
        identity = service._identity.get_public_key()
        contact = deepcopy(service.store.get("contact", state.contacts[role]))
        before = state.peers[role].inventory()
        assert before["host_accounting"]["active_count"] == 1
        peer = state.peers[role]
        assert peer.pairing_cancel(state.intents[role]) == {
            "operation_id": state.intents[role], "state": "transferred"}
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
        peer.authorized.clear()
        try:
            with pytest.raises(ContactNotApproved):
                peer.pairing_status(state.intents[role])
        finally:
            peer.authorized.set()


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
