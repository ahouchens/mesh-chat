"""Real manual adoption/Core dispatch/Windows leases; loopback component only.

Contact approval rows and Reticulum registration/path are explicit models;
native_pairing disables real Reticulum networking. These controls do not execute
Controller.path_case/exchange, establish message receipts, or qualify Android or
packaged transports. Per-case retirement uses the actual private product port.
"""
import asyncio
import base64
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from native_interop_controller import Controller
from native_interop_peers import retirement_correlation, retirement_payload
from mesh_chat.carrier_journal import CarrierBinding, CarrierJournal
from mesh_chat.core_api.composition import bind_service_session
from mesh_chat.core_api.qualification_host import (
    QualificationControl, mark_initialized_profile, reserve_fresh_profile,
)
from mesh_chat.core_api.session import Grant
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, ValidationError
from mesh_chat.native_windows_webrtc import WindowsNativeWebRTCHost
from mesh_chat.native_carrier_checkpoint import _binding_context
from mesh_chat import reconnect_service
from test_pairing_runtime import native_pairing
from test_reconnect_service import _add_contact
from test_webrtc_interface import reticulum


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

    def inventory(self, *, operation_id=None, request_id=None):
        return self.port.dispatch("qualification.inventory", retirement_correlation(operation_id, request_id))

    def retire_carrier(self, operation_id, request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch, *, action):
        return self.port.dispatch("qualification.retire_carrier", retirement_payload(
            operation_id, request_id, logical_session, expected_physical,
            expected_service_incarnation, expected_adapter_epoch, action=action))

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
    result = condition()
    while not result and monotonic() < deadline:
        for service in services.values():
            service._connection_runtime.step()
        current = {role: [(state.reason, state.desired.value,
            state.negotiation.phase.value if state.negotiation else None, state.carrier is not None)
            for state in service._connection_runtime.owner.snapshots()] for role, service in services.items()}
        if not trace or current != trace[-1]:
            trace.append(current)
            trace = trace[-10:]
        Event().wait(0.002)
        result = condition()
    if not result:
        raise AssertionError(json.dumps(trace))
    return result


def begin_manual_case(services, peers, initiator):
    other = "android" if initiator == "windows" else "windows"
    intents = {role: str(uuid4()) for role in services}
    offer, answer = peers[initiator], peers[other]
    offer.pairing_begin(intents[initiator], "offer")
    code = drive(services, lambda: offer.pairing_status(intents[initiator])["pairing_code"])
    answer.pairing_begin(intents[other], "answer", pairing_code=code)
    drive(services, lambda: answer.pairing_status(intents[other])["state"] == "awaiting_approval")
    drive(services, lambda: offer.pairing_status(intents[initiator])["state"] == "awaiting_approval")
    return intents


def prepare_manual_contact(service, contact, peer):
    with peer._dispatch_lock:
        identity = peer._identity
        destination = peer._require_profile()["destination_hash"]
    # Match the surrounding production host-command lock, including the profile
    # read BEFORE consent's later authority-update write. Do not expose a partly
    # prepared approved contact to the actual native control worker.
    with service._dispatch_lock:
        _add_contact(service, contact, identity, destination)
        service.reconnect_consent_set(contact, False, True)


def finish_manual_case(state, intents):
    for role, service in state.services.items():
        other = "android" if role == "windows" else "windows"
        with state.services[other]._dispatch_lock:
            capability = state.services[other]._reconnect_profile_for_contact(state.contacts[other])["local_capabilities"]
        # Like _handle_native_webrtc_event, serialize the full receive. Never
        # retain the opposite peer lock while entering this service.
        with service._dispatch_lock:
            context = state.peers[role].contexts[intents[role]]
            service._native_control_receive(context["session"], "mesh-onboarding", json.dumps({
                "type": "connection_capabilities", "document": capability}))
    def adopted():
        return all(state.peers[role].pairing_status(intents[role])["state"] == "transferred"
            and service._native_carrier_authorized(state.peers[role].contexts[intents[role]]["session"])
            for role, service in state.services.items())
    state.drive(adopted)
    state.intents = intents
    state.sessions = {role: peer.contexts[intents[role]]["session"] for role, peer in state.peers.items()}
    state.physical = {role: state.services[role]._native_resources.require(session)
                      for role, session in state.sessions.items()}


