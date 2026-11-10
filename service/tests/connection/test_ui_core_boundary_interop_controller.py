"""Controller/evidence component checks; synthetic reports are never CI proof."""

from pathlib import Path
import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_evidence as evidence
from native_interop_rendezvous import APPROVAL_PHASES, OFFER_PHASES, checked_payload
from test_ui_core_boundary_interop_peers import (
    ANDROID_ENVIRONMENT_SITES, ANDROID_START_SITES, assert_android_cleaned, scripted_android,
)
from test_ui_core_boundary_interop_evidence import sample
from test_ui_core_boundary_interop_artifacts import RECEIVE_ORIGINS


def cold_setup_controller(monkeypatch, *, role="windows", consent=None, imported=None, received=None):
    association = {"id": "PRIVATE_RECONNECT_PROFILE", "contact_id": "PRIVATE_CONTACT",
        "destination_hash": "a" * 32, "local_device_id": "PRIVATE_LOCAL_DEVICE", "remote_device_id": "PRIVATE_REMOTE_DEVICE"}
    state = SimpleNamespace(events=[], stop=RuntimeError("first_crash_barrier"), association=association)
    consent = consent if consent is not None else {"profile": {**association, "auto_reconnect": True,
        "peer_auto_reconnect": False}, "capabilities": "PRIVATE_SIGNED_CAPABILITIES"}
    imported = imported if imported is not None else {"profile": {**association, "auto_reconnect": True,
        "peer_auto_reconnect": True}, "pending": False}
    state.consent, state.imported = consent, imported
    state.received = received if received is not None else {"capabilities": "PRIVATE_PEER_CAPABILITIES"}
    state.fail_command, state.failure = None, controller.PeerFailure("unavailable")
    class Peer:
        def core(self, operation, params, key=None):
            state.events.append((operation, copy.deepcopy(params)))
            if operation == "call.settings_update": return {}
            assert operation == "native.command"
            if params["command"] == state.fail_command: raise state.failure
            if params["command"] == "reconnect_consent_set": return copy.deepcopy(state.consent)
            assert params["command"] == "reconnect_capabilities_store"
            return copy.deepcopy(state.imported)
        def inventory(self):
            state.events.append("inventory")
            return {"service_incarnation": "old"}
        def stop(self, **kwargs):
            state.events.append(("stop", kwargs))
            raise state.stop
    instance = controller.Controller(role, Peer(), None, None, {})
    instance.profile = "PRIVATE_CORE_PROFILE"
    instance.contact = {"id": "PRIVATE_CONTACT", "destination_hash": "a" * 32}
    instance.default_call_settings = {"signal_mailbox_url": "https://synthetic.invalid"}
    def publish(phase, value): state.events.append(("publish", phase, copy.deepcopy(value)))
    def receive(phase):
        state.events.append(("receive", phase))
        return state.received
    monkeypatch.setattr(instance, "publish", publish)
    monkeypatch.setattr(instance, "receive", receive)
    state.controller = instance
    return state


@pytest.mark.parametrize("role", ["windows", "android"])
def test_cold_consent_is_published_then_imported_before_first_crash(monkeypatch, role):
    state = cold_setup_controller(monkeypatch, role=role)
    with pytest.raises(RuntimeError) as failure: state.controller.cold_starts()
    assert failure.value is state.stop
    commands = [event[1]["command"] for event in state.events if isinstance(event, tuple) and event[0] == "native.command"]
    assert commands == ["reconnect_consent_set", "reconnect_capabilities_store"]
    assert state.events[2:4] == [("publish", "reconnect_capabilities", {"capabilities": "PRIVATE_SIGNED_CAPABILITIES"}),
                                  ("receive", "reconnect_capabilities")]
    assert state.events[4] == ("native.command", {"command": "reconnect_capabilities_store", "payload": {
        "document": "PRIVATE_PEER_CAPABILITIES", "expected_contact_id": "PRIVATE_CONTACT", "expected_peer_destination": "a" * 32}})
    assert state.events[-2:] == ["inventory", ("stop", {"crash": True})]


@pytest.mark.parametrize("field", ["id", "contact_id", "destination_hash", "local_device_id", "remote_device_id"])
@pytest.mark.parametrize("poison", [None, "", 7, "PRIVATE_REPLACED_ASSOCIATION"])
def test_cold_import_cannot_change_any_profile_or_device_association(monkeypatch, field, poison):
    state = cold_setup_controller(monkeypatch)
    state.imported["profile"][field] = poison
    with pytest.raises(ValueError): state.controller.cold_starts()
    assert "inventory" not in state.events and not any(event[0] == "stop" for event in state.events)


@pytest.mark.parametrize("field", ["pending", "auto_reconnect", "peer_auto_reconnect"])
@pytest.mark.parametrize("poison", [None, 0, 1, "true", {}, []])
def test_cold_import_requires_exact_mutual_consent_and_nonpending(monkeypatch, field, poison):
    state = cold_setup_controller(monkeypatch)
    selected = state.imported if field == "pending" else state.imported["profile"]
    selected[field] = poison
    with pytest.raises(ValueError): state.controller.cold_starts()
    assert "inventory" not in state.events


@pytest.mark.parametrize("fault", ["pending_true", "pending_missing", "profile_missing", "profile_none", "local_false", "peer_false"])
def test_cold_import_declined_or_stale_result_cannot_reach_crash(monkeypatch, fault):
    state = cold_setup_controller(monkeypatch)
    if fault == "pending_true": state.imported["pending"] = True
    elif fault == "pending_missing": del state.imported["pending"]
    elif fault == "profile_missing": del state.imported["profile"]
    elif fault == "profile_none": state.imported["profile"] = None
    else: state.imported["profile"]["auto_reconnect" if fault == "local_false" else "peer_auto_reconnect"] = False
    with pytest.raises(ValueError): state.controller.cold_starts()
    assert "inventory" not in state.events


@pytest.mark.parametrize("fault", ["contact", "destination", "local_missing", "remote_missing", "disabled", "not_bool", "capability_missing", "capability_large"])
def test_cold_local_consent_must_target_current_complete_association_before_publish(monkeypatch, fault):
    state = cold_setup_controller(monkeypatch)
    profile = state.consent["profile"]
    if fault == "contact": profile["contact_id"] = "PRIVATE_OTHER_CONTACT"
    elif fault == "destination": profile["destination_hash"] = "b" * 32
    elif fault == "local_missing": del profile["local_device_id"]
    elif fault == "remote_missing": del profile["remote_device_id"]
    elif fault == "disabled": profile["auto_reconnect"] = False
    elif fault == "not_bool": profile["auto_reconnect"] = 1
    elif fault == "capability_missing": state.consent["capabilities"] = ""
    else: state.consent["capabilities"] = "x" * 16385
    with pytest.raises(ValueError): state.controller.cold_starts()
    assert len(state.events) == 2 and "inventory" not in state.events


@pytest.mark.parametrize("received", [{}, {"capabilities": ""}, {"capabilities": None},
    {"capabilities": "x", "profile": {}}, {"capabilities": "x" * 16385}])
def test_cold_peer_payload_is_exact_and_bounded_before_product_import(monkeypatch, received):
    state = cold_setup_controller(monkeypatch, received=received)
    with pytest.raises(ValueError): state.controller.cold_starts()
    assert len(state.events) == 4 and "inventory" not in state.events


@pytest.mark.parametrize("command", ["reconnect_consent_set", "reconnect_capabilities_store"])
def test_cold_product_error_keeps_original_identity_without_retry_or_crash(monkeypatch, command):
    state = cold_setup_controller(monkeypatch)
    state.fail_command = command
    deadline = state.controller.deadline
    with pytest.raises(controller.PeerFailure) as failure: state.controller.cold_starts()
    assert failure.value is state.failure and state.controller.deadline == deadline
    assert sum(isinstance(event, tuple) and event[0] == "native.command" and event[1]["command"] == command
               for event in state.events) == 1
    assert "inventory" not in state.events and not state.controller.cycles


@pytest.mark.parametrize("mode,iterations,restarts", [("quick", 5, 1), ("full", 100, 10)])
@pytest.mark.parametrize("role", ["windows", "android"])
def test_cold_setup_keeps_actual_loop_schedule_receipt_checks_and_native_deltas(monkeypatch, sample, mode, iterations, restarts, role):
    """Actual cold loop/projections; observations/receipts/processes are DTO doubles."""
    state = cold_setup_controller(monkeypatch, role=role)
    instance, peer = state.controller, state.controller.peer
    instance.workload = controller.required_workload(mode)
    state.incarnation, state.observations, state.exchanges, state.deliveries, state.stops = 1, 0, [], [], []
    def inventory():
        return {**terminal_inventory(resources=True, active=1), "service_incarnation": str(state.incarnation)}
    def stop(**kwargs):
        assert state.events[4][0] == "native.command" and state.events[4][1]["command"] == "reconnect_capabilities_store"
        state.stops.append((len(state.exchanges), kwargs))
    def start():
        state.incarnation += 1
        return inventory()
    core = peer.core
    def core_call(operation, params, key=None):
        if operation == "runtime.capabilities": return {"profiles": [instance.profile]}
        return core(operation, params, key)
    monkeypatch.setattr(peer, "inventory", inventory)
    monkeypatch.setattr(peer, "stop", stop)
    monkeypatch.setattr(peer, "start", start, raising=False)
    monkeypatch.setattr(peer, "core", core_call)
    monkeypatch.setattr(instance, "approved_contact", lambda: instance.contact)
    monkeypatch.setattr(instance, "snapshot", lambda: {"profile": {"destination_hash": "PRIVATE_DURABLE_IDENTITY"}})
    instance.identity = evidence.digest("PRIVATE_DURABLE_IDENTITY")
    def observe(logical=None, ready=False):
        assert ready is True
        state.observations += 1
        value = copy.deepcopy(sample[0])
        value["service_incarnation"] = str(state.incarnation)
        value["sample_sequence"] = state.observations
        value["application"] = dict.fromkeys(evidence.APPLICATION, state.observations)
        return value
    def exchange(scenario, index):
        assert scenario == "cold_start_receipts"
        state.exchanges.append(index)
        return {"outbound": "a" * 64, "inbound": "b" * 64}, "PRIVATE_MESSAGE_" + str(index)
    monkeypatch.setattr(instance, "observe", observe)
    monkeypatch.setattr(instance, "exchange", exchange)
    monkeypatch.setattr(instance, "delivered", lambda message: state.deliveries.append(message) or True)
    deadline = instance.deadline
    instance.cold_starts()
    assert instance.deadline == deadline and len(instance.cycles) == iterations
    assert state.exchanges == list(range(iterations)) and len(state.deliveries) == iterations - 1
    assert state.stops == [(index, {"crash": True}) for index in range(0, iterations, 10)]
    assert len(state.stops) == restarts and state.observations == iterations * 2
    assert [cycle["cold_start"] for cycle in instance.cycles] == [index % 10 == 0 for index in range(iterations)]
    for cycle in instance.cycles:
        assert cycle["native_delta"] == dict.fromkeys(evidence.APPLICATION, 1)
        assert cycle["native_resources"] == cycle["warm_baseline_resources"] == 1
        assert cycle["host_accounting"] == cycle["warm_baseline_host_accounting"]
    assert "PRIVATE" not in json.dumps(instance.cycles)
    assert len([event for event in state.events if isinstance(event, tuple) and event[0] == "publish"]) == 1


@pytest.mark.parametrize("mode", ["quick", "full"])
@pytest.mark.parametrize("failure_index", [None, -1])
def test_run_enters_cold_consent_only_after_last_required_manual_retirement(monkeypatch, mode, failure_index):
    state = cold_setup_controller(monkeypatch)
    instance = state.controller
    instance.workload = controller.required_workload(mode)
    paths = instance.workload["paths"]
    events = []
    instance.transport = SimpleNamespace(publish=lambda *args: events.append("key_publish"), wait=lambda *args, **kwargs: {})
    instance.rendezvous = SimpleNamespace(public_manifest=lambda: {}, bind_partner=lambda _: events.append("key_bind"))
    monkeypatch.setattr(instance, "initialize", lambda: None)
    def path_case(scenario, initiator):
        if failure_index is not None and (scenario, initiator) == paths[failure_index]: raise state.failure
        events.append((scenario, initiator, "owner_ack_and_global_zero"))
    monkeypatch.setattr(instance, "path_case", path_case)
    with pytest.raises((RuntimeError, controller.PeerFailure)) as failure: instance.run()
    if failure_index is not None:
        assert failure.value is state.failure and not state.events
    else:
        assert failure.value is state.stop
        assert events == ["key_publish", "key_bind", *[(scenario, initiator, "owner_ack_and_global_zero") for scenario, initiator in paths]]
        assert state.events[0][0] == "call.settings_update"