def manual_identity(state):
    result = {}
    for role, service in state.services.items():
        contact = service.store.get("contact", state.contacts[role])
        profile = service._reconnect_profile_for_contact(state.contacts[role])
        result[role] = (service._identity.get_public_key(), contact["id"], contact["destination_hash"],
            contact["trust"], *(profile[name] for name in (
                "id", "local_device_id", "remote_device_id", "auto_reconnect", "remote_auto_reconnect",
                "active", "state")))
    return result


def retirement_requests(state):
    requests = {}
    for role, observer in state.controllers.items():
        # Genuine post-adoption inspection populates production adapter sequence
        # provenance. Neither the service evidence nor owner state is replaced.
        sample = state.drive(lambda: observer.observe(state.sessions[role], ready=True, scenario="direct"))
        requests[role] = {"operation_id": state.intents[role], "request_id": uuid4().hex,
            "logical_session": sample["logical_session"], "expected_physical": sample["resource"],
            "expected_service_incarnation": sample["service_incarnation"],
            "expected_adapter_epoch": sample["adapter_epoch"]}
        state.retirement_scopes[requests[role]["request_id"]] = (
            sample["service_incarnation"], sample["profile_incarnation"])
    return requests


def prepare_retirement(state, requests):
    # Both real owners must retain proof custody before either peer can close.
    for role, payload in requests.items():
        assert state.peers[role].retire_carrier(**payload, action="prepare") == {
            "request_id": payload["request_id"], "state": "prepared"}


def request_retirement(state, requests):
    prepare_retirement(state, requests)
    for role, payload in requests.items():
        assert state.peers[role].retire_carrier(**payload, action="commit") == {
            "request_id": payload["request_id"], "state": "pending"}


def retirement_observation(state, role, payload):
    return state.peers[role].inventory(operation_id=payload["operation_id"],
                                     request_id=payload["request_id"])["carrier_retirement"]


def correlated_retired(state, role, payload):
    service, profile = state.retirement_scopes[payload["request_id"]]
    return state.controllers[role].retired(operation_id=payload["operation_id"],
        request_id=payload["request_id"], expected_service=service, expected_profile=profile)


def retirement_loop_state(host):
    """Bounded loop responsiveness probe; never enumerate or dump tasks."""
    if host._loop.is_closed() or not host._thread.is_alive():
        return "loop_stopped"
    done = Event()
    try:
        host._loop.call_soon_threadsafe(done.set)
    except RuntimeError:
        return "loop_stopped"
    return "loop_responsive" if done.wait(0.05) else "loop_probe_pending"


def retirement_failure_snapshot(state, requests):
    """Bounded, identifier-free evidence sampled only after the existing timeout."""
    evidence = {}
    for role in ("windows", "android"):
        payload = requests[role]
        record = state.peers[role].contexts[payload["operation_id"]]["carrier_retirement"]
        ticket = record.ticket
        runtime_lock = record.runtime._lock
        if runtime_lock.acquire(False):
            try:
                ticket_state = {name: bool(getattr(ticket, name)) for name in (
                    "committed", "close_started", "native_acknowledged",
                    "cleanup_acknowledged", "acknowledged", "invalidated")}
            finally:
                runtime_lock.release()
        else:
            ticket_state = "runtime_lock_busy"
        service = state.services[role]
        registry = service._native_resources
        if registry._lock.acquire(False):
            try:
                local_state = {
                    "logical_maps_to_requested_physical": registry._logical.get(
                        payload["logical_session"]) == payload["expected_physical"],
                    "physical_maps_to_requested_logical": registry._physical.get(
                        payload["expected_physical"]) == payload["logical_session"]}
            finally:
                registry._lock.release()
        else:
            local_state = "registry_lock_busy"
        if service._native_webrtc_lock.acquire(False):
            try:
                local_state = {**local_state,
                    "logical_live": payload["logical_session"] in service._native_webrtc_live,
                    "logical_creating": payload["logical_session"] in service._native_webrtc_creating,
                    "profile_session_present": payload["logical_session"] in
                        service._native_webrtc_profile_sessions.values()} if isinstance(local_state, dict) else local_state
            finally:
                service._native_webrtc_lock.release()
        elif isinstance(local_state, dict):
            local_state["service_native_lock_busy"] = True
        host = state.hosts[role]
        if host._lock.acquire(False):
            try:
                lease = host._leases.get(payload["expected_physical"])
                pending = host._retire_futures.get(payload["expected_physical"])
                future = pending[1] if pending is not None and pending[0] is lease else None
                host_state = {"lease_count": min(len(host._leases), 16),
                              "lease_count_capped": len(host._leases) > 16,
                              "requested_lease_present": lease is not None}
                if lease is not None:
                    host_state.update(creating=bool(lease.creating), cancelled=bool(lease.cancelled),
                                      created=lease.created.is_set(), session_present=lease.session is not None,
                                      creation_task_present=lease.task is not None,
                                      creation_task_done=lease.task.done() if lease.task is not None else None,
                                      retire_future_present=future is not None,
                                      retire_future_done=future.done() if future is not None else None,
                                      retire_future_cancelled=future.cancelled() if future is not None else None)
                    if future is not None and future.done() and not future.cancelled():
                        try:
                            failure = future.exception(timeout=0)
                            host_state["retire_future_outcome"] = (
                                "failed" if failure is not None else "completed")
                        except Exception:
                            host_state["retire_future_outcome"] = "unavailable"
            finally:
                host._lock.release()
            if lease is not None and future is not None and not future.done():
                host_state["retirement_loop_state"] = retirement_loop_state(host)
        else:
            host_state = "host_lock_busy"
        evidence[role] = {"request_matches": record.request == (
            payload["request_id"], payload["logical_session"], payload["expected_physical"],
            payload["expected_service_incarnation"], payload["expected_adapter_epoch"]),
            "ticket": ticket_state, "local": local_state, "host": host_state}
    return evidence


def await_retirement(state, requests):
    def acknowledged_and_empty():
        return all(correlated_retired(state, role, payload) is not None for role, payload in requests.items())
    try:
        state.drive(acknowledged_and_empty)
    except AssertionError as error:
        try:
            snapshot = json.dumps(retirement_failure_snapshot(state, requests), sort_keys=True)
            error.add_note("retirement failure snapshot: " + (
                snapshot if len(snapshot) <= 4096 else '{"observation":"size_capped"}'))
        except Exception:
            pass  # The observer must never replace the original failure.
        raise


def test_retirement_timeout_note_is_bounded_and_does_not_replace_failure(monkeypatch):
    original = AssertionError("controlled retirement deadline")
    ticket = SimpleNamespace(**dict.fromkeys(("committed", "close_started", "native_acknowledged",
        "cleanup_acknowledged", "acknowledged", "invalidated"), False))
    ticket.committed = ticket.close_started = True
    record = SimpleNamespace(ticket=ticket, runtime=SimpleNamespace(_lock=RLock()),
        request=("secret-request", "secret-logical", "secret-physical", "secret-service", "secret-epoch"))
    lease = SimpleNamespace(creating=False, cancelled=True, created=Event(), session=object(),
        task=None)
    lease.created.set()
    sensitive_exception = type("secret_exception_" + "x" * 512, (Exception,), {})()
    def role_state(role):
        future = (SimpleNamespace(done=lambda: False, cancelled=lambda: False) if role == "windows"
                  else SimpleNamespace(done=lambda: True, cancelled=lambda: False,
                                       exception=lambda timeout: sensitive_exception))
        host = SimpleNamespace(_lock=RLock(), _leases={"secret-physical": lease},
            _retire_futures={"secret-physical": (lease, future)})
        peer = SimpleNamespace(contexts={"secret-operation": {"carrier_retirement": record}})
        payload = {"operation_id": "secret-operation", "request_id": "secret-request",
            "logical_session": "secret-logical", "expected_physical": "secret-physical",
            "expected_service_incarnation": "secret-service", "expected_adapter_epoch": "secret-epoch"}
        return host, peer, payload
    states = {role: role_state(role) for role in ("windows", "android")}
    service = SimpleNamespace(_native_resources=SimpleNamespace(_lock=RLock(),
        _logical={"secret-logical": "secret-physical"},
        _physical={"secret-physical": "secret-logical"}),
        _native_webrtc_lock=RLock(), _native_webrtc_live={"secret-logical"},
        _native_webrtc_creating=set(), _native_webrtc_profile_sessions={"profile": "secret-logical"})
    state = SimpleNamespace(hosts={role: item[0] for role, item in states.items()},
        peers={role: item[1] for role, item in states.items()},
        services={role: service for role in states},
        drive=lambda _: (_ for _ in ()).throw(original))
    monkeypatch.setattr(sys.modules[__name__], "retirement_loop_state", lambda *_: "loop_responsive")
    with pytest.raises(AssertionError) as caught:
        await_retirement(state, {role: item[2] for role, item in states.items()})
    assert caught.value is original
    note = original.__notes__[0]
    assert all(secret not in note for secret in ("secret-request", "secret-logical", "secret-physical",
        "secret-service", "secret-epoch", "secret-operation", "secret_exception_"))
    assert len(note) < 2500
    snapshot = json.loads(note.removeprefix("retirement failure snapshot: "))
    assert all(snapshot[role]["ticket"]["close_started"] and
               snapshot[role]["local"]["logical_maps_to_requested_physical"]
               for role in ("windows", "android"))
    assert snapshot["windows"]["host"]["retirement_loop_state"] == "loop_responsive"
    assert snapshot["android"]["host"]["retire_future_outcome"] == "failed"