@pytest.fixture
def signed_cold_services(tmp_path, monkeypatch):
    """Actual encrypted stores and signatures; no network, carrier or native host."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from test_reconnect_service import _pair
    from mesh_chat.service import MeshChatService
    monkeypatch.setattr(MeshChatService, "_start_network", lambda *_: None)
    first, first_contact, second, second_contact = _pair(tmp_path)
    services, contacts, documents = [first, second], [first_contact, second_contact], []
    try:
        for service, contact in zip(services, contacts):
            result = service._execute("reconnect_consent_set", {"contact_id": contact,
                "auto_reconnect": False, "allow_direct_ip_disclosure": True})
            assert result["native_shared"] is False and not service._native_webrtc_live
            documents.append(result["capabilities"])
        for index, service in enumerate(services):
            service._execute("reconnect_capabilities_store", {"document": documents[1 - index],
                "expected_contact_id": contacts[index],
                "expected_peer_destination": service.store.get("contact", contacts[index])["destination_hash"]})
            profile = service.reconnect_profiles()["profiles"][0]
            assert profile["auto_reconnect"] is False and profile["peer_auto_reconnect"] is False
        yield SimpleNamespace(services=services, contacts=contacts, old_documents=documents, root=tmp_path)
    finally:
        for service in services: service.close()


def signed_cold_controller(state, index, transport):
    service, contact_id = state.services[index], state.contacts[index]
    contact = service.store.get("contact", contact_id)
    class Peer:
        def core(self, operation, params, key=None):
            if operation == "call.settings_update":
                state.events.append((index, "settings"))
                return service.update_call_settings(params["settings"])
            assert operation == "native.command"
            command = params["command"]
            state.events.append((index, command))
            result = service._execute(command, params["payload"])
            if command == "reconnect_consent_set":
                assert result["native_shared"] is False
                assert result["profile"]["peer_auto_reconnect"] is False
            return result
        def inventory(self): return {"service_incarnation": "old"}
        def stop(self, **kwargs):
            assert kwargs == {"crash": True}
            profile = service.reconnect_profiles()["profiles"][0]
            assert profile["auto_reconnect"] is True and profile["peer_auto_reconnect"] is True
            state.events.append((index, "first_crash"))
            raise state.stop
    role = ("windows", "android")[index]
    instance = controller.Controller(role, Peer(), transport, state.rendezvous[index], state.context)
    instance.profile, instance.contact = "PRIVATE_CORE_PROFILE", contact
    instance.default_call_settings = service._call_settings.to_dict()
    return instance


def test_actual_signed_cold_exchange_persists_both_consents_before_each_own_crash(signed_cold_services, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from test_reconnect_reopen import _reopen
    from native_interop_rendezvous import Rendezvous, canonical
    state = signed_cold_services
    state.context = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
        "run_attempt": 1, "source_commit": "a" * 40}
    state.rendezvous = [Rendezvous(state.context, role) for role in ("windows", "android")]
    for index in range(2): state.rendezvous[index].bind_partner(state.rendezvous[1 - index].public_manifest())
    state.events, state.stop = [], RuntimeError("first_crash_barrier")
    sealed, barrier = {}, Barrier(2)
    class Transport:
        def __init__(self, index): self.index = index
        def publish(self, phase, value):
            assert phase == "reconnect_capabilities" and self.index not in sealed
            assert set(value) == {"v", "context", "phase", "sender", "recipient", "producer_job", "created_at", "expires_at", "nonce", "ciphertext"}
            assert b'"capabilities"' not in canonical(value)
            sealed[self.index] = copy.deepcopy(value)
            state.events.append((self.index, "publish"))
            barrier.wait(timeout=5)
        def wait(self, role, phase, timeout):
            assert self.index in sealed and 1 - self.index in sealed and timeout == 180
            assert phase == "reconnect_capabilities" and role == ("android" if self.index == 0 else "windows")
            state.events.append((self.index, "receive"))
            return sealed[1 - self.index]
    try:
        instances = [signed_cold_controller(state, index, Transport(index)) for index in range(2)]
        def run(instance):
            with pytest.raises(RuntimeError) as failure: instance.cold_starts()
            assert failure.value is state.stop
        with ThreadPoolExecutor(max_workers=2) as executor: list(executor.map(run, instances))
        for index in range(2):
            assert [event for peer, event in state.events if peer == index] == ["settings", "reconnect_consent_set",
                "publish", "receive", "reconnect_capabilities_store", "first_crash"]
            assert instances[index].cycles == []
            assert "capabilities" not in vars(instances[index])
        before = [service.reconnect_profiles()["profiles"][0] for service in state.services]
        for service in state.services: service.close()
        state.services[:] = [_reopen(state.root / name, monkeypatch) for name in ("alex", "blair")]
        for index, service in enumerate(state.services):
            profile = service.reconnect_profiles()["profiles"][0]
            for field in ("id", "contact_id", "local_device_id", "remote_device_id"):
                assert profile[field] == before[index][field]
            assert profile["auto_reconnect"] is True and profile["peer_auto_reconnect"] is True
            assert profile["effective"]["ready"] is True
            request = service.reconnect_request_create(state.contacts[index], uuid4().hex)
            assert state.services[1 - index].verify_reconnect_request(request["document"])
    finally:
        for rendezvous in state.rendezvous: rendezvous.close()


@pytest.mark.parametrize("fault", ["wrong_peer", "wrong_recipient", "signature", "stale_false", "changed_device"])
def test_actual_signed_cold_import_rejects_foreign_forged_stale_or_rebound_peer(signed_cold_services, fault):
    import RNS
    from mesh_chat.errors import IdentityMismatch, ValidationError
    from mesh_chat.reconnect import create_connection_capabilities, verify_connection_capabilities
    from native_interop_rendezvous import Rendezvous
    state = signed_cold_services
    state.context = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
        "run_attempt": 1, "source_commit": "a" * 40}
    state.events, state.stop = [], RuntimeError("must_not_reach_crash")
    state.rendezvous = [Rendezvous(state.context, role) for role in ("windows", "android")]
    for index in range(2): state.rendezvous[index].bind_partner(state.rendezvous[1 - index].public_manifest())
    remote = state.services[1]
    document = remote._execute("reconnect_consent_set", {"contact_id": state.contacts[1],
        "auto_reconnect": True, "allow_direct_ip_disclosure": True})["capabilities"]
    if fault == "stale_false": document = state.old_documents[1]
    elif fault == "signature":
        value = json.loads(document)
        value["auto_reconnect"] = False
        document = json.dumps(value)
    else:
        valid = verify_connection_capabilities(document)
        document = create_connection_capabilities(RNS.Identity() if fault == "wrong_peer" else remote._call_identity(),
            peer_destination="0" * 32 if fault == "wrong_recipient" else valid.peer_destination,
            device_id="dev-other-device" if fault == "changed_device" else valid.device_id,
            transports=["webrtc"], auto_reconnect=True, allow_direct_ip_disclosure=True,
            mailbox_url=valid.mailbox_url, mailbox_pair_token=valid.mailbox_pair_token,
            mailbox_secret=valid.mailbox_secret, mailbox_expires_at=0,
            persistent=True, encrypted=True, now=valid.issued_at + 1)
    sealed = state.rendezvous[1].seal("reconnect_capabilities", {"capabilities": document})
    class Transport:
        def publish(self, phase, value): state.events.append((0, "publish"))
        def wait(self, role, phase, timeout):
            assert state.events[-1] == (0, "publish")
            state.events.append((0, "receive"))
            return sealed
    try:
        instance = signed_cold_controller(state, 0, Transport())
        with pytest.raises((ValueError, IdentityMismatch, ValidationError)): instance.cold_starts()
        assert (0, "first_crash") not in state.events and instance.cycles == []
        assert [event for _, event in state.events].count("reconnect_capabilities_store") == 1
        assert (1, "first_crash") not in state.events
    finally:
        for rendezvous in state.rendezvous: rendezvous.close()


def terminal_inventory(*, resources=False, active=0, retiring=0):
    return {"resources": [{"logical_session": "PRIVATE_LOGICAL", "physical_resource": "PRIVATE_PHYSICAL"}] if resources else [],
        "host_accounting": {"v": 1, "complete": True, "semantics": "native_allocation_leases",
            "availability": {name: True for name in evidence.ACCOUNTING}, "capacity": 16,
            "reserved_count": active + retiring, "creating_count": 0, "allocated_count": active + retiring,
            "active_count": active, "retiring_count": retiring}}


def run_terminal_report(tmp_path, monkeypatch, capsys, *, role="android", polls=None, remaining=3000,
                        stop_error=False, cleanup_error=False):
    """Actual main/run/retired/wait; earlier workload and external peers are inert."""
    import connection_ci
    from mesh_chat.core_api.requests import parse_request
    state = SimpleNamespace(now=0.0, events=[], stop_requested=False, reads=0, failures=[],
                            stop_error=controller.PeerFailure("unavailable"))
    pending = polls if polls is not None else [terminal_inventory(resources=True, active=1),
        terminal_inventory(retiring=1), terminal_inventory()]
    profile, peer_handle = "scoped_profile_AAAA", "scoped_peer_AAAAAAA"
    class Peer:
        process = SimpleNamespace(pid=17)
        processes_started, forced_exits, clean_exits = 1, 0, 0
        def core(self, operation, params, key=None):
            assert key is None
            if operation == "native.command":
                command = params["command"]
                if command == "reconnect_consent_set":
                    assert params["payload"] == {"contact_id": "PRIVATE_CONTACT_ID", "auto_reconnect": False,
                                                  "allow_direct_ip_disclosure": True}
                    state.events.append("consent_disabled")
                    return {}
                assert command == "native_webrtc_close"
                state.events.append("compatibility_close")
                return {"state": "managed"}
            assert operation == "connection.stop" and params == {"profile": profile, "peer": peer_handle}
            assert parse_request({"api_version": 1, "request_id": "terminal:stop", "operation": operation,
                                  "params": params}, {operation}) == (operation, params)
            state.events.append("connection.stop")
            if stop_error: raise state.stop_error
            state.stop_requested = True
            return {"profile": profile, "peer": peer_handle, "desired": "stopped", "active": False}
        def inventory(self):
            state.events.append("inventory")
            state.reads += 1
            if not state.stop_requested: return terminal_inventory(resources=True, active=1)
            return copy.deepcopy(pending[min(state.reads - 1, len(pending) - 1)])
        def stop(self, **kwargs):
            state.events.append(("host.stop", kwargs))
            self.process = None
            if cleanup_error: raise ValueError("PRIVATE_CLEANUP_ERROR")
            self.clean_exits += 1
    peer = Peer()
    def initialize(instance):
        state.controller = instance
        instance.profile, instance.contact, instance.identity = profile, {"id": "PRIVATE_CONTACT_ID", "core_handle": peer_handle}, "a" * 64
        instance.deadline = state.now + remaining
    def sleep(seconds):
        assert seconds == 0.25
        state.events.append("sleep")
        state.now += seconds
    failure_site = controller.Controller.failure_site
    def observe_failure(instance, error):
        state.failures.append(error)
        return failure_site(instance, error)
    monkeypatch.setattr(controller.Controller, "failure_site", observe_failure)
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    monkeypatch.setattr(controller.Controller, "initialize", initialize)
    monkeypatch.setattr(controller.Controller, "path_case", lambda _, scenario, initiator: state.events.append((scenario, initiator)))
    monkeypatch.setattr(controller.Controller, "cold_starts", lambda _: state.events.append("cold_starts"))
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_, **__: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(publish=lambda *_: None, wait=lambda *_, **__: {}, close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(public_manifest=lambda: {}, bind_partner=lambda _: None, close=lambda: None))
    import check_native_windows_messaging
    monkeypatch.setattr(check_native_windows_messaging, "descendants", lambda _: [])
    output = tmp_path / "terminal.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state, peer=peer,
                           output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("role", ["windows", "android"])
def test_terminal_scoped_owner_stop_precedes_strict_retirement_observation(tmp_path, monkeypatch, capsys, role):
    run = run_terminal_report(tmp_path, monkeypatch, capsys, role=role)
    assert run.code == 0 and run.state.stop_requested
    assert "compatibility_close" not in run.state.events
    terminal = run.state.events[run.state.events.index("consent_disabled"):]
    assert terminal == ["consent_disabled", "connection.stop", "inventory", "sleep", "inventory", "sleep", "inventory",
                        ("host.stop", {"delete_profile": True} if role == "android" else {})]
    assert run.record["execution"]["final_host_accounting"] == terminal_inventory()["host_accounting"]
    assert "PRIVATE" not in run.output
    with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, role)


@pytest.mark.parametrize("pending", [
    pytest.param(terminal_inventory(resources=True), id="logical-resource-with-native-zero"),
    pytest.param(terminal_inventory(active=1), id="active-native-with-logical-empty"),
    pytest.param(terminal_inventory(retiring=1), id="retiring-native-with-logical-empty"),
    pytest.param({**terminal_inventory(), "host_accounting": {
        **terminal_inventory()["host_accounting"], "reserved_count": 1}}, id="reserved-native"),
    pytest.param({**terminal_inventory(), "host_accounting": {
        **terminal_inventory()["host_accounting"], "reserved_count": 1, "creating_count": 1}}, id="creating-native"),
])
def test_terminal_desired_stopped_reply_is_not_retirement_ack(tmp_path, monkeypatch, capsys, pending):
    run = run_terminal_report(tmp_path, monkeypatch, capsys, polls=[pending], remaining=0.5)
    assert run.state.stop_requested and run.state.events.count("connection.stop") == 1
    assert run.code == 1 and run.record["phase"] == "clean_host_retirement"
    assert run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "scenario_deadline"
    assert run.state.reads == 2 and run.state.events.count("sleep") == 2 and run.state.now == 0.5
    assert "execution" not in run.record and "compatibility_close" not in run.state.events
    assert run.state.events[-1] == ("host.stop", {"crash": True})
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("remaining,reads,elapsed", [(3000, 120, 30), (0, 0, 0)])
def test_terminal_owner_stop_preserves_original_local_and_global_wait_budget(tmp_path, monkeypatch, capsys, remaining, reads, elapsed):
    run = run_terminal_report(tmp_path, monkeypatch, capsys, polls=[terminal_inventory(active=1)], remaining=remaining)
    assert run.code == 1 and run.record["error_code"] == "scenario_deadline"
    assert run.state.events.count("connection.stop") == 1 and run.state.reads == reads
    assert run.state.events.count("sleep") == reads and run.state.now == elapsed


@pytest.mark.parametrize("cleanup_error", [False, True])
def test_terminal_stop_error_keeps_original_main_error_and_attempts_cleanup(tmp_path, monkeypatch, capsys, cleanup_error):
    run = run_terminal_report(tmp_path, monkeypatch, capsys, stop_error=True, cleanup_error=cleanup_error)
    assert run.code == 1 and run.record["phase"] == "clean_host_retirement"
    assert run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "unavailable"
    assert run.state.failures == [run.state.stop_error]  # Exact escaping object, even if cleanup fails later.
    assert run.state.reads == 0 and run.state.events.count("connection.stop") == 1
    assert "compatibility_close" not in run.state.events and "execution" not in run.record
    assert run.state.events[-1] == ("host.stop", {"crash": True})
    assert run.record.get("cleanup_failed", False) is cleanup_error
    assert "PRIVATE" not in run.output


def test_terminal_stop_cannot_turn_unavailable_accounting_into_zero(tmp_path, monkeypatch, capsys):
    inventory = terminal_inventory()
    inventory["host_accounting"]["complete"] = False
    run = run_terminal_report(tmp_path, monkeypatch, capsys, polls=[inventory])
    assert run.code == 1 and run.state.stop_requested and run.state.reads == 1
    assert run.record["failure_type"] == "AccountingUnavailable" and run.record["error_code"] == "native_accounting_unavailable"
    assert "execution" not in run.record


def carrier_inventory(*, state="acknowledged", request_id="ECHO", resources=False, active=0, retiring=0):
    return {**terminal_inventory(resources=resources, active=active, retiring=retiring),
        "service_incarnation": "b" * 32, "profile_incarnation": "c" * 32,
        "carrier_retirement": {"request_id": request_id, "state": state}}


def retirement_case(monkeypatch, sample, *, role="windows", polls=None, reply=None, remaining=3000, request_error=None,
                    prepare_reply=None):
    """Actual path_case/wait/retired; ready path/receipt and private peer doubles."""
    original, _ = sample
    state = SimpleNamespace(now=0.0, events=[], requests=[], inventories=[], random_draws=[], case_index=0,
                            observation=0, reads=0, current=None, request_error=request_error, actions=[], markers=[])
    state.request_error_action, state.completion_failure = "prepare", None
    state.completion_reply = {"completed": True}
    templates = polls if polls is not None else [carrier_inventory(state="pending"),
        carrier_inventory(retiring=1), carrier_inventory()]
    class Peer:
        def core(self, operation, params, key=None):
            assert operation == "native.command" and params["command"] == "native_webrtc_close"
            state.events.append("compatibility_close")
            return {"state": "managed"}
        def pairing_status(self, operation): return {"operation_id": operation, "state": "transferred"}
        def pairing_cancel(self, operation): return {"operation_id": operation, "state": "transferred"}
        def retire_carrier(self, operation_id, request_id, logical_session, expected_physical,
                           expected_service_incarnation, expected_adapter_epoch, *, action=None):
            state.actions.append(action)
            request = {"operation_id": operation_id, "request_id": request_id,
                "logical_session": logical_session, "expected_physical": expected_physical,
                "expected_service_incarnation": expected_service_incarnation, "expected_adapter_epoch": expected_adapter_epoch}
            if action == "commit": assert request == state.requests[-1]
            else: state.requests.append(request)
            state.reads = 0
            if state.request_error is not None and action in {None, state.request_error_action}: raise state.request_error
            if remaining == 0 and action != "prepare": state.now = state.controller.deadline
            selected = prepare_reply if action == "prepare" else reply
            value = copy.deepcopy(selected if selected is not None else {
                "request_id": "ECHO", "state": "prepared" if action == "prepare" else "pending"})
            if isinstance(value, dict) and value.get("request_id") == "ECHO": value["request_id"] = request_id
            return value
        def inventory(self, *, operation_id=None, request_id=None):
            state.inventories.append((operation_id, request_id))
            state.reads += 1
            if not state.requests: return carrier_inventory(resources=True, active=1)
            assert state.actions[-2:] == ["prepare", "commit"]
            assert operation_id == state.requests[-1]["operation_id"] and request_id == state.requests[-1]["request_id"]
            value = copy.deepcopy(templates[min(state.reads - 1, len(templates) - 1)])
            echo = value.get("carrier_retirement")
            if isinstance(echo, dict) and echo.get("request_id") == "ECHO": echo["request_id"] = request_id
            return value
    def sleep(seconds):
        assert seconds == 0.25
        state.events.append("sleep")
        state.now += seconds
    def random_bytes(size):
        state.random_draws.append(size)
        return bytes([(0xdd + 17 * (len(state.random_draws) - 1)) % 256]) * size
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    monkeypatch.setattr(controller.os, "urandom", random_bytes)
    instance = controller.Controller(role, Peer(), None, None, {})
    def publish(phase, value):
        assert state.actions[-1] == "prepare" and value == {"completed": True}
        state.markers.append(("publish", phase, value))
        if state.completion_failure == "publish": raise state.request_error
    def receive(partner, phase, *, timeout):
        assert state.actions[-1] == "prepare" and state.markers[-1] == ("publish", phase, {"completed": True})
        state.markers.append(("receive", phase, timeout))
        if state.completion_failure == "receive": raise state.request_error
        return state.completion_reply
    instance.transport = SimpleNamespace(publish=publish, wait=receive)
    instance.rendezvous = SimpleNamespace(seal=lambda phase, value: value, open=lambda phase, value: value)
    instance.contact = {"id": "PRIVATE_CONTACT", "core_handle": "PRIVATE_HANDLE"}
    instance.deadline = remaining if remaining > 0 else 3000
    def negotiate(scenario, initiator):
        state.case_index += 1
        state.observation = 0
        instance.pairing = f"00000000-0000-4000-8000-{state.case_index:012x}"
        state.current = copy.deepcopy(original)
        state.current.update(service_incarnation="b" * 32, profile_incarnation="c" * 32,
            logical_session=f"PRIVATE_LOGICAL_{state.case_index}", resource=f"PRIVATE_PHYSICAL_{state.case_index}")
        return state.current["logical_session"], None
    def observe(*args, **kwargs):
        state.observation += 1
        value = copy.deepcopy(state.current)
        value["sample_sequence"] = state.observation
        if state.observation >= 3: value["application"] = dict.fromkeys(evidence.APPLICATION, 1)
        return value
    instance.negotiate, instance.observe = negotiate, observe
    instance.exchange = lambda *_args, **_kwargs: ({"outbound": "1" * 64, "inbound": "2" * 64,
        "authenticated_receipt": True, "inbound_records": 1, "outbound_records": 1, "receipt_roundtrip_ms": 1}, "PRIVATE_MESSAGE")
    state.controller = instance
    return state


def test_prepared_case_publishes_completion_before_committing_same_request(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    state.controller.path_case("direct", "windows")
    assert state.actions == ["prepare", "commit"]
    assert state.markers == [("publish", "case_complete_direct_windows", {"completed": True}),
                             ("receive", "case_complete_direct_windows", 180)]
    assert len(state.requests) == 1 and state.controller.cases[-1]["owner_retirement_acknowledged"] is True


@pytest.mark.parametrize("reply", [{}, [], {"request_id": "ECHO", "state": "pending"},
    {"request_id": "ECHO", "state": "acknowledged"}, {"request_id": "ECHO", "state": True},
    {"request_id": "0" * 32, "state": "prepared"}, {"request_id": "ECHO", "state": "prepared", "extra": True}])
def test_first_prepare_reply_requires_exact_prepared_before_any_marker(monkeypatch, sample, reply):
    state = retirement_case(monkeypatch, sample, prepare_reply=reply)
    with pytest.raises(controller.PeerFailure) as failure: state.controller.path_case("direct", "windows")
    assert failure.value.code == "invalid_carrier_retirement_reply"
    assert state.actions == ["prepare"] and not state.markers and not state.inventories
    assert state.controller.failure_retirement(failure.value)["carrier_retirement_failure"]["stage"] == "prepare"


@pytest.mark.parametrize("marker", [{}, {"completed": False}, {"completed": 1}, {"completed": None},
    {"completed": "true"}, {"completed": True, "initiator": "windows"}, {"approved": True}])
def test_case_completion_is_exact_true_and_failure_never_commits(monkeypatch, sample, marker):
    state = retirement_case(monkeypatch, sample)
    state.completion_reply = marker
    with pytest.raises(ValueError) as failure: state.controller.path_case("direct", "windows")
    assert state.actions == ["prepare"] and len(state.markers) == 2 and not state.inventories
    context = state.controller.failure_retirement(failure.value)["carrier_retirement_failure"]
    assert context == {"scenario": "direct", "initiator": "windows", "stage": "completion_receive", "polls": 0,
                       "polls_capped": False, "last_observation": None}


@pytest.mark.parametrize("remaining", [0.5, 180, 3000])
def test_completion_receive_uses_existing_ceiling_and_remaining_global_budget(monkeypatch, sample, remaining):
    state = retirement_case(monkeypatch, sample, remaining=remaining, polls=[carrier_inventory()])
    state.controller.path_case("direct", "windows")
    assert state.markers[-1] == ("receive", "case_complete_direct_windows", min(180, remaining))
    assert state.controller.deadline == remaining and state.actions == ["prepare", "commit"]


def test_exhausted_global_budget_does_not_start_completion_wait_or_commit(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    original = state.controller.peer.retire_carrier
    def retire(*args, **kwargs):
        reply = original(*args, **kwargs)
        state.now = state.controller.deadline
        return reply
    monkeypatch.setattr(state.controller.peer, "retire_carrier", retire)
    with pytest.raises(controller.PeerFailure) as failure: state.controller.path_case("direct", "windows")
    assert failure.value.code == "scenario_deadline" and state.actions == ["prepare"]
    assert len(state.markers) == 1 and state.markers[0][0] == "publish" and not state.inventories


def test_prepared_inventory_cannot_satisfy_postcommit_poll_even_when_global_zero(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample, polls=[carrier_inventory(state="prepared")])
    with pytest.raises(controller.PeerFailure) as failure: state.controller.path_case("direct", "windows")
    assert failure.value.code == "invalid_carrier_retirement_reply" and state.actions == ["prepare", "commit"]
    assert "owner_retirement_acknowledged" not in state.controller.cases[-1]


def test_per_case_owner_request_and_acknowledgment_precede_zero_evidence(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    state.controller.path_case("direct", "windows")
    assert len(state.requests) == 1 and "compatibility_close" not in state.events
    assert state.controller.cases[-1]["owner_retirement_acknowledged"] is True
    assert state.controller.cases[-1]["retired_host_accounting"] == terminal_inventory()["host_accounting"]
    assert state.events == ["sleep", "sleep"] and state.random_draws == [16]


@pytest.mark.parametrize("role", ["windows", "android"])
def test_each_manual_case_uses_fresh_nonce_and_exact_current_sample_target(monkeypatch, sample, role):
    state = retirement_case(monkeypatch, sample, role=role)
    state.controller.path_case("direct", "windows")
    state.controller.path_case("direct", "android")
    assert state.random_draws == [16, 16] and len(state.requests) == 2
    assert state.actions == ["prepare", "commit", "prepare", "commit"]
    assert [marker[1] for marker in state.markers if marker[0] == "publish"] == [
        "case_complete_direct_windows", "case_complete_direct_android"]
    for index, request in enumerate(state.requests, 1):
        assert request == {"operation_id": f"00000000-0000-4000-8000-{index:012x}",
            "request_id": ("d" if index == 1 else "e") * 32, "logical_session": f"PRIVATE_LOGICAL_{index}",
            "expected_physical": f"PRIVATE_PHYSICAL_{index}", "expected_service_incarnation": "b" * 32,
            "expected_adapter_epoch": "a" * 32}
    assert state.inventories == [(request["operation_id"], request["request_id"])
                                 for request in state.requests for _ in range(3)]
    assert all(case["owner_retirement_acknowledged"] is True for case in state.controller.cases)
    encoded = json.dumps(state.controller.cases)
    assert "request_id" not in encoded and "PRIVATE" not in encoded
    assert all(value not in encoded for request in state.requests for value in request.values())


@pytest.mark.parametrize("reply", [
    pytest.param(value, id=label) for label, value in (
        ("missing", {}), ("type", []), ("wrong-request", {"request_id": "0" * 32, "state": "pending"}),
        ("immediate-ack", {"request_id": "ECHO", "state": "acknowledged"}),
        ("prepared-is-not-pending", {"request_id": "ECHO", "state": "prepared"}),
        ("unknown-state", {"request_id": "ECHO", "state": "retired"}),
        ("state-type", {"request_id": "ECHO", "state": True}),
        ("extra", {"request_id": "ECHO", "state": "pending", "resource": "PRIVATE_RESOURCE"}),
    )
])
def test_first_retirement_reply_cannot_supply_cleanup_ack_or_wrong_identity(monkeypatch, sample, reply):
    state = retirement_case(monkeypatch, sample, reply=reply)
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    assert caught.value.code == "invalid_carrier_retirement_reply"
    assert len(state.requests) == 1 and state.inventories == []
    assert "owner_retirement_acknowledged" not in state.controller.cases[-1]
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("echo", [
    pytest.param(value, id=label) for label, value in (
        ("missing", None), ("array", []), ("wrong-request", {"request_id": "0" * 32, "state": "acknowledged"}),
        ("request-type", {"request_id": True, "state": "acknowledged"}),
        ("unknown", {"request_id": "ECHO", "state": "retired"}),
        ("state-type", {"request_id": "ECHO", "state": True}),
        ("extra", {"request_id": "ECHO", "state": "acknowledged", "physical": "PRIVATE_RESOURCE"}),
    )
])
def test_correlated_inventory_requires_exact_request_and_known_ack_state(monkeypatch, sample, echo):
    inventory = carrier_inventory()
    if echo is None: inventory.pop("carrier_retirement")
    else: inventory["carrier_retirement"] = echo
    state = retirement_case(monkeypatch, sample, polls=[inventory])
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    assert caught.value.code == "invalid_carrier_retirement_reply"
    assert len(state.requests) == len(state.inventories) == 1 and state.events == []
    assert "owner_retirement_acknowledged" not in state.controller.cases[-1]


@pytest.mark.parametrize("field,value", [("service_incarnation", "f" * 32), ("profile_incarnation", "f" * 32),
                                        ("service_incarnation", None), ("profile_incarnation", True)])
def test_ack_from_changed_or_missing_scope_cannot_satisfy_retirement(monkeypatch, sample, field, value):
    inventory = carrier_inventory()
    inventory[field] = value
    state = retirement_case(monkeypatch, sample, polls=[inventory])
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    assert caught.value.code == "carrier_retirement_scope_changed"
    assert len(state.inventories) == 1 and "owner_retirement_acknowledged" not in state.controller.cases[-1]


@pytest.mark.parametrize("inventory", [
    pytest.param(carrier_inventory(state="pending"), id="pending-with-zero"),
    pytest.param(carrier_inventory(resources=True), id="ack-with-logical-resource"),
    pytest.param(carrier_inventory(active=1), id="ack-with-active-native"),
    pytest.param(carrier_inventory(retiring=1), id="ack-with-retiring-native"),
])
def test_acknowledgment_and_global_zero_are_independent_wait_requirements(monkeypatch, sample, inventory):
    state = retirement_case(monkeypatch, sample, polls=[inventory], remaining=0.5)
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    assert caught.value.code == "scenario_deadline" and len(state.requests) == 1
    assert len(state.inventories) == 2 and state.events == ["sleep", "sleep"] and state.now == 0.5
    assert "owner_retirement_acknowledged" not in state.controller.cases[-1]


@pytest.mark.parametrize("fault", ["counts_unavailable", "resources_type"])
def test_correlated_retirement_does_not_turn_unknown_observation_into_zero(monkeypatch, sample, fault):
    inventory = carrier_inventory()
    if fault == "counts_unavailable": inventory["host_accounting"]["complete"] = False
    else: inventory["resources"] = None
    state = retirement_case(monkeypatch, sample, polls=[inventory])
    with pytest.raises(ValueError if fault == "counts_unavailable" else controller.PeerFailure):
        state.controller.path_case("direct", "windows")
    assert "owner_retirement_acknowledged" not in state.controller.cases[-1]


def test_retirement_request_error_keeps_exact_exception_without_retry_or_poll(monkeypatch, sample):
    error = controller.PeerFailure("forbidden")
    state = retirement_case(monkeypatch, sample, request_error=error)
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    assert caught.value is error and len(state.requests) == 1 and state.inventories == []
    assert state.controller.phase == "direct_native_lease_retirement"


def test_previous_case_acknowledgment_cannot_satisfy_new_case(monkeypatch, sample):
    templates = [carrier_inventory()]
    state = retirement_case(monkeypatch, sample, polls=templates)
    state.controller.path_case("direct", "windows")
    templates[0]["carrier_retirement"]["request_id"] = state.requests[0]["request_id"]
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "android")
    assert caught.value.code == "invalid_carrier_retirement_reply" and len(state.requests) == 2
    assert state.controller.cases[0]["owner_retirement_acknowledged"] is True
    assert "owner_retirement_acknowledged" not in state.controller.cases[1]


def negative_control_case(monkeypatch, sample, *, role="android", point="receipt", cleanup_error=False,
                          scenario="turn_tcp", observer_mode=None):
    """Actual path_case/negative/receipt predicates; host/kernel DTO boundaries only."""
    import native_interop_faults
    state = retirement_case(monkeypatch, sample, role=role)
    instance, peer = state.controller, state.controller.peer
    def sleep(seconds):
        assert seconds in (0.1, 0.25)
        state.events.append(("sleep", seconds))
        state.now += seconds
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    instance.context = {"run_id": 123, "run_attempt": 1}
    state.blocked, state.restored, state.block_reads = False, False, 0
    state.point, state.cleanup_error = point, cleanup_error
    state.scenario = scenario
    state.observer_mode = observer_mode
    state.boundary_error = ValueError("PRIVATE_BOUNDARY_PAYLOAD")
    state.cleanup_exception = RuntimeError("PRIVATE_CLEANUP_PAYLOAD")
    def command(operation, params, key=None):
        state.events.append(operation)
        if operation == "message.enqueue":
            if state.point == "enqueue_error": raise state.boundary_error
            return {"accepted": state.point != "enqueue", "message": "PRIVATE_MESSAGE"}
        if operation == "message.query":
            if state.blocked:
                state.block_reads += 1
                if state.point == "receipt_error": raise state.boundary_error
                return {"state": "delivered" if state.point == "receipt" else "sending"}
            if state.point == "restored_error": raise state.boundary_error
            return {"state": "delivered"}
        assert operation == "application.snapshot"
        if state.point == "records_error": raise state.boundary_error
        values = [{"kind": "chat", "text": instance.text("blocked_path_" + state.scenario, sender=sender),
                   "direction": direction, "id": "PRIVATE_" + direction}
                  for sender, direction in ((instance.role, "outbound"), (instance.partner, "inbound"))]
        if state.point == "duplicate": values.append(dict(values[0]))
        return {"messages": values}
    peer.core = command
    class Fault:
        protocol, socket = "tcp", {"PRIVATE_SOCKET": "PRIVATE_ADDRESS"}
        def block(self):
            state.events.append("block")
            if state.point == "block_error": raise state.boundary_error
            state.blocked = True
        def unblock(self):
            state.events.append("unblock")
            state.blocked, state.restored = False, True
            if state.point == "unblock_error": raise state.boundary_error
            return 0 if state.point == "zero_drop" else 2
        def close(self):
            state.events.append("fault_cleanup")
            if state.cleanup_error: raise state.cleanup_exception
            state.blocked = False
        def install(self): pass
        def report(self):
            if state.point == "impairment_error": raise state.boundary_error
            return {}
    state.kernel = Fault()
    if observer_mode in {"actual_kernel_install", "actual_kernel_delete"}:
        from test_ui_core_boundary_interop_faults import diagnostic_kernel
        kernel = diagnostic_kernel(monkeypatch)
        kernel.value._negative_diagnostics = instance._negative_diagnostics
        kernel.fault = "install_error" if observer_mode == "actual_kernel_install" else "delete_error"
        state.boundary_error = kernel.error
        def block():
            kernel.value.block()
            state.blocked = True
        def unblock():
            packets = kernel.value.unblock()
            state.blocked, state.restored = False, True
            return packets
        state.kernel.block, state.kernel.unblock, state.kernel.close = block, unblock, kernel.value.close
    monkeypatch.setattr(native_interop_faults, "AndroidKernelPath", lambda *args, **kwargs: state.kernel)
    def publish(phase, value):
        state.events.append(("publish", phase))
        if state.point == "publish_error": raise state.boundary_error
        if phase.startswith("negative_checked"): state.blocked, state.restored = False, True
    def receive(partner, phase, *, timeout):
        state.events.append(("receive", phase, timeout))
        if phase.startswith("case_complete_"): return {"completed": True}
        if state.point == "receive_error": raise state.boundary_error
        if phase.startswith("negative_ready"): state.blocked = True
        return {"approved": state.point != "ack"}
    instance.transport = SimpleNamespace(publish=publish, wait=receive)
    instance.rendezvous = SimpleNamespace(seal=lambda phase, value: value, open=lambda phase, value: value)
    original = instance.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3:
            if state.point == "final_observation_error": raise state.boundary_error
            if state.point == "path_missing": return None
            if state.point == "traffic": value["application"] = dict.fromkeys(evidence.APPLICATION, 0)
            if state.point == "selection": value["pair"] = None
        return value
    instance.observe = observe
    observer = instance._negative_diagnostics
    if observer_mode in {"observe", "observe_after", "reset", "projection"}:
        name = {"observe": "observe", "observe_after": "observe", "reset": "reset", "projection": "failure_observation"}[observer_mode]
        original_method = getattr(observer, name)
        def broken(*args, **kwargs):
            if observer_mode == "observe_after": original_method(*args, **kwargs)
            raise ValueError("PRIVATE_OBSERVER_PAYLOAD")
        monkeypatch.setattr(observer, name, broken)
    elif observer_mode == "malformed":
        original_method = observer.failure_observation
        monkeypatch.setattr(observer, "failure_observation", lambda error: {**original_method(error), "socket": "PRIVATE_SOCKET"})
    elif observer_mode == "forged_projection":
        monkeypatch.setattr(observer, "failure_observation", lambda error: {"scenario": scenario, "stage": "blocked_receipt", "reason": "receipt_while_blocked"})
    return state


def run_negative_control_report(tmp_path, monkeypatch, capsys, sample, **options):
    import connection_ci
    state = negative_control_case(monkeypatch, sample, **options)
    peer = state.controller.peer
    peer.process = SimpleNamespace(pid=17)
    def stop(**kwargs): peer.process = None
    peer.stop = stop
    def execute():
        try: state.controller.path_case(state.scenario, "windows")
        except Exception as error:
            state.primary_error = error
            if state.observer_mode == "foreign_escape": error = ValueError("PRIVATE_FOREIGN_EXCEPTION")
            state.escaping_error = error
            if error is not state.primary_error: raise error
            raise
    state.controller.run = execute
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: state.controller)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *args, **kwargs: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "negative.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", state.controller.role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state,
                           output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("point,stage,reason", [("receipt", "blocked_receipt", "receipt_while_blocked"),
    ("zero_drop", "dropped_count", "no_dropped_packets"), ("path_missing", "final_observation", "path_missing")])
def test_negative_report_classifies_actual_assertion_without_losing_original_failure(tmp_path, monkeypatch, capsys, sample, point, stage, reason):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point=point)
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["phase"] == "turn_tcp_kernel_block_negative_control"
    assert run.record.get("negative_control") == {"scenario": "turn_tcp", "stage": stage, "reason": reason}
    assert "PRIVATE" not in run.output and not run.state.requests


@pytest.mark.parametrize("point,stage,reason", [
    ("enqueue", "blocked_enqueue", "not_accepted"), ("enqueue_error", "blocked_enqueue", None),
    ("block_error", "kernel_block", None), ("publish_error", "ready_publish", None),
    ("receive_error", "checked_receive", None), ("ack", "checked_receive", "not_acknowledged"),
    ("receipt_error", "blocked_receipt", None), ("unblock_error", "kernel_unblock", None),
    ("restored_error", "restored_delivery", None), ("records_error", "recovered_inbound", None),
    ("duplicate", "recovered_records", "record_count"),
    ("final_observation_error", "final_observation", None), ("traffic", "final_traffic", None),
    ("selection", "final_evidence", None),
])
def test_negative_report_identifies_actual_stage_without_inventing_reason(tmp_path, monkeypatch, capsys, sample, point, stage, reason):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point=point)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if reason is not None: expected["reason"] = reason
    assert run.code == 1 and run.record["negative_control"] == expected
    assert run.state.controller.failure_negative_control(run.state.escaping_error) == {"negative_control": expected}
    if point.endswith("error"): assert run.state.escaping_error is run.state.boundary_error
    assert "PRIVATE" not in run.output and not run.state.requests


@pytest.mark.parametrize("point,stage,reason", [("receive_error", "ready_receive", None),
    ("ack", "ready_receive", "not_acknowledged"), ("publish_error", "checked_publish", None)])
def test_negative_windows_source_branches_use_same_safe_schema(tmp_path, monkeypatch, capsys, sample, point, stage, reason):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, role="windows", point=point)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if reason is not None: expected["reason"] = reason
    assert run.code == 1 and run.record["negative_control"] == expected
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("point", ["receipt", "path_missing", "traffic"])
def test_fault_cleanup_replacement_is_the_exact_reported_error_not_primary(tmp_path, monkeypatch, capsys, sample, point):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point=point, cleanup_error=True)
    assert run.state.escaping_error is run.state.cleanup_exception
    assert run.record["failure_type"] == "RuntimeError"
    assert run.record["negative_control"] == {"scenario": "turn_tcp", "stage": "fault_cleanup"}
    assert run.state.controller.failure_negative_control(run.state.boundary_error) == {}
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("mode", ["observe", "observe_after", "reset", "projection", "malformed", "forged_projection"])
def test_negative_observer_failure_or_forgery_omits_metadata_without_outcome_change(tmp_path, monkeypatch, capsys, sample, mode):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point="zero_drop", observer_mode=mode)
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["phase"] == "turn_tcp_kernel_block_negative_control"
    assert str(run.state.escaping_error) == "Negative control has no actual dropped packets"
    assert "negative_control" not in run.record and "PRIVATE" not in run.output
    assert run.state.block_reads == 20 and not run.state.requests


def test_negative_foreign_escaping_error_cannot_inherit_primary_stage(tmp_path, monkeypatch, capsys, sample):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, observer_mode="foreign_escape")
    assert run.state.primary_error is not run.state.escaping_error
    assert run.code == 1 and run.record["failure_type"] == "ValueError" and "negative_control" not in run.record
    assert run.state.controller.failure_negative_control(run.state.escaping_error) == {}
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("mode,stage,reason,kind", [
    ("actual_kernel_install", "kernel_block_install", None, "CalledProcessError"),
    ("actual_kernel_delete", "fault_cleanup", "cleanup_incomplete", "RuntimeError"),
])
def test_actual_kernel_error_reaches_main_with_exact_escaping_identity_and_safe_branch(tmp_path, monkeypatch, capsys, sample, mode, stage, reason, kind):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point="success", observer_mode=mode)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if reason is not None: expected["reason"] = reason
    assert run.code == 1 and run.record["failure_type"] == kind and run.record["negative_control"] == expected
    if mode == "actual_kernel_install": assert run.state.escaping_error is run.state.boundary_error
    else: assert run.state.controller.failure_negative_control(run.state.boundary_error) == {}
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("poison", [None, [], (), (ValueError("PRIVATE_FOREIGN"), {}),
    {"scenario": "turn_tcp", "stage": "blocked_receipt"}])
def test_negative_malformed_or_foreign_identity_record_fails_closed(monkeypatch, sample, poison):
    state = negative_control_case(monkeypatch, sample)
    with pytest.raises(ValueError) as failure: state.controller.path_case("turn_tcp", "windows")
    state.controller._negative_diagnostics._failure = poison
    assert state.controller.failure_negative_control(failure.value) == {}


@pytest.mark.parametrize("scenario", ["turn_tcp", "turn_tls", "impaired"])
def test_negative_diagnostics_preserve_actual_window_waits_calls_and_success_clear(monkeypatch, sample, scenario):
    state = negative_control_case(monkeypatch, sample, scenario=scenario, point="block_error")
    with pytest.raises(ValueError) as failure: state.controller.path_case(scenario, "windows")
    assert failure.value is state.boundary_error
    state.point = "success"
    # The impaired RTT requirement is an existing positive gate, not a diagnostic substitute.
    if scenario == "impaired": sample[0]["pair"]["rtt_ms"] = 10
    waits = []
    original_wait = state.controller.wait
    def wait(action, **kwargs):
        waits.append(kwargs)
        return original_wait(action, **kwargs)
    monkeypatch.setattr(state.controller, "wait", wait)
    state.controller.path_case(scenario, "windows")
    assert state.controller.failure_negative_control(failure.value) == {}
    assert state.controller.failure_negative_control(ValueError("PRIVATE_FOREIGN")) == {}
    assert state.block_reads == 20 and state.now >= 2
    assert [event for event in state.events if isinstance(event, tuple) and event == ("sleep", 0.1)] == [("sleep", 0.1)] * 20
    assert sum(item.get("timeout") == 90 for item in waits) == 2
    assert state.controller.deadline == 3000 and state.controller.cases[-1]["owner_retirement_acknowledged"] is True
    assert "negative_control" not in state.controller.cases[-1]


@pytest.mark.parametrize("point,reason", [("impairment_error", None), ("success", "rtt_unavailable")])
def test_impaired_final_evidence_branch_remains_distinct_from_kernel_negative(tmp_path, monkeypatch, capsys, sample, point, reason):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point=point, scenario="impaired")
    expected = {"scenario": "impaired", "stage": "final_evidence"}
    if reason is not None: expected["reason"] = reason
    assert run.code == 1 and run.record["negative_control"] == expected
    assert "PRIVATE" not in run.output


def run_carrier_failure_report(tmp_path, monkeypatch, capsys, sample, *, remaining=0.5, fault="", polls=None, role="windows"):
    """Actual main plus case retirement, inert binding and earlier path/receipt effects."""
    import connection_ci
    state = retirement_case(monkeypatch, sample, remaining=remaining, role=role,
        polls=polls if polls is not None else [carrier_inventory(state="pending")])
    peer = state.controller.peer
    peer.process = SimpleNamespace(pid=17)
    def stop(**kwargs):
        assert kwargs == {"crash": True}
        state.events.append("host_cleanup")
        peer.process = None
        if fault == "cleanup": raise ValueError("PRIVATE_CLEANUP")
    peer.stop = stop
    if fault in {"prepare_error", "completion_publish", "completion_receive", "commit_error", "poll_error"}:
        state.request_error = controller.PeerFailure("forbidden")
        state.request_error_action = "commit" if fault == "commit_error" else ("prepare" if fault == "prepare_error" else "never")
        if fault.startswith("completion_"): state.completion_failure = fault.split("_")[1]
        if fault == "poll_error":
            def inventory(**kwargs): raise state.request_error
            peer.inventory = inventory
    def execute():
        try: state.controller.path_case("direct", "windows")
        except Exception as error:
            state.original_error = error
            if fault == "foreign": raise controller.PeerFailure("forbidden")
            if fault == "malformed": state.controller._retirement_failure[1]["request_id"] = "PRIVATE_REQUEST"
            raise
    state.controller.run = execute
    if fault == "observer":
        def broken(*args): raise ValueError("PRIVATE_OBSERVER")
        monkeypatch.setattr(state.controller, "_retirement_poll_observation", broken)
    if fault == "projection":
        def broken(value): raise ValueError("PRIVATE_PROJECTION")
        monkeypatch.setattr(controller, "retirement_failure_snapshot", broken)
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: state.controller)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *args, **kwargs: None, close=lambda: None))
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "carrier.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state,
                           output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("fault,stage,actions", [("prepare_error", "prepare", ["prepare"]),
    ("completion_publish", "completion_publish", ["prepare"]),
    ("completion_receive", "completion_receive", ["prepare"]),
    ("commit_error", "commit", ["prepare", "commit"]), ("poll_error", "poll", ["prepare", "commit"])])
def test_prepared_sequence_failure_keeps_exact_error_and_tears_down_owned_host(tmp_path, monkeypatch, capsys, sample, role, fault, stage, actions):
    run = run_carrier_failure_report(tmp_path, monkeypatch, capsys, sample, fault=fault, role=role)
    assert run.code == 1 and run.state.original_error is run.state.request_error
    assert run.state.actions == actions and run.record["error_code"] == "forbidden"
    context = run.record["carrier_retirement_failure"]
    assert context == {"scenario": "direct", "initiator": "windows", "stage": stage, "polls": int(stage == "poll"),
                       "polls_capped": False, "last_observation": None}
    assert "host_cleanup" in run.state.events and "execution" not in run.record
    assert "PRIVATE" not in run.output and "request_id" not in run.output


@pytest.mark.parametrize("remaining,polls", [(0, 0), (0.5, 2)])
def test_retirement_report_retains_only_last_valid_existing_poll(tmp_path, monkeypatch, capsys, sample, remaining, polls):
    run = run_carrier_failure_report(tmp_path, monkeypatch, capsys, sample, remaining=remaining)
    assert run.code == 1 and run.record["error_code"] == "scenario_deadline"
    context = run.record["carrier_retirement_failure"]
    assert context == {"scenario": "direct", "initiator": "windows", "stage": "poll", "polls": polls,
        "polls_capped": False, "last_observation": ({"state": "pending", "resource_count": 0,
            "resources_capped": False, "counts": dict.fromkeys(controller.RETIREMENT_COUNTS, 0)} if polls else None)}
    assert run.state.controller.failure_retirement(run.state.original_error) == {"carrier_retirement_failure": context}
    assert len(run.state.requests) == 1 and len(run.state.inventories) == polls
    assert "PRIVATE" not in run.output and "request_id" not in run.output
    assert all(value not in run.output for value in run.state.requests[0].values())


@pytest.mark.parametrize("fault", ["foreign", "observer", "projection", "malformed", "cleanup"])
def test_retirement_failure_context_is_best_effort_same_error_only(tmp_path, monkeypatch, capsys, sample, fault):
    run = run_carrier_failure_report(tmp_path, monkeypatch, capsys, sample, fault=fault)
    assert run.code == 1 and run.record["failure_type"] == "PeerFailure"
    assert run.record["phase"] == "direct_native_lease_retirement"
    assert run.record["error_code"] == ("forbidden" if fault == "foreign" else "scenario_deadline")
    assert ("carrier_retirement_failure" in run.record) is (fault == "cleanup")
    assert run.record.get("cleanup_failed", False) is (fault == "cleanup")
    assert "host_cleanup" in run.state.events and len(run.state.inventories) == 2
    assert "PRIVATE" not in run.output


def test_retirement_diagnostics_clear_after_next_case_success(monkeypatch, sample):
    error = controller.PeerFailure("forbidden")
    state = retirement_case(monkeypatch, sample, request_error=error)
    with pytest.raises(controller.PeerFailure): state.controller.path_case("direct", "windows")
    context = state.controller.failure_retirement(error)["carrier_retirement_failure"]
    assert context == {"scenario": "direct", "initiator": "windows", "stage": "prepare", "polls": 0,
                       "polls_capped": False, "last_observation": None}
    assert state.controller.failure_retirement(controller.PeerFailure("forbidden")) == {}
    state.request_error = None
    state.controller.path_case("direct", "android")
    assert state.controller.failure_retirement(error) == {} and state.controller._retirement_context is None


def test_retirement_failure_resource_observation_is_capped_without_raw_rows(tmp_path, monkeypatch, capsys, sample):
    inventory = carrier_inventory(active=1)
    inventory["resources"] = [{"logical_session": "PRIVATE_OTHER", "physical_resource": "PRIVATE_RESOURCE"}] * 20
    run = run_carrier_failure_report(tmp_path, monkeypatch, capsys, sample, polls=[inventory])
    last = run.record["carrier_retirement_failure"]["last_observation"]
    assert last["resource_count"] == 16 and last["resources_capped"] is True
    assert last["state"] == "acknowledged" and last["counts"]["active_count"] == 1
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("field,value", [("scenario", "PRIVATE_CASE"), ("initiator", []), ("stage", "cleanup"),
                                       ("polls", True), ("polls", 129), ("polls_capped", "true")])
def test_unknown_or_malformed_retirement_failure_snapshot_is_omitted(monkeypatch, sample, field, value):
    error = controller.PeerFailure("forbidden")
    state = retirement_case(monkeypatch, sample, request_error=error)
    with pytest.raises(controller.PeerFailure): state.controller.path_case("direct", "windows")
    state.controller._retirement_failure[1][field] = value
    assert state.controller.failure_retirement(error) == {}


@pytest.mark.parametrize("fault", ["state", "resource_bool", "resource_limit", "resource_cap", "count_bool", "count_limit", "raw_id", "no_poll"])
def test_retirement_failure_last_observation_rejects_poison_and_unbounded_values(monkeypatch, sample, fault):
    state = retirement_case(monkeypatch, sample, polls=[carrier_inventory(state="pending")], remaining=0.5)
    with pytest.raises(controller.PeerFailure) as caught: state.controller.path_case("direct", "windows")
    snapshot = state.controller._retirement_failure[1]
    last = snapshot["last_observation"]
    if fault == "state": last["state"] = "PRIVATE_STATE"
    elif fault == "resource_bool": last["resource_count"] = True
    elif fault == "resource_limit": last["resource_count"] = 17
    elif fault == "resource_cap": last["resources_capped"] = True
    elif fault == "count_bool": last["counts"]["active_count"] = True
    elif fault == "count_limit": last["counts"]["active_count"] = 17
    elif fault == "raw_id": last["resource"] = "PRIVATE_RESOURCE"
    else: snapshot["polls"] = 0
    assert state.controller.failure_retirement(caught.value) == {}


@pytest.fixture
def path_observer(monkeypatch, sample):
    """Actual observe/wait/Samples; only private peer calls and time are scripted."""
    value, inventory = sample
    state = SimpleNamespace(now=10.0, events=[], sleeps=[], on_sleep=None, error=None, value=value,
        inventory=inventory, sequence=0, challenges=[], echo_request=True)
    state.inventory["resources"][0]["owner_state"] = "authorized"
    def discover():
        state.events.append("inventory")
        return copy.deepcopy(state.inventory)
    def path(logical, physical, sample_request):
        state.events.append(("path", logical, physical))
        state.challenges.append(sample_request)
        if state.error is not None: raise state.error
        state.sequence += 1
        result = copy.deepcopy(state.value)
        result.update(sample_sequence=state.sequence, sampled_at_ms=int((100 + state.now - 10) * 1000))
        if state.echo_request: result["sample_request"] = sample_request
        return result
    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        if state.on_sleep is not None: state.on_sleep()
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    instance = controller.Controller("android", SimpleNamespace(inventory=discover, path=path), None, None, {})
    instance.samples = evidence.Samples(monotonic=lambda: state.now)
    state.controller = instance
    return state


class PendingState(str):
    pass


OWNER_STATE_VALUES = [None, False, True, 0, 1, [], {}, "unknown", "PENDING_ADOPTION",
    "unadopted", "unavailable", "authorized", PendingState("pending_adoption")]


@pytest.mark.parametrize("logical", [None, "logical"])
def test_unique_pending_adoption_waits_then_samples_same_physical_resource(path_observer, logical):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    def adopt(): state.inventory["resources"][0]["owner_state"] = "authorized"
    state.on_sleep = adopt
    result = state.controller.wait(lambda: state.controller.observe(logical, ready=True, scenario="turn_udp"), timeout=120)
    assert result["logical_session"] == "logical" and result["resource"] == "physical"
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.sequence == 1
    assert state.controller.samples.previous == {("service", "physical", "a" * 32): 1}


@pytest.mark.parametrize("owner_state", ["missing", *OWNER_STATE_VALUES, "pending_adoption"])
@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("denial", ["contact", "native"])
def test_only_strict_pending_hint_defers_other_metadata_preserves_exact_path_error(path_observer, owner_state, ready, denial):
    from mesh_chat.errors import NativeUnavailable
    state = path_observer
    row = state.inventory["resources"][0]
    if owner_state == "missing": row.pop("owner_state")
    else: row["owner_state"] = owner_state
    state.error = controller.PeerFailure("contact_not_approved") if denial == "contact" else NativeUnavailable("private sample unavailable")
    if ready and type(owner_state) is str and owner_state == "pending_adoption":
        assert state.controller.observe("logical", ready=ready) is None
        assert state.events == ["inventory"]
    else:
        with pytest.raises(type(state.error)) as failure:
            state.controller.observe("logical", ready=ready)
        assert failure.value is state.error
        assert state.events == ["inventory", ("path", "logical", "physical")]
    assert state.sleeps == [] and state.controller.samples.previous == {}


@pytest.mark.parametrize("owner_state", ["missing", *OWNER_STATE_VALUES])
def test_nonpending_metadata_keeps_original_successful_sampling(path_observer, owner_state):
    state = path_observer
    if owner_state == "missing": state.inventory["resources"][0].pop("owner_state")
    else: state.inventory["resources"][0]["owner_state"] = owner_state
    result = state.controller.observe("logical", scenario="turn_udp")
    assert result["resource"] == "physical"
    assert state.events == ["inventory", ("path", "logical", "physical")] and state.sleeps == []


def test_ready_false_still_samples_pending_unadopted_path(path_observer):
    state = path_observer
    state.inventory["resources"][0].update(adopted=False, owner_state="pending_adoption")
    state.value.update(adopted=False, attached=False, messaging_ready=False)
    assert state.controller.observe("logical", ready=False)["adopted"] is False
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("requested,pending_logical,expected", [
    ("logical", "logical", ["inventory"]),
    ("logical", "other", ["inventory", ("path", "logical", "physical")]),
    ("absent", "logical", ["inventory"]),
])
def test_pending_hint_is_considered_only_after_exact_logical_filter(path_observer, requested, pending_logical, expected):
    state = path_observer
    state.inventory["resources"].append(dict(logical_session="other", physical_resource="other-physical", adopted=True, owner_state="authorized"))
    next(row for row in state.inventory["resources"] if row["logical_session"] == pending_logical)["owner_state"] = "pending_adoption"
    result = state.controller.observe(requested)
    assert (result is not None) == (requested == "logical" and pending_logical == "other")
    assert state.events == expected


@pytest.mark.parametrize("requested,second_logical", [(None, "other"), ("logical", "logical")])
def test_ambiguous_matching_pending_row_keeps_original_path_and_denial(path_observer, requested, second_logical):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    state.inventory["resources"].append(dict(logical_session=second_logical, physical_resource="other-physical", adopted=True, owner_state="authorized"))
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.observe(requested)
    assert failure.value is state.error
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_pending_adoption_uses_original_poll_and_deadline_without_path_rpc(path_observer, remaining, polls):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    if remaining < 120: state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.wait(lambda: state.controller.observe("logical"), timeout=120)
    assert failure.value.code == "scenario_deadline"
    assert state.now == 10 + remaining and state.sleeps == [0.25] * polls
    assert state.events == ["inventory"] * polls and state.controller.samples.previous == {}


def test_pending_then_revoked_is_not_cached_or_swallowed(path_observer):
    state = path_observer
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    def revoke():
        state.inventory["resources"][0]["owner_state"] = "unavailable"
        state.error = controller.PeerFailure("contact_not_approved")
    state.on_sleep = revoke
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.wait(lambda: state.controller.observe("logical"), timeout=120)
    assert failure.value is state.error
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.controller.samples.previous == {}


@pytest.mark.parametrize("field", ["adopted", "attached", "messaging_ready", "status"])
def test_authorized_inventory_does_not_replace_actual_selected_path_readiness(path_observer, field):
    state = path_observer
    state.value[field] = "unsupported" if field == "status" else False
    assert state.controller.observe("logical", ready=True) is None
    assert state.events == ["inventory", ("path", "logical", "physical")]
    assert state.controller.samples.previous == {} and state.sleeps == []


def test_empty_inventory_still_returns_no_sample(path_observer):
    state = path_observer
    state.inventory["resources"] = []
    assert state.controller.observe() is None
    assert state.events == ["inventory"] and state.controller.samples.previous == {}


def test_controller_draws_exactly_one_fresh_sixteen_byte_request_per_path_rpc(path_observer, monkeypatch):
    state, draws = path_observer, []
    def random_bytes(size):
        draws.append(size)
        return bytes([len(draws)]) * size
    monkeypatch.setattr(controller.os, "urandom", random_bytes)
    state.controller.observe("logical")
    state.controller.observe("logical")
    assert draws == [16, 16] and state.challenges == ["01" * 16, "02" * 16]
    assert state.events == ["inventory", ("path", "logical", "physical")] * 2
    assert state.controller.samples.previous == {("service", "physical", "a" * 32): 2}
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    assert state.controller.observe("logical") is None and draws == [16, 16]
    state.inventory["resources"] = []
    assert state.controller.observe() is None and draws == [16, 16]


@pytest.mark.parametrize("unready", [None, "adopted", "status"])
def test_old_or_missing_invocation_echo_fails_even_before_readiness_filter(path_observer, unready):
    state = path_observer
    state.echo_request = False
    state.value.pop("sample_request")
    if unready is not None: state.value[unready] = "not_selected" if unready == "status" else False
    with pytest.raises(ValueError) as failure: state.controller.observe("logical")
    assert state.controller.failure_observation(failure.value) == {
        "failure_substage": "path_validation", "sample_rejection_reason": "sample_request"}
    assert state.controller.samples.previous == {} and len(state.challenges) == 1


def run_approval_report(tmp_path, monkeypatch, capsys, path_observer, role, fault, *, transport=None):
    """Actual main/pair/path_case/observe/Samples; all product/host boundaries doubled."""
    import connection_ci
    state = path_observer
    state.decided = state.cancelled = False
    state.approval_error = ValueError("PRIVATE_PAYLOAD_ERROR")
    peer = state.controller.peer
    inventory, path = peer.inventory, peer.path
    # Direct native DTO double for post-pair selected-path assertions.
    for endpoint in ("local", "remote"): state.value["pair"][endpoint]["type"] = "host"
    state.value["pair"]["relay_protocol"] = "not_applicable"
    contact = {"id": "PRIVATE_CONTACT", "core_handle": "PRIVATE_PEER", "trust": "approved"}
    def core(operation, params, key=None):
        if operation == "application.snapshot":
            state.events.append("snapshot")
            if (not state.decided and fault == "pending_contact_wait") or (state.decided and fault == "approved_contact_wait"):
                raise state.approval_error
            if state.decided: return {"contacts": [contact]}
            if role == "windows": return {"contacts": [{**contact, "trust": "pending_request"}]}
            return {"contact_invitations": [{"id": "PRIVATE_INVITATION", "state": "pending"}],
                "contacts": [contact] if fault == "implicit_contact_guard" else []}
        if operation in {"peer.approve", "contact.invitation"}:
            state.events.append("decision")
            if fault == "contact_decision": raise state.approval_error
            state.decided = True
            return {}
        assert operation == "native.command" and params["command"] == "reconnect_consent_set"
        state.events.append("consent")
        if fault == "reconnect_consent": raise state.approval_error
        return {}
    def discover():
        value = inventory()
        if fault == "path_inventory": raise state.approval_error
        pending = fault == "approval_ready_observation" or (fault == "adopted_observation" and state.challenges) or (
            fault == "post_cancel_observation" and state.cancelled)
        if pending: value["resources"][0]["owner_state"] = "pending_adoption"
        return value
    def sample(logical, physical, sample_request):
        if fault == "path_read":
            state.events.append(("path", logical, physical))
            state.challenges.append(sample_request)
            raise state.approval_error
        value = path(logical, physical, sample_request)
        if fault == "sample_request": value["sample_request"] = "PRIVATE_CACHED_REQUEST"
        elif fault == "sample_timestamp": value["sampled_at_ms"] = -1
        elif fault == "selected_transport": value["dtls_state"] = "closed"
        elif fault == "cleanup_substitution": value["dtls_state"] = "closed"
        elif fault == "application_counters": value["application"]["received_bytes"] = True
        elif fault == "selected_pair_identity": value["pair"]["token"] = "PRIVATE_PAIR"
        return value
    def pairing_status(operation):
        state.events.append("status")
        return {"operation_id": operation, "state": "retired" if fault == "transferred_status_wait" else "transferred",
            "retirement": retirement_example()}
    def cancel(operation):
        state.events.append("cancel")
        state.cancelled = True
        if fault == "transferred_cancel": raise state.approval_error
        if fault == "carrier_identity_check":
            state.inventory["resources"][0]["physical_resource"] = "PRIVATE_REPLACEMENT"
            state.value["resource"] = "PRIVATE_REPLACEMENT"
        return {"operation_id": "PRIVATE_FOREIGN" if fault == "transferred_cancel_check" else operation, "state": "transferred"}
    peer.core, peer.inventory, peer.path = core, discover, sample
    peer.pairing_status, peer.pairing_cancel, peer.process = pairing_status, cancel, None
    def publish(*args):
        state.events.append("publish")
        if fault == "publish_failure": raise state.approval_error
    def receive(*args, **kwargs):
        state.events.append("receive")
        if fault == "receive_failure": raise state.approval_error
        return {"approved": fault != "approval_acknowledgment"}
    def execute(instance):
        instance.profile, instance.pairing = "PRIVATE_PROFILE", "PRIVATE_PAIRING"
        instance.samples = state.controller.samples
        state.controller = instance
        if fault == "cleanup_substitution":
            consume = instance.samples.consume
            def replacing_cleanup(*args, **kwargs):
                try: return consume(*args, **kwargs)
                finally: raise controller.PeerFailure("invalid_request")
            instance.samples.consume = replacing_cleanup
        if fault in {"forged", "unknown_stage", "unknown_reason"}:
            error = state.approval_error
            error.failure_substage = "path_validation"
            error.sample_rejection_reason = "sample_request"
            if fault == "unknown_stage": instance._substage_failure = error, "PRIVATE_STAGE"
            if fault == "unknown_reason":
                instance._substage_failure = error, "path_validation"
                instance.samples._rejection = error, "PRIVATE_REASON"
            raise error
        if fault in {"stale_then_foreign", "stale_then_success", "stale_then_same"}:
            state.echo_request = False
            with pytest.raises(ValueError) as caught: instance.observe("logical")
            state.echo_request = True
            if fault != "stale_then_foreign": instance.observe("logical")
            if fault == "stale_then_success": return {}
            raise caught.value if fault == "stale_then_same" else state.approval_error
        if fault in {"transferred_status_wait", "adopted_observation", "transferred_cancel", "transferred_cancel_check", "post_cancel_observation", "carrier_identity_check"}:
            instance.negotiate = lambda *_: ("logical", None)
            return instance.path_case("direct", "windows")
        instance.pair("logical", "windows")
        return {}  # Incomplete synthetic execution, never native evidence.
    monkeypatch.setattr(controller.Controller, "run", execute)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_, **__: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: transport if transport is not None else
        SimpleNamespace(publish=publish, wait=receive, close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(seal=lambda _, value: value, open=lambda _, value: value, close=lambda: None))
    output = tmp_path / "approval.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state,
        output=output.read_text() + captured.out + captured.err)


def test_receive_http_failure_reports_only_safe_origin_and_status(tmp_path, monkeypatch, capsys, path_observer):
    import native_interop_artifacts as artifacts
    from test_ui_core_boundary_interop_artifacts import CONTEXT, environment
    transport = artifacts.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=environment("windows"))
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(timeout)
            raise artifacts.urllib.error.HTTPError(request.full_url, 403, "PRIVATE_HTTP_TEXT",
                {"PRIVATE_HEADER": "PRIVATE_TOKEN"}, None)
    monkeypatch.setattr(artifacts.urllib.request, "build_opener", lambda *_: Opener())
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", "", transport=transport)
    assert run.code == 1 and run.record["failure_type"] == "RendezvousUnavailable"
    assert run.record["phase"] == "explicit_contact_approval"
    assert run.record["failure_site"] == "rendezvous_receive" and run.record["failure_substage"] == "approval_acknowledgment"
    assert run.record.get("rendezvous_stage") == "inventory_request"
    assert run.record.get("rendezvous_reason") == "http_rejected"
    assert run.record.get("rendezvous_http_status") == 403
    assert calls == [10] and "PRIVATE_" not in run.output


@pytest.mark.parametrize("fault,stage,reason,count", RECEIVE_ORIGINS)
def test_actual_receive_report_validates_every_transport_origin(tmp_path, monkeypatch, capsys, path_observer, fault, stage, reason, count):
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, fault, role="android", phase="approved")
    observed_errors, created_errors = [], []
    observation, unavailable = state.transport.failure_observation, state.transport._unavailable
    def observe(error):
        observed_errors.append(error)
        return observation(error)
    def create(*args):
        error = unavailable(*args)
        created_errors.append(error)
        return error
    monkeypatch.setattr(state.transport, "failure_observation", observe)
    monkeypatch.setattr(state.transport, "_unavailable", create)
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", "", transport=state.transport)
    assert run.code == 1 and run.record["failure_type"] == "RendezvousUnavailable"
    assert run.record["phase"] == "explicit_contact_approval"
    assert run.record["failure_site"] == "rendezvous_receive" and run.record["failure_substage"] == "approval_acknowledgment"
    expected = {"rendezvous_stage": stage, "rendezvous_reason": reason}
    if fault.endswith("http") and fault != "read_http": expected["rendezvous_http_status"] = 403
    assert {key: value for key, value in run.record.items() if key.startswith("rendezvous_")} == expected
    assert set(run.record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "phase",
        "failure_type", "failure_site", "failure_substage"} | set(expected)
    assert len(created_errors) == 1 and observed_errors == created_errors
    assert len(state.calls) == count and "PRIVATE" not in run.output
    assert state.transport._token is None  # Existing main cleanup was not skipped.


@pytest.mark.parametrize("fault", ["throw", "none", "extra", "unknown", "wrong_status", "object"])
def test_faulty_receive_observer_cannot_replace_primary_or_skip_cleanup(tmp_path, monkeypatch, capsys, path_observer, fault):
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, role="android", phase="approved")
    def broken(error):
        if fault == "throw": raise RuntimeError("PRIVATE_OBSERVER_ERROR")
        if fault == "none": return None
        if fault == "object": return SimpleNamespace(rendezvous_stage="inventory_request", rendezvous_reason="http_rejected")
        value = {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected"}
        if fault == "extra": value["url"] = "PRIVATE_URL"
        if fault == "unknown": value["rendezvous_reason"] = "PRIVATE_REASON"
        if fault == "wrong_status": value["rendezvous_http_status"] = True
        return value
    monkeypatch.setattr(state.transport, "failure_observation", broken)
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", "", transport=state.transport)
    assert run.code == 1 and run.record["failure_type"] == "RendezvousUnavailable"
    assert run.record["phase"] == "explicit_contact_approval" and run.record["failure_substage"] == "approval_acknowledgment"
    assert not any(key.startswith("rendezvous_") for key in run.record)
    assert state.transport._token is None and len(state.calls) == 1 and "PRIVATE" not in run.output


@pytest.mark.parametrize("activity", ["replace", "replace_same_type", "wait_success", "request_success", "publish", "close"])
def test_receive_metadata_omits_replaced_or_stale_same_exception(tmp_path, monkeypatch, capsys, path_observer, activity):
    import native_interop_artifacts as artifacts
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, role="android", phase="approved")
    original_wait = state.transport.wait
    def intercepted(*args, **kwargs):
        try: return original_wait(*args, **kwargs)
        except artifacts.RendezvousUnavailable as original:
            if activity in {"replace", "replace_same_type"}:
                error = artifacts.RendezvousUnavailable("PRIVATE_REPLACED") if activity == "replace_same_type" else ValueError("PRIVATE_CLEANUP_ERROR")
                error.rendezvous_stage, error.rendezvous_reason, error.rendezvous_http_status = "inventory_request", "http_rejected", 403
                raise error
            state.fault = "success"
            if activity == "wait_success": original_wait(*args, **kwargs)
            elif activity == "request_success": state.transport._request("/artifacts?per_page=100")
            elif activity == "publish":
                with pytest.raises(ValueError): state.transport.publish("key", {"PRIVATE_BODY": "PRIVATE_PAYLOAD"})
            else: state.transport.close()
            raise original
    monkeypatch.setattr(state.transport, "wait", intercepted)
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", "", transport=state.transport)
    assert run.code == 1 and run.record["phase"] == "explicit_contact_approval"
    assert run.record["failure_type"] == ("ValueError" if activity == "replace" else "RendezvousUnavailable")
    assert run.record["failure_site"] == "rendezvous_receive" and run.record["failure_substage"] == "approval_acknowledgment"
    assert not any(key.startswith("rendezvous_") for key in run.record)
    assert state.transport._token is None and "PRIVATE" not in run.output


def test_forged_receive_exception_attributes_supply_no_provenance(tmp_path, monkeypatch, capsys, path_observer):
    import native_interop_artifacts as artifacts
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, role="android", phase="approved")
    error = artifacts.RendezvousUnavailable("PRIVATE_FOREIGN")
    error.rendezvous_stage, error.rendezvous_reason, error.rendezvous_http_status = "inventory_request", "http_rejected", 403
    class Opener:
        def open(self, *args, **kwargs): raise error
    monkeypatch.setattr(artifacts.urllib.request, "build_opener", lambda *_: Opener())
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", "", transport=state.transport)
    assert run.record["failure_type"] == "RendezvousUnavailable" and run.record["failure_site"] == "rendezvous_receive"
    assert not any(key.startswith("rendezvous_") for key in run.record) and "PRIVATE" not in run.output


APPROVAL_CASES = [
    ("windows", "pending_contact_wait", "pending_contact_wait", None),
    ("android", "implicit_contact_guard", "implicit_contact_guard", None),
    ("windows", "contact_decision", "contact_decision", None),
    ("android", "approved_contact_wait", "approved_contact_wait", None),
    ("windows", "reconnect_consent", "reconnect_consent", None),
    ("android", "approval_ready_observation", "approval_ready_observation", None),
    ("windows", "approval_acknowledgment", "approval_acknowledgment", None),
    ("android", "publish_failure", "approval_acknowledgment", "rendezvous_publish"),
    ("windows", "receive_failure", "approval_acknowledgment", "rendezvous_receive"),
    ("windows", "transferred_status_wait", "transferred_status_wait", "pairing_status"),
    ("android", "adopted_observation", "adopted_observation", None),
    ("windows", "transferred_cancel", "transferred_cancel", None),
    ("android", "transferred_cancel_check", "transferred_cancel_check", None),
    ("windows", "post_cancel_observation", "post_cancel_observation", None),
    ("android", "carrier_identity_check", "carrier_identity_check", None),
    ("windows", "path_inventory", "path_inventory", None),
    ("android", "path_read", "path_read", None),
]


@pytest.mark.parametrize("role,fault,stage,site", APPROVAL_CASES)
def test_actual_approval_report_retains_precise_substage_and_nested_site(tmp_path, monkeypatch, capsys, path_observer, role, fault, stage, site):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, role, fault)
    assert run.code == 1 and run.record["phase"] == "explicit_contact_approval"
    assert run.record["failure_substage"] == stage
    assert run.record.get("failure_site") == site and "sample_rejection_reason" not in run.record
    if fault == "transferred_status_wait":
        assert run.record["error_code"] == "supervisor_pairing_retired" and run.record["pairing_retirement"] == retirement_example()
    elif fault in {"approval_ready_observation", "adopted_observation", "post_cancel_observation"}:
        assert run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "scenario_deadline"
        assert run.state.sleeps == [0.25] * 480
    else: assert run.record["failure_type"] == "ValueError" and "error_code" not in run.record
    assert "PRIVATE_" not in run.output and "sample_request" not in run.record
    assert controller.FAILURE_SUBSTAGES == frozenset({case[2] for case in APPROVAL_CASES} | {"path_validation"})


@pytest.mark.parametrize("reason", ["sample_request", "sample_timestamp", "selected_transport", "application_counters", "selected_pair_identity"])
def test_actual_sample_rejection_report_contains_only_same_exception_reason(tmp_path, monkeypatch, capsys, path_observer, reason):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", reason)
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["failure_substage"] == "path_validation" and run.record["sample_rejection_reason"] == reason
    assert run.record["phase"] == "explicit_contact_approval" and "failure_site" not in run.record
    assert len(run.state.challenges) == 1 and "PRIVATE_" not in run.output
    assert run.state.challenges[0] not in run.output


@pytest.mark.parametrize("fault", ["forged", "unknown_stage", "unknown_reason", "stale_then_foreign", "stale_then_same", "stale_then_success", "success"])
def test_failure_metadata_never_attaches_to_foreign_stale_unknown_or_success(tmp_path, monkeypatch, capsys, path_observer, fault):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", fault)
    assert "sample_rejection_reason" not in run.record
    if fault == "unknown_reason": assert run.record["failure_substage"] == "path_validation"
    else: assert "failure_substage" not in run.record
    if fault in {"success", "stale_then_success"}:
        assert run.code == 0 and run.record["passed"] is True
        assert not {"failure_site", "pairing_state", "pairing_retirement", "failure_substage", "sample_rejection_reason"} & set(run.record)
        with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, "android")
    else: assert run.code == 1
    assert "PRIVATE_" not in run.output


def test_cleanup_replacement_cannot_inherit_prior_sample_rejection_reason(tmp_path, monkeypatch, capsys, path_observer):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "android", "cleanup_substitution")
    assert run.code == 1 and run.record["failure_type"] == "PeerFailure" and run.record["error_code"] == "invalid_request"
    assert run.record["failure_substage"] == "path_validation" and "sample_rejection_reason" not in run.record
    assert len(run.state.challenges) == 1 and "PRIVATE_" not in run.output


MISSING_PAIRING_STATE = object()


@pytest.fixture
def negotiating_peer(monkeypatch):
    """Actual negotiate/wait/status scopes; inert peer and rendezvous boundaries."""
    state = SimpleNamespace(now=10.0, events=[], sleeps=[], on_sleep=None, status_value="awaiting_approval",
        foreign=False, stats_error=None, stats_value={"data_channel_state": "open"},
        resources=[{"logical_session": "logical-session", "physical_resource": "physical"}])
    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
        if state.on_sleep is not None: state.on_sleep()
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep))
    def make(role):
        offer_status_read = False
        def begin(operation, pairing_role, **kwargs):
            state.operation = operation
            state.events.append("begin_" + pairing_role)
            assert kwargs["direct"] is True
            return {"operation_id": operation}
        def status(operation):
            nonlocal offer_status_read
            assert operation == state.operation
            if role == "windows" and not offer_status_read:
                offer_status_read = True
                state.events.append("offer_status")
                return {"operation_id": operation, "state": "offer_ready", "pairing_code": "offline-code"}
            state.events.append("status")
            reply = {"operation_id": "foreign-operation" if state.foreign else operation,
                "retirement": retirement_example()}
            if state.status_value is not MISSING_PAIRING_STATE: reply["state"] = copy.deepcopy(state.status_value)
            return reply
        def inventory():
            state.events.append("inventory")
            return {"resources": copy.deepcopy(state.resources)}
        def core(operation, params, key=None):
            assert key is None
            if operation == "call.settings_update":
                state.events.append("settings")
                return {}
            assert operation == "native.command" and params == {
                "command": "native_webrtc_stats", "payload": {"session_id": "logical-session"}}
            state.events.append("stats")
            if state.stats_error is not None: raise state.stats_error
            return state.stats_value
        def receive(partner, phase, *, timeout):
            assert (partner, phase, timeout) == ("windows", "offer", 180)
            state.events.append("receive")
            return {"shareable": "offline-code"}
        def publish(phase, value):
            assert (phase, value) == ("offer", {"shareable": "offline-code"})
            state.events.append("publish")
        peer = SimpleNamespace(pairing_begin=begin, pairing_status=status, inventory=inventory, core=core)
        instance = controller.Controller(role, peer, SimpleNamespace(wait=receive, publish=publish),
            SimpleNamespace(open=lambda phase, value: value, seal=lambda phase, value: value), {})
        instance.profile = "offline-profile"
        instance.default_call_settings = {}
        instance.broker_ice = {"iceServers": [{"urls": ["stun:offline.invalid"]}]}
        state.controller = instance
        state.prefix = (["settings", "begin_offer", "offer_status", "publish"] if role == "windows"
                        else ["settings", "receive", "begin_answer"])
        return state
    return make


@pytest.mark.parametrize("role", ["windows", "android"])
def test_negotiate_defers_reserved_before_inventory_and_stats_then_observes_same_resource(negotiating_peer, role):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    def ready(): state.status_value = "awaiting_approval"
    state.on_sleep = ready
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "status", "inventory", "stats"]
    assert state.resources == [{"logical_session": "logical-session", "physical_resource": "physical"}]
    assert state.sleeps == [0.25]


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("value", [MISSING_PAIRING_STATE, None, False, True, 0, 1, "unknown", "RESERVED",
    PendingState("reserved"), "offer_ready", "awaiting_approval", "transferred"])
def test_negotiate_nonreserved_or_missing_state_keeps_original_sampling(negotiating_peer, role, value):
    state = negotiating_peer(role)
    state.status_value = value
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "inventory", "stats"] and state.sleeps == []


@pytest.mark.parametrize("value", [[], {}])
def test_negotiate_unhashable_status_keeps_original_status_failure(negotiating_peer, value):
    state = negotiating_peer("android")
    state.status_value = value
    with pytest.raises(TypeError) as failure:
        state.controller.negotiate("direct", "windows")
    assert state.controller.failure_site(failure.value) == "pairing_status"
    assert state.events == [*state.prefix, "status"] and state.sleeps == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("terminal", ["retired", "retiring", "foreign"])
def test_negotiate_reserved_gate_preserves_existing_terminal_and_identity_failures(negotiating_peer, role, terminal):
    state = negotiating_peer(role)
    state.status_value = "reserved" if terminal == "foreign" else terminal
    state.foreign = terminal == "foreign"
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == ("invalid_pairing_identity" if terminal == "foreign" else "supervisor_pairing_retired")
    assert state.controller.failure_site(failure.value) == "pairing_status"
    expected = {} if terminal == "foreign" else {"pairing_state": terminal, "pairing_retirement": retirement_example()}
    assert state.controller.failure_pairing(failure.value) == expected
    assert state.events == [*state.prefix, "status"] and state.sleeps == []


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_negotiate_reserved_uses_existing_deadline_and_cadence(negotiating_peer, role, remaining, polls):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    if remaining < 120: state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == "scenario_deadline" and state.controller.failure_site(failure.value) is None
    assert state.now == 10 + remaining and state.sleeps == [0.25] * polls
    assert state.events == [*state.prefix, *(["status"] * polls)]


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("released", ["stats_error", "retired", "foreign"])
def test_negotiate_after_reserved_preserves_original_error_and_site(negotiating_peer, role, released):
    state = negotiating_peer(role)
    state.status_value = "reserved"
    error = controller.PeerFailure("invalid_request")
    def finish():
        state.status_value = "retired" if released == "retired" else "awaiting_approval"
        state.foreign = released == "foreign"
        if released == "stats_error": state.stats_error = error
    state.on_sleep = finish
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    tail = ["status", "status"]
    if released == "stats_error":
        assert failure.value is error and state.controller.failure_site(error) == "negotiate_native_stats"
        assert state.controller.failure_pairing(error) == {}
        tail += ["inventory", "stats"]
    else:
        assert failure.value.code == ("invalid_pairing_identity" if released == "foreign" else "supervisor_pairing_retired")
        assert state.controller.failure_site(failure.value) == "pairing_status"
    assert state.events == [*state.prefix, *tail] and state.sleeps == [0.25]


@pytest.mark.parametrize("role", ["windows", "android"])
def test_negotiate_created_status_still_requires_original_open_channel_stats(negotiating_peer, role):
    state = negotiating_peer(role)
    state.status_value = "offer_ready"
    state.stats_value = {"data_channel_state": "connecting"}
    def open_channel(): state.stats_value = {"data_channel_state": "open"}
    state.on_sleep = open_channel
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.events == [*state.prefix, "status", "inventory", "stats", "status", "inventory", "stats"]
    assert state.sleeps == [0.25]


def run_android_preflight_report(tmp_path, monkeypatch, capsys, *, site=None, fault=None,
                                 failure_status=1, failure_stderr=b"PRIVATE_STDERR"):
    """Actual main/start/environment; all subprocess and external services scripted."""
    import android_qualification
    import connection_ci
    script = scripted_android(monkeypatch, tmp_path, fault=site,
        failure_status=failure_status, failure_stderr=failure_stderr)
    context = {"source_commit": "a" * 40}
    events = []
    foreign = controller.PeerFailure("invalid_request")
    foreign.preflight_failure_site = "android_root"
    foreign.preflight_exit_status = 1
    foreign.preflight_root_reason = "connect_failure"
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: context)
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(android_qualification, "APKS", script.apks)
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: script.emulator)
    def services():
        events.append("services")
        if fault == "after_success": raise foreign
        return {}
    monkeypatch.setattr(controller, "outbound_services", services)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: SimpleNamespace(process=None))
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: events.append("transport_closed")))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: events.append("rendezvous_closed")))
    def execute(instance):
        events.append("controller")
        return {}  # Incomplete synthetic execution, never qualified native evidence.
    monkeypatch.setattr(controller.Controller, "run", execute)
    if fault in {"foreign", "caught_then_success", "caught_then_same", "unscoped_same"}:
        start = script.emulator.start
        def intercepted_start(apks, *, diagnostics):
            with pytest.raises(subprocess.CalledProcessError):
                start(apks, diagnostics=diagnostics)
            if fault == "foreign": raise foreign
            if fault == "unscoped_same":
                with diagnostics.scope(None): pass
                raise script.failure
            script.fault = None
            start(apks, diagnostics=diagnostics)
            if fault == "caught_then_same": raise script.failure
        monkeypatch.setattr(script.emulator, "start", intercepted_start)
    if fault == "cleanup_substitution":
        close = script.emulator.close
        def substituting_close():
            close()
            if not events:
                events.append("cleanup_substitution")
                raise foreign
        monkeypatch.setattr(script.emulator, "close", substituting_close)
    output = tmp_path / "preflight-report.json"
    output.write_text(json.dumps({"passed": True, "preflight_failure_site": "PRIVATE_STALE_SITE",
        "preflight_exit_status": 255, "preflight_root_reason": "PRIVATE_STALE_REASON", "pairing_state": "retired"}))
    monkeypatch.setattr(sys, "argv", ["native_interop_controller", "--role", "android", "--expected-source", "a" * 40,
        "--workload", "full", "--output", str(output)])
    exit_code = controller.main()
    record = json.loads(output.read_text())
    captured = capsys.readouterr()
    return SimpleNamespace(record=record, exit_code=exit_code, script=script, events=events,
        output=output.read_text() + captured.out + captured.err)


def test_root_failure_reports_only_checked_status_and_literal_reason(tmp_path, monkeypatch, capsys):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site="android_root",
        failure_stderr=b"adb: error while reading for root: PRIVATE_SUFFIX\n")
    assert run.exit_code == 1 and run.record["passed"] is False
    assert run.record["phase"] == "platform_outbound_preflight"
    assert run.record["failure_type"] == "CalledProcessError"
    assert run.record["preflight_failure_site"] == "android_root"
    assert run.record.get("preflight_exit_status") == 1
    assert run.record.get("preflight_root_reason") == "read_failure"
    assert run.script.calls == ["android_devices", "android_avd_create", "boot", "android_root", "kill"]
    assert run.events == [] and "PRIVATE_" not in run.output
    assert_android_cleaned(run.script)


@pytest.mark.parametrize("stderr,reason", [
    pytest.param(b"adb: unable to connect for root: PRIVATE_SUFFIX\n", "connect_failure", id="connect"),
    pytest.param("adb: error while reading for root: PRIVATE_SUFFIX\r\n", "read_failure", id="read-text"),
    pytest.param(b"adb: unexpected output length for root\n", "unexpected_output_length", id="length"),
    pytest.param(b"timeout expired while waiting for device\n", "wait_for_device_timeout", id="timeout"),
    pytest.param(b"PRIVATE_UNKNOWN", "unclassified", id="unknown"),
    pytest.param(b"adb: unable to connect for root: " + b"X" * 4096, "unclassified", id="oversized"),
    pytest.param(b"adb: unable to connect for root: PRIVATE\nadb: error while reading for root: PRIVATE\n",
                 "unclassified", id="conflict"),
])
def test_actual_root_report_serializes_only_fixed_stderr_family(tmp_path, monkeypatch, capsys, stderr, reason):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site="android_root",
        failure_status=255, failure_stderr=stderr)
    assert run.exit_code == 1 and run.record["passed"] is False
    assert run.record["failure_type"] == "CalledProcessError"
    assert run.record["preflight_exit_status"] == 255 and run.record["preflight_root_reason"] == reason
    assert set(run.record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "phase",
        "failure_type", "preflight_failure_site", "preflight_exit_status", "preflight_root_reason"}
    assert "PRIVATE_" not in run.output and "adb:" not in run.output
    assert run.script.calls.count("android_root") == 1 and run.events == []
    assert_android_cleaned(run.script)


@pytest.mark.parametrize("status", [-64, -1, 1, 255, 0, -65, 256, True, 1.0, "1", None])
def test_actual_root_report_preserves_fatality_for_every_status(tmp_path, monkeypatch, capsys, status):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site="android_root",
        failure_status=status, failure_stderr=b"PRIVATE_STDERR")
    assert run.exit_code == 1 and run.record["passed"] is False
    assert run.record["failure_type"] == "CalledProcessError"
    assert run.record["preflight_failure_site"] == "android_root"
    assert run.record["preflight_root_reason"] == "unclassified"
    if type(status) is int and -64 <= status <= 255 and status != 0:
        assert run.record["preflight_exit_status"] == status
    else:
        assert "preflight_exit_status" not in run.record
    assert "PRIVATE_" not in run.output and run.script.calls.count("android_root") == 1
    assert_android_cleaned(run.script)


@pytest.mark.parametrize("site", (*ANDROID_START_SITES, *ANDROID_ENVIRONMENT_SITES))
def test_actual_precontroller_report_identifies_each_checked_command_only(tmp_path, monkeypatch, capsys, site):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site=site)
    assert run.exit_code == 1
    record = run.record
    assert record["passed"] is False and record["phase"] == "platform_outbound_preflight"
    assert record["failure_type"] == "CalledProcessError" and record["preflight_failure_site"] == site
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type",
              "preflight_failure_site", "preflight_exit_status"}
    assert record["preflight_exit_status"] == 1
    if site == "android_root":
        fields.add("preflight_root_reason")
        assert record["preflight_root_reason"] == "unclassified"
    assert set(record) == fields
    sites = (*ANDROID_START_SITES, *ANDROID_ENVIRONMENT_SITES)
    expected = list(sites[:sites.index(site) + 1])
    if run.script.starts: expected.insert(2, "boot")
    if run.script.starts: expected.append("kill")
    assert run.script.calls == expected and run.events == []
    assert "PRIVATE_" not in run.output
    assert_android_cleaned(run.script)


@pytest.mark.parametrize("fault", ["foreign", "caught_then_same", "unscoped_same", "cleanup_substitution", "after_success"])
@pytest.mark.parametrize("site", ["android_root", "android_root_identity"])
def test_precontroller_report_omits_foreign_or_cleared_command_attribution(tmp_path, monkeypatch, capsys, fault, site):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys,
        site=None if fault == "after_success" else site, fault=fault,
        failure_stderr=b"adb: unable to connect for root: PRIVATE_SUFFIX\n")
    assert run.exit_code == 1 and run.record["phase"] == "platform_outbound_preflight"
    expected_type = "CalledProcessError" if fault in {"caught_then_same", "unscoped_same"} else "PeerFailure"
    assert run.record["failure_type"] == expected_type
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type"}
    if expected_type == "PeerFailure":
        fields.add("error_code")
        assert run.record["error_code"] == "invalid_request"
    assert set(run.record) == fields
    assert "controller" not in run.events and "PRIVATE_" not in run.output
    assert not run.script.emulator.root.exists() and run.script.emulator.process is None


@pytest.mark.parametrize("caught", [False, True])
@pytest.mark.parametrize("site", ["android_root", "android_root_identity"])
def test_success_report_omits_all_preflight_failure_metadata(tmp_path, monkeypatch, capsys, caught, site):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys,
        site=site if caught else None, fault="caught_then_success" if caught else None,
        failure_stderr=b"adb: unable to connect for root: PRIVATE_SUFFIX\n")
    assert run.exit_code == 0 and run.record["passed"] is True
    assert set(run.record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "context",
        "source_commit", "source_tree", "platform", "preflight", "artifacts", "execution"}
    assert run.events == ["services", "controller", "rendezvous_closed", "transport_closed"]
    assert "PRIVATE_" not in run.output and not run.script.emulator.root.exists()
    with pytest.raises(ValueError):
        evidence.verify_pair(interop_reports()[0], run.record, "a" * 40, "b" * 40)


def interop_reports(source="a" * 40, tree="b" * 40, android_artifacts=None, *, workload="full"):
    """Complete fake runs for rejection tests only; no dist report is written."""
    from android_qualification import APKS, CORE_APKS, CONSUMER_ARTIFACTS, INDEPENDENT_ARTIFACTS, ROOT
    plan = evidence.required_workload(workload)
    if android_artifacts is None:
        android_artifacts = {path.relative_to(ROOT).as_posix(): "e" * 64 for path in (*APKS, *CORE_APKS, *CONSUMER_ARTIFACTS, *INDEPENDENT_ARTIFACTS)}
    def message(name, role):
        other = "android" if role == "windows" else "windows"
        return {"outbound": evidence.digest([name, role]), "inbound": evidence.digest([name, other]),
                "authenticated_receipt": True, "inbound_records": 1, "outbound_records": 1, "receipt_roundtrip_ms": 1.0}
    def counts(active=0):
        return {"v": 1, "complete": True, "semantics": "native_allocation_leases", "capacity": 16,
                "reserved_count": active, "creating_count": 0, "allocated_count": active,
                "active_count": active, "retiring_count": 0, "availability": {name: True for name in evidence.ACCOUNTING}}
    def selection(name, role, service, scenario, count, sequence):
        return {"service": evidence.digest(service), "profile": evidence.digest([service, "profile"]),
            "resource": evidence.digest([role, name, "resource"]), "pair": evidence.digest([role, name, "pair"]),
            "sequence": sequence, "local_type": "host" if scenario == "direct" else "relay",
            "remote_type": "srflx" if scenario == "direct" else "relay",
            "relay_protocol": "not_applicable" if scenario == "direct" else "udp" if scenario in {None, "impaired"} else scenario.removeprefix("turn_"),
            "application": {name: count for name in evidence.APPLICATION}, "selected_pair_rtt_ms": 1.0,
            "adopted": True, "attached": True, "messaging_ready": True}
    result = []
    for role in ("windows", "android"):
        cases, iterations = [], []
        identity = evidence.digest([role, "identity"])
        for name, initiator in plan["paths"]:
            case_id = name + ":" + initiator
            before = selection(case_id, role, role + "initial", name, 0, 1)
            after = selection(case_id, role, role + "initial", name, 1, 2)
            negative = None
            if name in {"turn_tcp", "turn_tls", "impaired"}:
                negative = {"blocked_packets": 2 if role == "android" else None, "delivered_while_blocked": False,
                    "delivered_after_restore": True, "kernel_protocol": ("udp" if name == "impaired" else "tcp") if role == "android" else None,
                    "kernel_socket": evidence.digest([name, "kernel socket"]) if role == "android" else None,
                    "outbound": message("negative:" + name, role)["outbound"], "inbound": message("negative:" + name, role)["inbound"]}
            impairment = None
            if name == "impaired" and role == "android":
                impairment = {"kind": "android_emulator_linux_kernel_tc_netem", "delay_ms_each_way": 75,
                    "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                    "socket_correlation": "unique_own_pid_socket_and_kernel_flow", "loss_observed": False,
                    "counters": {direction: {"bytes": 1000, "packets": 10, "dropped": 0} for direction in ("egress", "ingress")}}
            cases.append({"scenario": name, "initiator": initiator, "supervisor_pairing": {
                "operation": evidence.digest([role, case_id, "operation"]), "role": "offer" if role == initiator else "answer",
                "state": "transferred", "transferred_cancel_preserves_carrier": True}, "before": before, "after": after,
                "native_delta": {name: 1 for name in evidence.APPLICATION},
                "messages": [message(f"{case_id}:{index}", role) for index in range(20 if name == "impaired" else 1)],
                "impairment": impairment, "negative": negative, "retired_host_accounting": counts(),
                "owner_retirement_acknowledged": True})
        for index in range(plan["iterations"]):
            generation = index // 10 + 1
            service = role + str(generation)
            previous = role + ("initial" if generation == 1 else str(generation - 1)) if index % 10 == 0 else service
            before = selection("warm:" + service, role, service, None, index % 10 * 2, index % 10 * 2 + 1)
            after = selection("warm:" + service, role, service, None, index % 10 * 2 + 1, index % 10 * 2 + 2)
            iterations.append({"iteration": index + 1, "cold_start": index % 10 == 0, "native_resources": 1,
                "warm_baseline_resources": 1, "previous_service": evidence.digest(previous), "current_service": evidence.digest(service),
                "identity": identity, "before": before, "after": after, "native_delta": {name: 1 for name in evidence.APPLICATION},
                "host_accounting": counts(1), "warm_baseline_host_accounting": counts(1), "message": message(f"soak:{index}", role)})
        result.append({"v": 1, "passed": True, "evidence_level": plan["level"], "role": role, "scope": plan["scope"], "workload": workload,
            "context": {"repository": "example/mesh", "repository_id": 1, "run_id": 2, "run_attempt": 1, "source_commit": source},
            "source_commit": source, "source_tree": tree,
            "platform": {"windows": True} if role == "windows" else {"emulated": True, "abi": "x86_64", "kvm": True},
            "preflight": {"turn_advertised_transports": ["tcp", "tls", "udp"], "mailbox_protocol": 2, "mailbox_writes_enabled": True,
                          "scope": "outbound health and advertisement only; no allocation or selected path"},
            "artifacts": {"sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64} if role == "windows" else dict(android_artifacts),
            "execution": {"identity": identity, "scenarios": cases, "receipt_iterations": iterations,
                "processes_started": (plan["iterations"] - 1) // 10 + 2, "forced_exits": (plan["iterations"] - 1) // 10 + 1,
                "clean_exits": 1, "webview_processes": 0, "cleanup": "passed"}})
        result[-1]["execution"]["final_host_accounting"] = counts()
    return tuple(result)


def test_complete_two_role_fixture_is_accepted_only_with_cross_matching_actual_message_identities():
    windows, android = interop_reports()
    assert evidence.verify_pair(windows, android, "a" * 40, "b" * 40) == (windows, android)


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("fault", ["source", "tree", "scope", "platform", "missing_case", "wrong_selected_protocol", "packet_delta",
    "no_receipt", "duplicate_message", "missing_negative", "block_no_packet", "delivered_under_block", "no_restore",
    "iteration_missing", "process_count", "cold_schedule", "old_service", "warm_growth", "native_lease_growth", "unknown_native_zero",
    "unretired_native", "identity_changed", "cleanup", "wrong_initiator", "manual_pairing", "cancel_reclaimed", "raw_extra"])
def test_native_matrix_rejects_partial_or_unexecuted_required_evidence(role, fault):
    reports = interop_reports()
    value = reports[0 if role == "windows" else 1]
    execution = value["execution"]
    case = next(case for case in execution["scenarios"] if case["scenario"] == "turn_tcp")
    if fault == "source": value["source_commit"] = "c" * 40
    elif fault == "tree": value["source_tree"] = "c" * 40
    elif fault == "scope": value["scope"] = "physical full native and media qualification"
    elif fault == "platform": value["platform"] = {"linux": True}
    elif fault == "missing_case": execution["scenarios"].pop()
    elif fault == "wrong_selected_protocol": case["after"]["relay_protocol"] = "udp"
    elif fault == "packet_delta": case["native_delta"]["enqueued_packets"] = 0
    elif fault == "no_receipt": case["messages"][0]["authenticated_receipt"] = False
    elif fault == "duplicate_message": execution["scenarios"][1]["messages"][0] = execution["scenarios"][0]["messages"][0]
    elif fault == "missing_negative": case["negative"] = None
    elif fault == "block_no_packet": case["negative"]["blocked_packets"] = 0
    elif fault == "delivered_under_block": case["negative"]["delivered_while_blocked"] = True
    elif fault == "no_restore": case["negative"]["delivered_after_restore"] = False
    elif fault == "iteration_missing": execution["receipt_iterations"].pop()
    elif fault == "process_count": execution["forced_exits"] = 0
    elif fault == "cold_schedule": execution["receipt_iterations"][1]["cold_start"] = True
    elif fault == "old_service": execution["receipt_iterations"][0]["current_service"] = execution["receipt_iterations"][0]["previous_service"]
    elif fault == "warm_growth": execution["receipt_iterations"][-1]["native_resources"] = 2
    elif fault == "native_lease_growth": execution["receipt_iterations"][-1]["host_accounting"]["reserved_count"] = 2
    elif fault == "unknown_native_zero": execution["final_host_accounting"]["complete"] = False
    elif fault == "unretired_native":
        execution["scenarios"][0]["retired_host_accounting"].update(reserved_count=1, allocated_count=1, retiring_count=1)
    elif fault == "identity_changed": execution["receipt_iterations"][-1]["identity"] = "f" * 64
    elif fault == "cleanup": execution["cleanup"] = "unavailable"
    elif fault == "wrong_initiator": case["initiator"] = "android"
    elif fault == "manual_pairing": case["supervisor_pairing"]["role"] = "manual"
    elif fault == "cancel_reclaimed": case["supervisor_pairing"]["transferred_cancel_preserves_carrier"] = False
    else: case["after"]["raw_sdp"] = "secret"
    with pytest.raises(ValueError): evidence.verify_pair(*reports, "a" * 40, "b" * 40)


@pytest.mark.parametrize("fault", ["run", "attempt", "same_identity", "other_message", "other_negative", "other_iteration", "loss_profile", "fake_loss", "missing_rtt"])
def test_pair_cannot_mix_runs_peers_or_impairment_profiles(fault):
    windows, android = interop_reports()
    if fault == "run": android["context"]["run_id"] += 1
    elif fault == "attempt": android["context"]["run_attempt"] += 1
    elif fault == "same_identity": android["execution"]["identity"] = windows["execution"]["identity"]
    elif fault == "other_message": android["execution"]["scenarios"][0]["messages"][0]["inbound"] = "f" * 64
    elif fault == "other_negative": next(case for case in android["execution"]["scenarios"] if case["scenario"] == "turn_tcp")["negative"]["inbound"] = "f" * 64
    elif fault == "other_iteration": android["execution"]["receipt_iterations"][-1]["message"]["inbound"] = "f" * 64
    elif fault == "loss_profile": android["execution"]["scenarios"][-1]["impairment"]["loss_percent_each_way"] = 1
    elif fault == "fake_loss": android["execution"]["scenarios"][-1]["impairment"]["loss_observed"] = True
    else: android["execution"]["scenarios"][-1]["before"]["selected_pair_rtt_ms"] = None
    with pytest.raises(ValueError): evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


def test_final_ci_context_cannot_reuse_a_passing_prior_attempt():
    reports = interop_reports()
    context = {**reports[0]["context"], "run_attempt": 2}
    with pytest.raises(ValueError, match="another workflow"):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, context=context)


def test_transport_filtering_uses_one_broker_url_and_never_counts_configuration_as_selected_evidence():
    ice = {"iceServers": [{"urls": ["stun:stun.example:3478"]},
        {"urls": ["turn:relay.example:3478?transport=udp", "turn:relay.example:3478?transport=tcp", "turns:relay.example:5349?transport=tcp"],
         "username": "synthetic", "credential": "synthetic"}]}
    for scenario, prefix in (("direct", "stun:"), ("turn_udp", "turn:"), ("turn_tcp", "turn:"), ("turn_tls", "turns:")):
        value, _ = controller.selected_ice(ice, scenario)
        assert len(value["iceServers"]) == len(value["iceServers"][0]["urls"]) == 1
        assert value["iceServers"][0]["urls"][0].startswith(prefix)
        assert "selected" not in value
    with pytest.raises(ValueError): controller.selected_ice({"iceServers": []}, "turn_tls")


def test_fixed_plan_and_phase_inventory_keep_explicit_bounded_setup_uploads():
    assert checked_payload("control", {"scenarios": list(evidence.SCENARIOS), "iterations": 100, "cold_start_every": 10})
    from native_interop_rendezvous import CASE_COMPLETION_PHASES
    windows = {"key", "reconnect_capabilities", *OFFER_PHASES, *("negative_checked_" + name for name in ("turn_tcp", "turn_tls", "impaired")), *CASE_COMPLETION_PHASES}
    android = {"key", "reconnect_capabilities", "offer", "approved", "impaired_ready", *("negative_ready_" + name for name in ("turn_tcp", "turn_tls", "impaired")), *CASE_COMPLETION_PHASES}
    assert len(windows) == 16 and len(android) == 14
    assert len(windows) + 1 == 17 and len(android) + 1 == 15
    quick = {"case_complete_direct_windows", "case_complete_direct_android", "case_complete_turn_udp_windows"}
    assert len({"key", "offer", "offer_turn_udp", "reconnect_capabilities", *quick}) + 1 == 8
    assert len({"key", "offer", "approved", "reconnect_capabilities", *quick}) + 1 == 8
    assert all(name in APPROVAL_PHASES for name in windows | android if name.startswith("negative"))


def test_workflow_keeps_two_actual_concurrent_platform_jobs_and_owned_emulator_lifetime():
    path = controller.ROOT / ".github/workflows/native-interop.yml"
    workflow = yaml.safe_load(path.read_text())
    assert set(workflow["jobs"]) == {"native_windows_peer", "native_android_peer"}
    windows, android = (workflow["jobs"][name] for name in ("native_windows_peer", "native_android_peer"))
    assert windows["runs-on"] == "windows-latest" and android["runs-on"] == "ubuntu-latest"
    assert "needs" not in windows and "needs" not in android
    for role, job in (("windows", windows), ("android", android)):
        action = next(step for step in job["steps"] if step.get("uses") == "./scripts/native-interop-artifact")
        assert action["with"]["role"] == role and action["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
        assert action["with"]["workload"] == "${{ inputs.workload }}"
        assert next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))["with"]["fetch-depth"] == 0
        assert any(step.get("if") == "always()" and step.get("uses", "").startswith("actions/upload-artifact@") for step in job["steps"])
    assert not any(step.get("uses", "").startswith("reactivecircus/") for step in android["steps"])
    assert any("system-images;android-35;google_apis;x86_64" in step.get("run", "") for step in android["steps"])


def test_controller_uses_supervisor_pairing_and_both_direct_initiators():
    source = Path(controller.__file__).read_text()
    assert all(name in source for name in ("pairing_begin", "pairing_status", "pairing_cancel"))
    assert all(name not in source for name in ("native_webrtc_offer", "native_webrtc_accept",
        "native_webrtc_bind_onboarding", "native_webrtc_apply_answer", "signal_publish", "signal_fetch"))
    assert [(name, role) for name, role in evidence.PATH_CASES if name == "direct"] == [
        ("direct", "windows"), ("direct", "android")]


@pytest.mark.parametrize("mode", ["quick", "full"])
def test_workload_cannot_be_relabelled_or_substituted_for_the_other_matrix(mode):
    reports = interop_reports(workload=mode)
    evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=mode)
    other = "full" if mode == "quick" else "quick"
    with pytest.raises(ValueError):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=other)
    # Changing labels alone cannot bypass the actual fixed native inventory.
    for report in reports:
        report.update(workload=other, scope=evidence.required_workload(other)["scope"],
                      evidence_level=evidence.required_workload(other)["level"])
    with pytest.raises(ValueError):
        evidence.verify_pair(*reports, "a" * 40, "b" * 40, workload=other)


FAILURE_REPORT_CASES = [
    ("android", "negotiate_settings_update", "negotiate_settings_update", "PeerFailure"),
    ("windows", "pairing_offer_begin", "pairing_offer_begin", "PeerFailure"),
    ("android", "pairing_answer_begin", "pairing_answer_begin", "PeerFailure"),
    ("windows", "pairing_status", "pairing_status", "PeerFailure"),
    ("windows", "rendezvous_publish", "rendezvous_publish", "PeerFailure"),
    ("android", "rendezvous_receive", "rendezvous_receive", "PeerFailure"),
    ("android", "negotiate_inventory", "negotiate_inventory", "PeerFailure"),
    ("android", "negotiate_native_stats", "negotiate_native_stats", "PeerFailure"),
    ("windows", "offer_identity", "pairing_offer_begin", "PeerFailure"),
    ("android", "answer_identity", "pairing_answer_begin", "PeerFailure"),
    ("windows", "status_retired", "pairing_status", "PeerFailure"),
    ("android", "inventory_shape", "negotiate_inventory", "KeyError"),
    ("android", "stats_shape", "negotiate_native_stats", "AttributeError"),
    ("windows", "publish_validation", "rendezvous_publish", "ValueError"),
    ("android", "receive_validation", "rendezvous_receive", "ValueError"),
    ("windows", "before_any_call", None, "ValueError"),
    ("windows", "after_success", None, "ValueError"),
    ("android", "after_success", None, "ValueError"),
    ("windows", "caught_then_unrelated", None, "ValueError"),
]


def run_negotiate_report(tmp_path, monkeypatch, capsys, role, fault, *, status_reply=None):
    # Actual main/negotiate/wait/report flow, synthetic peer/artifact boundaries.
    # No native process, network, service allocation or successful evidence claim.
    import connection_ci
    events = []
    def fail(name):
        if fault == name or (fault == "caught_then_unrelated" and name == "negotiate_settings_update"):
            raise controller.PeerFailure("invalid_request")

    class Peer:
        process = None
        def core(self, operation, params, key=None):
            assert key is None
            if operation == "call.settings_update":
                events.append("settings")
                fail("negotiate_settings_update")
                return {}
            assert operation == "native.command" and params == {
                "command": "native_webrtc_stats", "payload": {"session_id": "PRIVATE_LOGICAL"}}
            events.append("stats")
            fail("negotiate_native_stats")
            return None if fault == "stats_shape" else {"data_channel_state": "open"}
        def pairing_begin(self, operation, pairing_role, **kwargs):
            self.operation = operation
            events.append("begin_" + pairing_role)
            assert kwargs["direct"] is True
            if pairing_role == "answer": assert kwargs["pairing_code"] == "PRIVATE_SIGNED_CODE"
            fail("pairing_" + pairing_role + "_begin")
            return {"operation_id": "PRIVATE_OTHER_ID" if fault == pairing_role + "_identity" else operation}
        def pairing_status(self, operation):
            events.append("status")
            fail("pairing_status")
            if status_reply is not None: return status_reply(operation)
            return {"operation_id": operation, "state": "retired" if fault == "status_retired" else "offer_ready",
                    "pairing_code": "PRIVATE_SIGNED_CODE"}
        def inventory(self):
            events.append("inventory")
            fail("negotiate_inventory")
            return {"resources": [{}] if fault == "inventory_shape" else [{"logical_session": "PRIVATE_LOGICAL"}]}

    class Transport:
        def publish(self, *args):
            events.append("publish")
            fail("rendezvous_publish")
        def wait(self, partner, phase, *, timeout):
            assert partner == "windows" and phase == "offer" and timeout == 180
            events.append("receive")
            fail("rendezvous_receive")
            return {"shareable": "PRIVATE_SIGNED_CODE"}
        def close(self): pass

    class Rendezvous:
        def seal(self, phase, value):
            if fault == "publish_validation": raise ValueError("PRIVATE_URL/SDP/KEY publish")
            return value
        def open(self, phase, value):
            if fault == "receive_validation": raise ValueError("PRIVATE_URL/SDP/KEY receive")
            return value
        def close(self): pass

    def negotiate_only(instance):
        instance.profile = "PRIVATE_PROFILE"
        instance.default_call_settings = {}
        instance.broker_ice = {"iceServers": [] if fault == "before_any_call" else [{"urls": ["stun:PRIVATE_URL"]}]}
        if fault in {"caught_then_unrelated", "caught_status_then_unrelated", "caught_status_then_success", "caught_status_then_foreign"}:
            with pytest.raises(controller.PeerFailure): instance.negotiate("direct", "windows")
            if fault in {"caught_status_then_success", "caught_status_then_foreign"}: instance.pairing_status()
        else:
            instance.negotiate("direct", "windows")
        if fault == "success": return {}
        error = ValueError("PRIVATE_LATER_EXCEPTION/SDP/KEY")
        error.failure_site = "PRIVATE_CALLER_SUPPLIED_SITE"
        raise error

    context = {"source_commit": "a" * 40}
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: context)
    monkeypatch.setattr(controller, "binding", lambda *_: (Path("unused.exe"), {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *_, **__: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: Peer())
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: Transport())
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: Rendezvous())
    monkeypatch.setattr(controller.Controller, "run", negotiate_only)
    output = tmp_path / "failure.json"
    monkeypatch.setattr(sys, "argv", ["native_interop_controller", "--role", role, "--expected-source", "a" * 40,
                                      "--workload", "full", "--output", str(output)])
    exit_code = controller.main()
    record = json.loads(output.read_text())
    captured = capsys.readouterr()
    return SimpleNamespace(record=record, events=events, exit_code=exit_code,
        output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("role,fault,site,error_type", FAILURE_REPORT_CASES)
def test_actual_failure_report_selects_only_active_literal_call_site(tmp_path, monkeypatch, capsys, role, fault, site, error_type):
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, role, fault)
    record, events = run.record, run.events
    assert run.exit_code == 1
    assert record["passed"] is False and record["phase"] == "direct_supervisor_owned_pairing_windows"
    assert record["workload"] == "full" and record["failure_type"] == error_type
    if site is None: assert "failure_site" not in record
    else: assert record["failure_site"] == site and site in controller.FAILURE_SITES
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type"}
    if error_type == "PeerFailure":
        fields.add("error_code")
        expected_code = ("invalid_pairing_identity" if fault in {"offer_identity", "answer_identity"}
                         else "supervisor_pairing_retired" if fault == "status_retired" else "invalid_request")
        assert record["error_code"] == expected_code
    if site is not None: fields.add("failure_site")
    if fault == "status_retired":
        fields.add("pairing_state")
        assert record["pairing_state"] == "retired" and "pairing_retirement" not in record
    assert set(record) == fields
    success_path = (["settings", "begin_offer", "status", "publish", "status", "inventory", "stats"] if role == "windows"
                    else ["settings", "receive", "begin_answer", "status", "inventory", "stats"])
    assert events == success_path[:len(events)]  # No added/reordered/repeated requests.
    if fault == "after_success": assert events == success_path
    assert "PRIVATE_" not in run.output


def retirement_example():
    # Agreed first-causal-transition DTO, checked against C's shared sanitizer.
    value = {"phase": "gather_answer", "event": "failed", "reason": "invalid_document"}
    assert controller.validated_pairing_retirement(value) == value
    return value


RETIREMENT_CASES = ("valid", "absent", "null", "empty", "missing_phase", "missing_event", "missing_reason",
    "extra_private", "phase_private", "event_private", "reason_private", "foreign_identity", "stale_time",
    "phase_number", "event_array", "reason_object", "scalar", "array")


@pytest.mark.parametrize("state", ["retiring", "retired"])
@pytest.mark.parametrize("case", RETIREMENT_CASES)
def test_retirement_failure_retains_actual_state_and_only_shared_sanitized_cause(tmp_path, monkeypatch, capsys, state, case):
    valid = retirement_example()
    value = dict(valid)
    if case.startswith("missing_"): value.pop(case.removeprefix("missing_"))
    elif case == "extra_private": value["sdp"] = "PRIVATE_SDP"
    elif case.endswith("_private"): value[case.removesuffix("_private")] = "PRIVATE_ENUM"
    elif case == "foreign_identity": value["operation_id"] = "PRIVATE_FOREIGN_ID"
    elif case == "stale_time": value["sampled_at_ms"] = 123
    elif case == "phase_number": value["phase"] = 1
    elif case == "event_array": value["event"] = ["PRIVATE_EVENT"]
    elif case == "reason_object": value["reason"] = {"raw": "PRIVATE_REASON"}
    elif case == "null": value = None
    elif case == "empty": value = {}
    elif case == "scalar": value = "PRIVATE_RAW_ERROR"
    elif case == "array": value = [valid]
    def reply(operation):
        result = {"operation_id": operation, "state": state, "pairing_code": "PRIVATE_PAIRING_CODE",
                  "resource": "PRIVATE_RESOURCE", "url": "https://PRIVATE_URL", "raw_error": "PRIVATE_ERROR"}
        if case != "absent": result["retirement"] = value
        return result
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", "retirement", status_reply=reply)
    record = run.record
    assert run.exit_code == 1 and record["passed"] is False
    assert record["error_code"] == "supervisor_pairing_retired" and record["failure_site"] == "pairing_status"
    assert record["phase"] == "direct_supervisor_owned_pairing_windows" and record["workload"] == "full"
    assert record["pairing_state"] == state
    if case == "valid": assert record["pairing_retirement"] == valid
    else: assert "pairing_retirement" not in record
    assert set(record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type",
                           "error_code", "failure_site", "pairing_state"} | ({"pairing_retirement"} if case == "valid" else set())
    assert run.events == ["settings", "begin_offer", "status"]
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("state", ["retiring", "retired"])
def test_foreign_status_identity_cannot_attach_state_or_retirement(tmp_path, monkeypatch, capsys, state):
    value = retirement_example()
    def forbidden_sanitize(_): pytest.fail("Foreign status detail was inspected")
    monkeypatch.setattr(controller, "validated_pairing_retirement", forbidden_sanitize)
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", "foreign_status",
        status_reply=lambda _: {"operation_id": "PRIVATE_FOREIGN_ID", "state": state, "retirement": value})
    assert run.record["error_code"] == "invalid_pairing_identity" and run.record["failure_site"] == "pairing_status"
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("fault", ["caught_status_then_unrelated", "caught_status_then_success", "caught_status_then_foreign"])
def test_retirement_detail_belongs_only_to_same_active_status_exception(tmp_path, monkeypatch, capsys, fault):
    value = retirement_example()
    calls = []
    def reply(operation):
        calls.append(operation)
        if len(calls) == 1: return {"operation_id": operation, "state": "retired", "retirement": value}
        return {"operation_id": "PRIVATE_OTHER_ID" if fault.endswith("foreign") else operation,
                "state": "retired" if fault.endswith("foreign") else "offer_ready", "retirement": value}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", fault, status_reply=reply)
    assert run.exit_code == 1 and run.record["passed"] is False
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    if fault.endswith("foreign"):
        assert run.record["failure_site"] == "pairing_status" and run.record["error_code"] == "invalid_pairing_identity"
    else:
        assert "failure_site" not in run.record and run.record["failure_type"] == "ValueError"
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("role", ["windows", "android"])
def test_successful_negotiate_report_never_gains_retirement_failure_fields(tmp_path, monkeypatch, capsys, role):
    value = retirement_example()
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, role, "success",
        status_reply=lambda operation: {"operation_id": operation, "state": "offer_ready",
            "pairing_code": "PRIVATE_SIGNED_CODE", "retirement": value})
    assert run.exit_code == 0 and run.record["passed"] is True
    assert not {"failure_site", "pairing_state", "pairing_retirement"} & set(run.record)
    assert "PRIVATE_" not in run.output
    # This intentionally incomplete component fixture cannot qualify native CI.
    with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, role)


# Derived from B's independently retained original-path reproducer; boundary models only.
from copy import deepcopy as completion_copy
from threading import Event, Lock, Thread
from time import monotonic as completion_monotonic
import native_interop_faults as completion_faults
from native_interop_evidence import ACCOUNTING, APPLICATION
from mesh_chat.native_path_evidence import candidate, observation, pair_token

class CompletionRendezvous:
    def seal(self, _phase, value): return completion_copy(value)
    def open(self, _phase, value): return completion_copy(value)


class CompletionWorld:
    def __init__(self, mode):
        self.mode, self.lock = mode, Lock()
        self.live, self.blocked = True, False
        self.events, self.documents, self.messages = [], {}, {}
        self.records = {role: [] for role in ("windows", "android")}
        self.counters = {role: dict.fromkeys(APPLICATION, 0) for role in self.records}
        self.final_entered, self.fast_retired = Event(), Event()
        self.cleanup_entered, self.cleanup_finished = Event(), Event()
        self.final_finished = {role: Event() for role in self.records}
        self.measurement_invalidated = self.cleanup_overtaken = False
        self.retired_roles, self.pending = set(), []
        self.results = {}
        self.release_slow, self.completion_reached = Event(), Event()
        self.prepared_roles = set()

    def event(self, role, stage):
        with self.lock: self.events.append([role, stage])

    def publish(self, role, phase, value):
        with self.lock:
            if phase.startswith("case_complete_"):
                assert phase == "case_complete_turn_tcp_windows" and value == {"completed": True}
                assert role in self.prepared_roles and self.final_finished[role].is_set()
                if role == "android": assert self.cleanup_finished.is_set()
                self.events.append([role, "completion_publish"])
            self.documents[role, phase] = completion_copy(value)
        if role == "windows" and phase.startswith("case_complete_"): self.completion_reached.set()

    def receive(self, role, phase):
        until = completion_monotonic() + 3  # Harness safety bound, not a product deadline.
        while completion_monotonic() < until:
            with self.lock:
                if (role, phase) in self.documents:
                    return completion_copy(self.documents[role, phase])
            Event().wait(.001)
        raise AssertionError("scripted rendezvous did not receive its phase")

    def enqueue(self, role, text):
        with self.lock:
            handle = role + ":" + str(len(self.messages))
            self.messages[handle] = {"role": role, "text": text, "delivered": False}
            self.records[role].append({"id": handle, "text": text, "direction": "outbound",
                "kind": "chat", "native_message_id": "modeled-native-message"})
            self.counters[role]["enqueued_packets"] += 1
            self.counters[role]["enqueued_bytes"] += len(text)
            if self.blocked: self.pending.append(handle)
            else: self.deliver(handle)
            return {"accepted": True, "message": handle}

    def deliver(self, handle):
        value = self.messages[handle]
        other = "android" if value["role"] == "windows" else "windows"
        value["delivered"] = True
        self.records[other].append({"id": handle, "text": value["text"], "direction": "inbound", "kind": "chat"})
        self.counters[other]["received_packets"] += 1
        self.counters[other]["received_bytes"] += len(value["text"])

    def retire(self, role):
        with self.lock:
            assert self.prepared_roles == {"windows", "android"}
            assert all(gate.is_set() for gate in self.final_finished.values()) and self.cleanup_finished.is_set()
            assert all((peer, "case_complete_turn_tcp_windows") in self.documents for peer in self.records)
            self.events.append([role, "commit"])
            self.live = False
            self.retired_roles.add(role)


class CompletionFault:
    protocol, socket = "tcp", {"modeled_socket": True}
    def __init__(self, peer, _sample, _url, *, diagnostics=None): self.world = peer.world
    def block(self):
        with self.world.lock: self.world.blocked = True
    def unblock(self):
        with self.world.lock:
            self.world.blocked = False
            count = len(self.world.pending)
            for handle in self.world.pending: self.world.deliver(handle)
            self.world.pending.clear()
            return count
    def close(self):
        world = self.world
        world.event("android", "fault_cleanup_entered")
        world.cleanup_entered.set()
        if world.mode == "cleanup":
            assert world.release_slow.wait(6), "test did not independently release pending cleanup"
        world.cleanup_finished.set()
        world.event("android", "fault_cleanup_finished")


class CompletionPeer:
    def __init__(self, world, role):
        self.world, self.role, self.calls = world, role, 0
        self.service = ("a" if role == "windows" else "b") * 32
        self.profile = ("c" if role == "windows" else "d") * 32
        self.epoch = ("e" if role == "windows" else "f") * 32
        self.logical, self.physical = "modeled-session-" + role, "modeled-resource-" + role
        self.operation, self.request_id = None, None

    def core(self, operation, params, key=None):
        assert (isinstance(key, str) and len(key) == 32) if operation == "message.enqueue" else key is None
        if operation == "call.settings_update": return {}
        if operation == "native.command":
            assert params["command"] == "native_webrtc_stats"
            return {"data_channel_state": "open"}
        if operation == "message.enqueue": return self.world.enqueue(self.role, params["text"])
        if operation == "message.query":
            with self.world.lock: delivered = self.world.messages[params["message"]]["delivered"]
            return {"state": "delivered" if delivered else "pending"}
        if operation == "application.snapshot":
            with self.world.lock: return {"messages": completion_copy(self.world.records[self.role])}
        raise AssertionError("unexpected modeled Core operation")

    def pairing_begin(self, operation, _role, **_kwargs):
        self.operation = operation
        return {"operation_id": operation}
    def pairing_status(self, operation):
        assert operation == self.operation
        return {"operation_id": operation, "state": "transferred", "pairing_code": "modeled-shareable-code"}
    def pairing_cancel(self, operation):
        assert operation == self.operation
        return {"operation_id": operation, "state": "transferred"}

    def inventory(self, *, operation_id=None, request_id=None):
        retired = self.role in self.world.retired_roles
        counts = dict(capacity=16, reserved_count=int(not retired), creating_count=0,
            allocated_count=int(not retired), active_count=int(not retired), retiring_count=0)
        value = {"service_incarnation": self.service, "profile_incarnation": self.profile,
            "resources": [] if retired else [{"logical_session": self.logical,
                "physical_resource": self.physical, "owner_state": "authorized"}],
            "host_accounting": {"v": 1, "complete": True, "semantics": "native_allocation_leases",
                "availability": dict.fromkeys(ACCOUNTING, True), **counts}}
        if operation_id is not None:
            assert operation_id == self.operation and request_id == self.request_id
            value["carrier_retirement"] = {"request_id": request_id, "state": "acknowledged"}
        return value

    def path(self, logical, physical, sample_request):
        assert (logical, physical) == (self.logical, self.physical)
        self.calls += 1
        if self.calls == 3:
            self.world.event(self.role, "final_measurement_entered")
            if self.role == "android" and self.world.mode == "measurement":
                self.world.final_entered.set()
                assert self.world.release_slow.wait(6), "test did not independently release final measurement"
        with self.world.lock:
            live, counters = self.world.live, dict(self.world.counters[self.role])
        local = candidate("192.0.2.1", 10001, "relay", "udp")
        remote = candidate("198.51.100.2", 10002, "relay", "udp")
        pair = {"token": pair_token(self.epoch, physical, local, remote), "local": local, "remote": remote,
            "nominated": True, "relay_protocol": "tcp", "relay_socket": None,
            "bytes_sent": None, "bytes_received": None, "rtt_ms": 1.0}
        result = observation(physical, self.epoch, self.calls, 100000, sample_request=sample_request,
            status="selected" if live else "not_selected", ice_state="completed" if live else "closed",
            dtls_state="connected" if live else "closed", channel_state="open" if live else "closed",
            pair=pair if live else None, application=counters)
        result.update(service_incarnation=self.service, profile_incarnation=self.profile,
            logical_session=logical, qualification_only=True, valid_for_ms=2000, sample_elapsed_ms=0,
            adopted=live, attached=live, messaging_ready=live)
        if self.calls == 3:
            self.world.final_finished[self.role].set()
            self.world.event(self.role, "final_measurement_finished" if live else "final_measurement_lost")
        return result

    def retire_carrier(self, operation_id, request_id, logical_session, expected_physical,
                       expected_service_incarnation, expected_adapter_epoch, *, action):
        assert (operation_id, logical_session, expected_physical, expected_service_incarnation, expected_adapter_epoch) == (
            self.operation, self.logical, self.physical, self.service, self.epoch)
        if action == "prepare":
            assert self.world.live and self.request_id is None
            self.request_id = request_id
            with self.world.lock:
                self.world.prepared_roles.add(self.role)
                self.world.events.append([self.role, "prepare"])
            return {"request_id": request_id, "state": "prepared"}
        assert action == "commit" and request_id == self.request_id
        self.world.retire(self.role)
        return {"request_id": request_id, "state": "pending"}


def run_completion_pair(mode, monkeypatch):
    world = CompletionWorld(mode)
    monkeypatch.setattr(completion_faults, "AndroidKernelPath", CompletionFault)
    observers = {}
    for role in ("windows", "android"):
        peer = CompletionPeer(world, role)
        transport = type("Transport", (), {
            "publish": lambda _self, phase, value, r=role: world.publish(r, phase, value),
            "wait": lambda _self, partner, phase, **_kwargs: world.receive(partner, phase)})()
        observer = controller.Controller(role, peer, transport, CompletionRendezvous(),
            {"run_id": "modeled-run", "run_attempt": "1"})
        observer.profile, observer.contact = "modeled-profile", {"id": "modeled-contact", "core_handle": "modeled-peer"}
        observer.default_call_settings = {}
        observer.broker_ice = {"iceServers": [{"urls": ["turn:192.0.2.1:3478?transport=tcp"],
            "username": "modeled", "credential": "modeled"}]}
        observers[role] = observer
    def execute(role):
        try:
            observers[role].path_case("turn_tcp", "windows")
            world.results[role] = None
        except BaseException as error:
            world.results[role] = error
    workers = [Thread(target=execute, args=(role,), daemon=True) for role in observers]
    for worker in workers: worker.start()
    try:
        assert world.completion_reached.wait(6), "fast controller did not publish completion"
        gate = world.cleanup_entered if mode == "cleanup" else world.final_entered
        assert gate.wait(3), "slow peer never reached its independent gate"
        assert world.retired_roles == set() and world.prepared_roles == {"windows"}
        assert ("android", "case_complete_turn_tcp_windows") not in world.documents
    finally:
        world.release_slow.set()
        for worker in workers: worker.join(8)
    assert all(not worker.is_alive() for worker in workers), "scripted controller worker remained active"
    return world, observers




@pytest.mark.parametrize("mode", ["measurement", "cleanup"])
def test_two_actual_controllers_cannot_retire_before_peer_final_measurement_and_cleanup(monkeypatch, mode):
    """Actual controller algorithms; scripted packet/host/crypto boundaries, no native proof."""
    world, instances = run_completion_pair(mode, monkeypatch)
    assert world.results == {"windows": None, "android": None}
    for role, instance in instances.items():
        assert instance.peer.calls == 3 and len(instance.cases) == 1
        assert instance.cases[0]["owner_retirement_acknowledged"] is True
        events = [stage for peer, stage in world.events if peer == role]
        assert events.index("final_measurement_finished") < events.index("prepare") < events.index("completion_publish") < events.index("commit")
    first_commit = min(index for index, event in enumerate(world.events) if event[1] == "commit")
    assert world.events.index(["android", "fault_cleanup_finished"]) < first_commit
    assert all(world.events.index([role, "completion_publish"]) < first_commit for role in instances)