def test_retirement_loop_probe_omits_actual_task_names_and_bounds_unavailable_loop():
    secret = "secret_coroutine_" + "x" * 512
    scope = {"asyncio": asyncio, "started": Event(), "release": Event()}
    exec("async def " + secret + "():\n"
         "    started.set()\n"
         "    while not release.is_set():\n"
         "        await asyncio.sleep(0.002)\n"
         "async def _retire_lease(lease):\n"
         "    await " + secret + "()\n", scope)
    loop = asyncio.new_event_loop()
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    thread = Thread(target=run_loop, daemon=True)
    thread.start()
    lease = object()
    future = asyncio.run_coroutine_threadsafe(scope["_retire_lease"](lease), loop)
    try:
        assert scope["started"].wait(1)
        host = SimpleNamespace(_loop=loop, _thread=thread)
        observation = retirement_loop_state(host)
        assert observation == "loop_responsive" and secret not in observation
    finally:
        scope["release"].set()
        future.result(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()
    stopped = SimpleNamespace(_loop=SimpleNamespace(is_closed=lambda: True),
                              _thread=SimpleNamespace(is_alive=lambda: False))
    assert retirement_loop_state(stopped) == "loop_stopped"
    busy = SimpleNamespace(_loop=SimpleNamespace(is_closed=lambda: False,
        call_soon_threadsafe=lambda _: None), _thread=SimpleNamespace(is_alive=lambda: True))
    assert retirement_loop_state(busy) == "loop_probe_pending"
    unavailable = SimpleNamespace(_loop=SimpleNamespace(is_closed=lambda: False,
        call_soon_threadsafe=lambda _: (_ for _ in ()).throw(RuntimeError("secret-loop-error"))),
        _thread=SimpleNamespace(is_alive=lambda: True))
    assert retirement_loop_state(unavailable) == "loop_stopped"


def test_retirement_failure_note_has_hard_size_cap(monkeypatch):
    original = AssertionError("controlled retirement deadline")
    state = SimpleNamespace(drive=lambda _: (_ for _ in ()).throw(original))
    monkeypatch.setattr(sys.modules[__name__], "retirement_failure_snapshot",
                        lambda *_: {"untrusted": "secret-" + "x" * 8192})
    with pytest.raises(AssertionError) as caught:
        await_retirement(state, {})
    assert caught.value is original
    assert original.__notes__ == ['retirement failure snapshot: {"observation":"size_capped"}']


def test_retirement_failure_observer_never_masks_original_error():
    original = AssertionError("controlled retirement deadline")
    state = SimpleNamespace(drive=lambda _: (_ for _ in ()).throw(original), peers={})
    with pytest.raises(AssertionError) as caught:
        await_retirement(state, {"windows": {"operation_id": "missing"}})
    assert caught.value is original


@contextmanager
def delayed_native_close(state, role, monkeypatch):
    pc = state.hosts[role]._sessions[state.physical[role]].pc
    close = pc.close
    entered, release = Event(), Event()
    async def gated_close():
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.002)
        await close()
    monkeypatch.setattr(pc, "close", gated_close)
    try:
        yield entered
    finally:
        release.set()


@pytest.fixture
def manual_carriers(native_pairing, monkeypatch, initiator, tmp_path, reticulum):
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
        intents = begin_manual_case(services, peers, initiator)
        contacts = {}
        for role, service in services.items():
            peer = services["android" if role == "windows" else "windows"]
            contact = "contact-" + role
            prepare_manual_contact(service, contact, peer)
            contacts[role] = contact
        # Model the external network/Reticulum registration boundary only after
        # approval, so no isolated contact-bootstrap worker is allocated. Real
        # service bridge creation, attachment and owner readiness still execute.
        for service in services.values():
            service.network = SimpleNamespace(
                destination_hash=bytes.fromhex(service._require_profile()["destination_hash"]),
                reticulum=reticulum, reannounce=lambda: None,
                path_known=lambda _: True, recipient_ready=lambda _: True,
                invitation_hints=lambda: [], shutdown=lambda: True)
        controllers = {role: Controller(role, peers[role], None, None, {}) for role in services}
        state = SimpleNamespace(services=services, hosts=hosts, contacts=contacts, peers=peers,
            controllers=controllers, retirement_scopes={}, drive=lambda check: drive(services, check))
        finish_manual_case(state, intents)
        yield state


@pytest.mark.parametrize("overlap", ["refresh", "incoming"])
def test_contact_preparation_cannot_export_stale_snapshot_capability(native_pairing, monkeypatch, overlap):
    """Force a native-refresh overlap; import actual signed docs at the peer."""
    create, _ = native_pairing
    source, *_ = create()
    receiver, *_ = create()
    clock = reconnect_service._now()
    monkeypatch.setattr(reconnect_service, "_now", lambda: clock)
    prepare_manual_contact(receiver, "source", source)
    with receiver._dispatch_lock:
        incoming = receiver.reconnect_capabilities_get("source")["local_capabilities"]
        expected_device = receiver._reconnect_device_id()
        incoming_peer = receiver._require_profile()["destination_hash"]
    profile_for_contact = source._reconnect_profile_for_contact
    read, release, attempted, observed = Event(), Event(), Event(), Event()
    facts, errors = {}, []
    def capture_profile(*args, **kwargs):
        profile = profile_for_contact(*args, **kwargs)
        if current_thread() is preparer and not read.is_set():
            facts["dispatch_owned"] = source._dispatch_lock._is_owned()
            read.set()
            assert release.wait(5), "controlled profile-read gate was not released"
        return profile
    monkeypatch.setattr(source, "_reconnect_profile_for_contact", capture_profile)
    def prepare():
        try:
            prepare_manual_contact(source, "receiver", receiver)
        except BaseException as error:
            errors.append(error)
    def refresh():
        attempted.set()
        try:
            # Production native control refresh runs under this dispatch lock.
            with source._dispatch_lock:
                if overlap == "incoming":
                    source.reconnect_capabilities_store(incoming, expected_contact_id="receiver",
                        expected_peer_destination=incoming_peer)
                else:
                    facts["document"] = source.reconnect_capabilities_get("receiver")["local_capabilities"]
        except BaseException as error:
            errors.append(error)
        finally:
            observed.set()
    preparer, observer = Thread(target=prepare), Thread(target=refresh)
    preparer.start()
    try:
        assert read.wait(2)
        observer.start()
        assert attempted.wait(2)
        if not facts["dispatch_owned"]:
            assert observed.wait(2)  # Force unsafe publication before stale write.
        else:
            assert not observed.is_set()  # Atomic preparation blocks the refresh.
    finally:
        release.set()
        preparer.join(2)
        if observer.ident is not None:
            observer.join(2)
    assert not preparer.is_alive() and not observer.is_alive()
    assert not errors, [type(error).__name__ for error in errors]
    with source._dispatch_lock:
        if overlap == "incoming":
            profile = source._reconnect_profile_for_contact("receiver")
            device_matches = profile.get("remote_device_id") == expected_device
            document_matches = profile.get("remote_capabilities") == incoming
            assert (device_matches, document_matches) == (True, True)
            assert (profile["auto_reconnect"], profile["allow_direct_ip_disclosure"]) == (False, True)
            return
        final_document = source.reconnect_capabilities_get("receiver")["local_capabilities"]
        outgoing_peer = source._require_profile()["destination_hash"]
    with receiver._dispatch_lock:
        for document in (facts["document"], final_document):
            receiver.reconnect_capabilities_store(document, expected_contact_id="source",
                expected_peer_destination=outgoing_peer)
        profile = receiver._reconnect_profile_for_contact("source")
        assert (profile["remote_auto_reconnect"], profile["remote_allow_direct_ip_disclosure"]) == (False, True)


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


def import_cold_capabilities_after_manual_zero(state):
    """Signed storage continuity only; no cold process/delivery claim."""
    documents = {}
    for role, observer in state.controllers.items():
        assert observer.retired() is not None
        result = observer.native("reconnect_consent_set", contact_id=state.contacts[role],
            auto_reconnect=True, allow_direct_ip_disclosure=True)
        assert result["native_shared"] is False  # No carrier exists to deliver it.
        documents[role] = result["capabilities"]
    for role, observer in state.controllers.items():
        other = "android" if role == "windows" else "windows"
        observer.native("reconnect_capabilities_store", document=documents[other],
            expected_contact_id=state.contacts[role],
            expected_peer_destination=state.services[other]._require_profile()["destination_hash"])
        profile = state.services[role]._reconnect_profile_for_contact(state.contacts[role])
        assert profile["auto_reconnect"] is True and profile["remote_auto_reconnect"] is True
        assert state.services[role]._connection_runtime.permits_recovery(profile)
        assert observer.retired() is not None


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_two_manual_cases_reverse_initiator_and_old_request_cannot_retire_replacement(manual_carriers, initiator):
    state = manual_carriers
    first = retirement_requests(state)
    identity = manual_identity(state)
    request_retirement(state, first)
    await_retirement(state, first)
    receipts = {role: peer.contexts[first[role]["operation_id"]]["carrier_retirement"].ticket
                for role, peer in state.peers.items()}
    assert manual_identity(state) == identity

    other = "android" if initiator == "windows" else "windows"
    finish_manual_case(state, begin_manual_case(state.services, state.peers, other))
    assert manual_identity(state) == identity
    for role, peer in state.peers.items():
        assert state.intents[role] != first[role]["operation_id"]
        assert state.physical[role] != first[role]["expected_physical"]
        before = peer.inventory()["host_accounting"]
        assert before["active_count"] == 1
        runtime = state.services[role]._connection_runtime
        live = runtime.owner.snapshot(receipts[role].key)
        assert live.generation > receipts[role].generation
        assert live.carrier.resource.resource_id == state.physical[role]
        for action in ("prepare", "commit"):
            assert peer.retire_carrier(**first[role], action=action) == {
                "request_id": first[role]["request_id"], "state": "acknowledged"}
        assert runtime.owner.snapshot(receipts[role].key) == live
        with pytest.raises(ValidationError):
            peer.retire_carrier(**{**first[role], "request_id": uuid4().hex}, action="prepare")
        assert correlated_retired(state, role, first[role]) is None
        with pytest.raises(ValidationError):
            peer.retire_carrier(**{**first[role], "expected_physical": state.physical[role]}, action="commit")
        with pytest.raises(NativeUnavailable):
            peer.retire_carrier(**{**first[role], "operation_id": state.intents[role], "request_id": uuid4().hex}, action="prepare")
        assert peer.pairing_cancel(state.intents[role])["state"] == "transferred"
        assert state.controllers[role].native("native_webrtc_close", session_id=state.sessions[role]) == {"state": "managed"}
        assert state.services[role]._native_carrier_authorized(state.sessions[role])
        assert runtime.owner.snapshot(receipts[role].key) == live
        assert peer.inventory()["host_accounting"] == before
    final = retirement_requests(state)
    request_retirement(state, final)
    await_retirement(state, final)
    assert manual_identity(state) == identity
    import_cold_capabilities_after_manual_zero(state)


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_private_ack_and_global_zero_wait_for_exact_native_disposal(manual_carriers, monkeypatch, initiator):
    state = manual_carriers
    requests = retirement_requests(state)
    with delayed_native_close(state, initiator, monkeypatch) as entered:
        request_retirement(state, requests)
        state.drive(entered.is_set)
        payload = requests[initiator]
        assert retirement_observation(state, initiator, payload) == {
            "request_id": payload["request_id"], "state": "pending"}
        assert correlated_retired(state, initiator, payload) is None
        counts = state.peers[initiator].inventory()["host_accounting"]
        assert counts["reserved_count"] == counts["allocated_count"] == counts["retiring_count"] == 1
        with pytest.raises(ContactNotApproved):
            state.peers[initiator].pairing_begin(str(uuid4()), "offer")
    await_retirement(state, requests)


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_real_vault_journal_failure_cannot_be_acknowledged_by_native_zero(manual_carriers, monkeypatch, initiator):
    state = manual_carriers
    requests = retirement_requests(state)
    service = state.services[initiator]
    # This host has no recovery-inventory port, so its normal journal is None.
    # Configure a REAL sealed journal with the actual current binding to exercise
    # storage-failure semantics; this does not claim checkpoint inventory proof.
    context = _binding_context(service, state.sessions[initiator])
    journal = CarrierJournal(service.store)
    binding = CarrierBinding(**{**context, "adapter_epoch": requests[initiator]["expected_adapter_epoch"]})
    journal.save(binding, journal.revision())
    monkeypatch.setattr(service, "_carrier_journal", journal)
    update = service.store.update_record
    failed, writable, attempts = Event(), Event(), []
    def update_record(kind, key, change):
        if (kind, key) == ("native_carrier_recovery", "current"):
            attempts.append(True)
            if not writable.is_set():
                failed.set()
                raise OSError("Controlled protected journal write failure")
        return update(kind, key, change)
    monkeypatch.setattr(service.store, "update_record", update_record)
    try:
        request_retirement(state, requests)
        state.drive(lambda: failed.is_set() and state.controllers[initiator].retired() is not None)
        assert journal.bindings() == (binding,)
        assert retirement_observation(state, initiator, requests[initiator])["state"] == "pending"
        assert correlated_retired(state, initiator, requests[initiator]) is None
    finally:
        writable.set()
    await_retirement(state, requests)  # Real unchanged retry cadence; no clock jump.
    assert len(attempts) >= 2 and journal.bindings() == ()


@pytest.mark.parametrize("initiator", ["windows", "android"])
@pytest.mark.parametrize("denial", ["stop", "quarantine"])
def test_transient_retirement_never_clears_real_owner_denial(manual_carriers, monkeypatch, initiator, denial):
    state = manual_carriers
    requests = retirement_requests(state)
    service = state.services[initiator]
    if denial == "stop":
        # Keep the committed ticket active: Stop must invalidate it, rather
        # than racing an already completed historical receipt.
        with delayed_native_close(state, initiator, monkeypatch) as entered:
            request_retirement(state, requests)
            state.drive(entered.is_set)
            state.controllers[initiator].native("reconnect_stop", contact_id=state.contacts[initiator])
            with pytest.raises((ContactNotApproved, NativeUnavailable)):
                correlated_retired(state, initiator, requests[initiator])
        state.drive(lambda: all(observer.retired() is not None for observer in state.controllers.values()))
        state.controllers[initiator].native("reconnect_start", contact_id=state.contacts[initiator])
        with pytest.raises((ContactNotApproved, NativeUnavailable)):
            state.peers[initiator].retire_carrier(**requests[initiator], action="commit")
    else:
        request_retirement(state, requests)
        service._connection_runtime.quarantine()
        # Quarantine denies private inventory itself: inspect actual host leases
        # for cleanup only, without manufacturing an authorized controller ack.
        state.drive(lambda: all(json.loads(host.resourceAccounting())["result"]["reserved_count"] == 0
                                for host in state.hosts.values()))
        with pytest.raises(NativeUnavailable):
            state.controllers[initiator].retired()
        with pytest.raises((ContactNotApproved, NativeUnavailable)):
            state.peers[initiator].pairing_begin(str(uuid4()), "offer")
    profile = service._reconnect_profile_for_contact(state.contacts[initiator])
    assert profile["auto_reconnect"] is False and profile["remote_auto_reconnect"] is False
    assert not service._connection_runtime.permits_recovery(profile)
    if denial == "stop":
        assert profile["state"] == "stopped" and profile["active"] is False
