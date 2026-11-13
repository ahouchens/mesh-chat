"""Controller/evidence component checks; synthetic reports are never CI proof."""

from pathlib import Path
import copy
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from types import ModuleType, SimpleNamespace
import urllib.request

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_evidence as evidence
from native_interop_rendezvous import (APPROVAL_PHASES, COLD_COMPLETE_PHASES, COLD_STARTED_PHASES,
                                       OFFER_PHASES, Rendezvous, checked_payload)
from test_ui_core_boundary_interop_peers import (
    ANDROID_ENVIRONMENT_SITES, ANDROID_START_SITES, assert_android_cleaned, scripted_android,
)
from test_ui_core_boundary_interop_evidence import sample
from test_ui_core_boundary_interop_artifacts import RECEIVE_ORIGINS


@pytest.mark.parametrize("fault,stage,reason", [
    ("inventory_http", "inventory_request", "http_rejected"),
    ("archive_http", "archive_request", "http_rejected"),
    ("open_timeout", "inventory_request", "transport_failed"),
])
def test_initial_key_wait_projects_only_its_bounded_transport_failure(
        tmp_path, monkeypatch, fault, stage, reason):
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, fault, role="android", phase="key")
    instance = controller.Controller("windows", SimpleNamespace(), state.transport,
        SimpleNamespace(public_manifest=lambda: {}), {}, workload="full")
    instance.initialize = lambda: None
    state.transport.publish = lambda *_: None
    original_wait = state.transport.wait
    wait_timeouts = []
    def wait(*args, **kwargs):
        wait_timeouts.append(kwargs["timeout"])
        return original_wait(*args, **kwargs)
    state.transport.wait = wait
    with pytest.raises(controller.RendezvousUnavailable) as caught:
        instance.run()
    assert instance.phase == "initialize" and instance.failure_site(caught.value) == "initialize_key_wait"
    expected = {"rendezvous_stage": stage, "rendezvous_reason": reason}
    if fault.endswith("http"): expected["rendezvous_http_status"] = 403
    assert instance.failure_rendezvous(caught.value) == expected
    assert instance.failure_rendezvous(controller.RendezvousUnavailable("PRIVATE_FOREIGN")) == {}
    instance._operation_failure = caught.value, "initialize_key_publish"
    assert instance.failure_rendezvous(caught.value) == {}
    assert wait_timeouts == [900] and "PRIVATE" not in repr(expected)


def test_initial_key_wait_observer_fault_cannot_replace_original_failure(tmp_path, monkeypatch):
    from test_ui_core_boundary_interop_artifacts import scripted_receive
    state = scripted_receive(tmp_path, monkeypatch, "inventory_http", role="android", phase="key")
    instance = controller.Controller("windows", SimpleNamespace(), state.transport,
        SimpleNamespace(public_manifest=lambda: {}), {}, workload="full")
    instance.initialize = lambda: None
    state.transport.publish = lambda *_: None
    with pytest.raises(controller.RendezvousUnavailable) as caught:
        instance.run()
    monkeypatch.setattr(state.transport, "failure_observation", lambda _: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_OBSERVER_ERROR")))
    assert instance.failure_rendezvous(caught.value) == {}
    assert instance.failure_site(caught.value) == "initialize_key_wait"
    monkeypatch.setattr(state.transport, "failure_observation", lambda _: {
        "rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected",
        "url": "PRIVATE_URL"})
    assert instance.failure_rendezvous(caught.value) == {}


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
    def receive(phase, *, timeout=None):
        state.events.append(("receive", phase))
        if phase.startswith("cold_started_"): return {"started": True}
        if phase.startswith("cold_complete_"): return {"completed": True}
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
    assert state.events[-2:] == ["inventory", ("stop", {
        "crash": True, "_origin": "old_stop"})]


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
    def observe(logical=None, ready=False, retirement_deadline=None, missing_reasons=None):
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
    assert state.stops == [(index, {"crash": True,
        "_origin": "old_stop"})
        for index in range(0, iterations, 10)]
    assert len(state.stops) == restarts and state.observations == iterations * 2
    assert [cycle["cold_start"] for cycle in instance.cycles] == [index % 10 == 0 for index in range(iterations)]
    for cycle in instance.cycles:
        assert cycle["native_delta"] == dict.fromkeys(evidence.APPLICATION, 1)
        assert cycle["native_resources"] == cycle["warm_baseline_resources"] == 1
        assert cycle["host_accounting"] == cycle["warm_baseline_host_accounting"]
    assert "PRIVATE" not in json.dumps(instance.cycles)
    markers = [event[1] for event in state.events if isinstance(event, tuple) and event[0] == "publish"]
    expected = ["reconnect_capabilities"]
    for index in range(iterations):
        if index % 10 == 0: expected.append(f"cold_started_{index}")
        if (index + 1) % 10 == 0 or index + 1 == iterations:
            expected.append(f"cold_complete_{index + 1}")
    assert markers == expected


def test_two_cold_controllers_wait_for_reciprocal_start_and_completion(monkeypatch, sample):
    """The actual loop cannot exchange before both starts or crash before both evidence blocks."""
    states = {role: cold_setup_controller(monkeypatch, role=role) for role in ("windows", "android")}
    documents = {}
    condition = threading.Condition()
    windows_started = threading.Event()
    windows_complete = threading.Event()
    android_start_paused = threading.Event()
    release_android_start = threading.Event()
    android_tenth_paused = threading.Event()
    release_android_tenth = threading.Event()
    android_final_paused = threading.Event()
    release_android_final = threading.Event()
    windows_final_complete = threading.Event()
    windows_returned = threading.Event()
    failures = []
    for role, state in states.items():
        instance, peer = state.controller, state.controller.peer
        instance.workload = {**controller.required_workload("full"), "iterations": 20}
        instance.identity = evidence.digest("PRIVATE_DURABLE_IDENTITY")
        state.incarnation, state.stops, state.exchanges, state.observations = 1, [], [], 0
        original_core = peer.core
        def core_call(operation, params, key=None, *, state=state, instance=instance, original_core=original_core):
            if operation == "runtime.capabilities": return {"profiles": [instance.profile]}
            return original_core(operation, params, key)
        def inventory(*, state=state):
            return {"service_incarnation": str(state.incarnation), "resources": ["PRIVATE_RESOURCE"]}
        def stop(*, state=state, **kwargs):
            state.stops.append(len(state.exchanges))
        def start(*, state=state, role=role):
            if role == "android" and state.incarnation == 1:
                android_start_paused.set()
                assert release_android_start.wait(10)
            state.incarnation += 1
            return inventory(state=state)
        def publish(phase, value, *, role=role):
            with condition:
                documents[role, phase] = copy.deepcopy(value)
                condition.notify_all()
            if role == "windows" and phase == "cold_started_0": windows_started.set()
            if role == "windows" and phase == "cold_complete_10": windows_complete.set()
            if role == "windows" and phase == "cold_complete_20": windows_final_complete.set()
        def receive(phase, *, timeout=180, role=role):
            partner = "android" if role == "windows" else "windows"
            with condition:
                assert condition.wait_for(lambda: (partner, phase) in documents, timeout=10)
                return copy.deepcopy(documents[partner, phase])
        def ready(*, state=state):
            state.observations += 1
            result = copy.deepcopy(sample[0])
            result["sample_sequence"] = state.observations
            result["application"] = dict.fromkeys(evidence.APPLICATION, state.observations)
            return result
        def exchange(scenario, index, *, state=state, role=role):
            state.exchanges.append(index)
            return {"outbound": "a" * 64, "inbound": "b" * 64}, f"PRIVATE_MESSAGE_{index}"
        def exact_observe(*_args, state=state, role=role, **_kwargs):
            if role == "android" and state.exchanges and state.exchanges[-1] == 9:
                android_tenth_paused.set()
                assert release_android_tenth.wait(10)
            if role == "android" and state.exchanges and state.exchanges[-1] == 19:
                android_final_paused.set()
                assert release_android_final.wait(10)
            return ready(state=state)
        monkeypatch.setattr(peer, "core", core_call)
        monkeypatch.setattr(peer, "inventory", inventory)
        monkeypatch.setattr(peer, "stop", stop)
        monkeypatch.setattr(peer, "start", start, raising=False)
        monkeypatch.setattr(instance, "publish", publish)
        monkeypatch.setattr(instance, "receive", receive)
        monkeypatch.setattr(instance, "approved_contact", lambda instance=instance: instance.contact)
        monkeypatch.setattr(instance, "snapshot", lambda: {"profile": {"destination_hash": "PRIVATE_DURABLE_IDENTITY"}})
        monkeypatch.setattr(instance, "delivered", lambda _: True)
        monkeypatch.setattr(instance, "cold_ready_observation", ready)
        monkeypatch.setattr(instance, "exchange", exchange)
        monkeypatch.setattr(instance, "observe", exact_observe)
        monkeypatch.setattr(instance, "warm_counts", lambda: {"leases": 1})
        monkeypatch.setattr(instance, "wait", lambda callback, **_kwargs: callback())
    def run(role):
        try:
            states[role].controller.cold_starts()
            if role == "windows": windows_returned.set()
        except BaseException as error: failures.append(error)
    threads = [threading.Thread(target=run, args=(role,), daemon=True) for role in states]
    for thread in threads: thread.start()
    try:
        assert android_start_paused.wait(10) and windows_started.wait(10)
        assert states["windows"].exchanges == []
        release_android_start.set()
        assert android_tenth_paused.wait(10) and windows_complete.wait(10)
        assert states["windows"].stops == [0]
        release_android_tenth.set()
        assert android_final_paused.wait(10) and windows_final_complete.wait(10)
        assert not windows_returned.is_set()
    finally:
        release_android_start.set()
        release_android_tenth.set()
        release_android_final.set()
        for thread in threads: thread.join(10)
    assert not any(thread.is_alive() for thread in threads)
    assert not failures
    assert windows_returned.is_set()
    assert [len(states[role].controller.cycles) for role in states] == [20, 20]
    assert states["windows"].stops == [0, 10]


def test_cold_barrier_preserves_original_missing_error_and_rejects_invalid_payload(monkeypatch):
    instance = controller.Controller("windows", None, None, None, {}, workload="quick")
    sent = []
    monkeypatch.setattr(instance, "publish", lambda phase, payload: sent.append((phase, payload)))
    missing = controller.RendezvousUnavailable("missing")
    def absent(*_args, **_kwargs): raise missing
    monkeypatch.setattr(instance, "receive", absent)
    with pytest.raises(controller.RendezvousUnavailable) as caught:
        instance.cold_barrier("cold_started_0", {"started": True})
    assert caught.value is missing and sent == [("cold_started_0", {"started": True})]
    monkeypatch.setattr(instance, "receive", lambda *_args, **_kwargs: {"started": False})
    with pytest.raises(ValueError): instance.cold_barrier("cold_started_0", {"started": True})


def test_cold_barrier_obeys_original_deadline_before_and_after_io(monkeypatch):
    instance = controller.Controller("windows", None, None, None, {}, workload="quick")
    calls = []
    def publish(*_args): calls.append("publish")
    def receive(*_args, **_kwargs):
        calls.append("receive")
        return {"started": True}
    monkeypatch.setattr(instance, "publish", publish)
    monkeypatch.setattr(instance, "receive", receive)
    instance.deadline = controller.time.monotonic() - 1
    with pytest.raises(controller.PeerFailure): instance.cold_barrier("cold_started_0", {"started": True})
    assert calls == []
    def late_publish(*_args):
        calls.append("publish")
        instance.deadline = controller.time.monotonic() - 1
    instance.deadline = controller.time.monotonic() + 30
    monkeypatch.setattr(instance, "publish", late_publish)
    with pytest.raises(controller.PeerFailure): instance.cold_barrier("cold_started_0", {"started": True})
    assert calls == ["publish"]
    instance.deadline = controller.time.monotonic() + 30
    monkeypatch.setattr(instance, "publish", publish)
    def late_receive(*_args, **_kwargs):
        calls.append("receive")
        instance.deadline = controller.time.monotonic() - 1
        return {"started": True}
    monkeypatch.setattr(instance, "receive", late_receive)
    with pytest.raises(controller.PeerFailure): instance.cold_barrier("cold_started_0", {"started": True})
    assert calls == ["publish", "publish", "receive"]


def test_cold_barrier_phases_reject_replayed_stale_or_mixed_markers():
    from test_ui_core_boundary_interop_artifacts import CONTEXT
    now = [1000]
    windows = Rendezvous(CONTEXT, "windows", clock=lambda: now[0])
    android = Rendezvous(CONTEXT, "android", clock=lambda: now[0])
    try:
        windows.bind_partner(android.public_manifest())
        android.bind_partner(windows.public_manifest())
        assert len(COLD_STARTED_PHASES) == 10 and len(COLD_COMPLETE_PHASES) == 11
        for phase, invalid in (("cold_started_0", {"started": False}),
                               ("cold_complete_5", {"completed": 1}),
                               ("cold_complete_10", {"completed": True, "receipt": "PRIVATE"})):
            with pytest.raises(ValueError): checked_payload(phase, invalid)
        marker = windows.seal("cold_started_0", {"started": True})
        with pytest.raises(ValueError): android.open("cold_started_10", marker)
        assert android.open("cold_started_0", marker) == {"started": True}
        with pytest.raises(ValueError): android.open("cold_started_0", marker)
        stale = windows.seal("cold_complete_5", {"completed": True})
        now[0] += 600
        with pytest.raises(ValueError): android.open("cold_complete_5", stale)
    finally:
        windows.close()
        android.close()


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
            assert kwargs == {"crash": True, "_origin": "old_stop"}
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


@pytest.mark.parametrize("scenario", ["direct", "turn_udp"])
def test_final_observation_missing_uses_existing_skip_fact_in_actual_path_case(monkeypatch, sample, scenario):
    state = retirement_case(monkeypatch, sample, role="android")
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3:
            controller.record_final_path_skip(kwargs.get("missing_reasons"), "messaging_ready_not_true")
            return None
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as caught:
        state.controller.path_case(scenario, "windows")
    assert str(caught.value) == "Native selected path disappeared after receipt delivery"
    assert state.controller.failure_final_evidence(caught.value) == {"final_evidence_failure": {
        "scenario": scenario, "stage": "final_observation", "reason": "path_missing",
        "skip_reason": "messaging_ready_not_true"}}
    assert state.controller.failure_final_evidence(ValueError("PRIVATE_FOREIGN")) == {}
    assert state.observation == 3 and state.actions == [] and not state.markers


def test_final_observation_exception_keeps_primary_error_in_actual_turn_udp_path(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample, role="android")
    original = state.controller.observe
    failure = ValueError("PRIVATE_OBSERVATION_ERROR")
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3: raise failure
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as caught:
        state.controller.path_case("turn_udp", "windows")
    assert caught.value is failure
    assert state.controller.failure_final_evidence(failure) == {"final_evidence_failure": {
        "scenario": "turn_udp", "stage": "final_observation", "reason": "observation_error"}}
    assert "PRIVATE" not in json.dumps(state.controller.failure_final_evidence(failure))


@pytest.mark.parametrize("change,reason,fields", [
    ("service_incarnation", "native_identity_changed", ["service_incarnation"]),
    ("profile_incarnation", "native_identity_changed", ["profile_incarnation"]),
    ("logical_session", "native_identity_changed", ["logical_session"]),
    ("resource", "native_identity_changed", ["resource"]),
    ("adapter_epoch", "native_identity_changed", ["adapter_epoch"]),
    ("pair", "selected_pair_changed", None),
    ("sequence", "sample_sequence_not_increasing", None),
    ("regression", "counter_regression", ["received_controls"]),
    ("missing_positive", "required_delta_missing", ["received_packets"]),
])
def test_final_traffic_attribution_uses_fixed_labels_in_actual_turn_udp_path(monkeypatch, sample, change, reason, fields):
    state = retirement_case(monkeypatch, sample, role="android")
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if change == "regression" and state.observation == 2:
            value["application"]["received_controls"] = 1
        if state.observation == 3:
            if change in {"service_incarnation", "profile_incarnation", "logical_session", "resource", "adapter_epoch"}:
                value[change] = "PRIVATE_OTHER"
            elif change == "pair": value["pair"]["token"] = "f" * 32
            elif change == "sequence": value["sample_sequence"] = 2
            elif change == "regression": value["application"]["received_controls"] = 0
            else: value["application"]["received_packets"] = 0
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as caught:
        state.controller.path_case("turn_udp", "windows")
    expected = {"scenario": "turn_udp", "stage": "final_traffic", "reason": reason}
    if fields is not None: expected["fields"] = fields
    assert state.controller.failure_final_evidence(caught.value) == {"final_evidence_failure": expected}
    assert "PRIVATE" not in json.dumps(expected)
    assert state.observation == 3 and state.actions == [] and not state.markers


@pytest.mark.parametrize("broken", ["classifier", "validator"])
def test_final_traffic_projection_failure_preserves_exact_primary_error(monkeypatch, sample, broken):
    state = retirement_case(monkeypatch, sample, role="android")
    failure = ValueError("PRIVATE_TRAFFIC_ERROR")
    def fail_traffic(*_args): raise failure
    monkeypatch.setattr(controller, "traffic", fail_traffic)
    if broken == "classifier":
        monkeypatch.setattr(controller, "traffic_failure_details", lambda *_: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_PROJECTION_ERROR")))
    else:
        monkeypatch.setattr(controller, "traffic_failure_details", lambda *_: {"reason": "selected_pair_changed"})
        monkeypatch.setattr(controller, "final_evidence_failure_observation", lambda *_: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_PROJECTION_ERROR")))
    with pytest.raises(ValueError) as caught:
        state.controller.path_case("turn_udp", "windows")
    assert caught.value is failure and state.controller.failure_final_evidence(failure) == {}


def test_final_evidence_projection_rejects_untrusted_or_stale_private_fields(monkeypatch, sample):
    from native_interop_diagnostics import final_evidence_failure_observation
    for value in ({"scenario": "turn_udp", "stage": "final_traffic", "reason": "counter_regression",
                   "fields": ["PRIVATE_COUNTER"]},
                  {"scenario": "turn_udp", "stage": "final_observation", "reason": "path_missing",
                   "skip_reason": "PRIVATE_ENDPOINT"},
                  {"scenario": "turn_udp", "stage": "final_traffic", "reason": [], "fields": []}):
        assert final_evidence_failure_observation(value) is None
    state = retirement_case(monkeypatch, sample)
    error = ValueError("PRIVATE_ERROR")
    state.controller.phase = "turn_udp_authenticated_receipts"
    state.controller._final_evidence_failure = error, state.controller.phase, state.controller.pairing, {
        "scenario": "turn_udp", "stage": "final_traffic", "reason": "PRIVATE_REASON"}
    assert state.controller.failure_final_evidence(error) == {}
    state.controller._final_evidence_failure = error, "direct_authenticated_receipts", state.controller.pairing, {
        "scenario": "turn_udp", "stage": "final_traffic", "reason": "selected_pair_changed"}
    assert state.controller.failure_final_evidence(error) == {}


@pytest.mark.parametrize("broken_projection", [False, True])
def test_actual_turn_udp_failure_report_contains_only_fixed_final_traffic_attribution(
        tmp_path, monkeypatch, capsys, sample, broken_projection):
    import connection_ci
    state = retirement_case(monkeypatch, sample, role="android")
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3: value["application"]["received_packets"] = 0
        return value
    state.controller.observe = observe
    peer = state.controller.peer
    peer.process = SimpleNamespace(pid=17)
    peer.stop = lambda **_kwargs: setattr(peer, "process", None)
    state.controller.run = lambda: state.controller.path_case("turn_udp", "windows")
    if broken_projection:
        def broken(*_args): raise RuntimeError("PRIVATE_PROJECTION_ERROR")
        state.controller.failure_final_evidence = broken
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: state.controller)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *args, **kwargs: None,
        close=lambda: None))
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    captured = capsys.readouterr()
    report = json.loads(output.read_text())
    assert report["phase"] == "turn_udp_authenticated_receipts"
    assert report["failure_type"] == "ValueError"
    if broken_projection:
        assert "final_evidence_failure" not in report
    else:
        assert report["final_evidence_failure"] == {"scenario": "turn_udp", "stage": "final_traffic",
            "reason": "required_delta_missing", "fields": ["received_packets"]}
    assert "PRIVATE" not in output.read_text() + captured.out + captured.err


def test_prepared_case_publishes_completion_before_committing_same_request(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    state.controller.path_case("direct", "windows")
    assert state.actions == ["prepare", "commit"]
    assert state.markers == [("publish", "case_complete_direct_windows", {"completed": True}),
                             ("receive", "case_complete_direct_windows", 180)]
    assert len(state.requests) == 1 and state.controller.cases[-1]["owner_retirement_acknowledged"] is True


def test_optional_path_diagnostic_constructor_failure_preserves_successful_direct_case(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    def unavailable(_scenario): raise RuntimeError("PRIVATE_DIAGNOSTIC_ERROR")
    monkeypatch.setattr(controller, "NativePathDiagnostics", unavailable)
    state.controller.path_case("direct", "windows")
    assert state.controller._path_diagnostics is None
    assert state.actions == ["prepare", "commit"] and len(state.controller.cases) == 1
    assert state.controller.cases[0]["scenario"] == "direct"


def test_optional_path_diagnostic_constructor_failure_preserves_original_receipt_error(monkeypatch, sample):
    state = retirement_case(monkeypatch, sample)
    original = ValueError("PRIVATE_RECEIPT_ERROR")
    def unavailable(_scenario): raise RuntimeError("PRIVATE_DIAGNOSTIC_ERROR")
    def exchange(*_args, **_kwargs): raise original
    monkeypatch.setattr(controller, "NativePathDiagnostics", unavailable)
    state.controller.exchange = exchange
    with pytest.raises(ValueError) as caught: state.controller.path_case("direct", "windows")
    assert caught.value is original and state.controller.phase == "direct_authenticated_receipts"
    assert state.controller._path_diagnostics is None and state.actions == []


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
        assert seconds == 0.1 or 0 < seconds <= 0.25 + 1e-9
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
        protocol, socket = ("udp" if scenario == "impaired" else "tcp"), {"PRIVATE_SOCKET": "PRIVATE_ADDRESS"}
        endpoint_mode = False
        uid_udp_mode = scenario == "impaired"
        target_kind, target_material, rule_count = (
            "uid_udp_all_destinations" if scenario == "impaired" else "uid_tcp_turn_destination_set",
            {"PRIVATE_SOCKET": "PRIVATE_ADDRESS"}, 2 if scenario == "impaired" else 1)
        def require_current(self): pass
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
    instance._prepare_negative_control = lambda _: SimpleNamespace(
        send=lambda stage: instance.publish("negative_" + stage + "_" + scenario, {"approved": True}),
        receive=lambda stage, **_: instance.receive("negative_" + stage + "_" + scenario) == {"approved": True})
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation >= 3 and state.point == "path_missing": return None
        if state.observation == 3:
            if state.point == "final_observation_error": raise state.boundary_error
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


def test_final_path_miss_reports_only_allowlisted_unavailable_for_unsampled_wrapper(
        tmp_path, monkeypatch, capsys, sample):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point="path_missing")
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["negative_control"] == {
        "scenario": "turn_tcp", "stage": "final_observation", "reason": "path_missing"}
    assert run.record["final_path_missing"] == "unavailable"
    assert "PRIVATE" not in run.output and not run.state.requests
    assert run.state.controller.failure_final_path(ValueError("PRIVATE_FOREIGN")) == {}
    run.state.controller._final_path_failure = run.state.escaping_error, "PRIVATE_FORGED"
    assert run.state.controller.failure_final_path(run.state.escaping_error) == {}


def test_final_path_miss_explanation_does_not_survive_cleanup_replacement(
        tmp_path, monkeypatch, capsys, sample):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample,
        point="path_missing", cleanup_error=True)
    assert run.record["failure_type"] == "RuntimeError"
    assert run.record["negative_control"] == {"scenario": "turn_tcp", "stage": "fault_cleanup"}
    assert "final_path_missing" not in run.record
    assert run.state.controller.failure_final_path(run.state.escaping_error) == {}


def test_impaired_setup_error_stays_primary_when_exact_cleanup_retry_fails(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="impaired")
    setup = ValueError("PRIVATE_SETUP")
    cleanup = RuntimeError("PRIVATE_CLEANUP")
    state.kernel._setup_cleanup_failure = cleanup
    def fail_setup(): raise setup
    def fail_cleanup(): raise cleanup
    state.kernel.install = fail_setup
    state.kernel.close = fail_cleanup
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("impaired", "windows")
    assert failure.value is setup and failure.value.__cause__ is cleanup


@pytest.mark.parametrize("mode", ["observe", "projection", "malformed", "forged_projection"])
def test_final_path_miss_observer_fault_or_forgery_cannot_publish_private_data(
        tmp_path, monkeypatch, capsys, sample, mode):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample,
        point="path_missing", observer_mode=mode)
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert "final_path_missing" not in run.record
    assert "PRIVATE" not in run.output


def test_final_path_miss_collector_failure_keeps_original_error(tmp_path, monkeypatch, capsys, sample):
    def broken(_reasons): raise RuntimeError("PRIVATE_COLLECTOR")
    monkeypatch.setattr(controller, "final_path_missing_reason", broken)
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point="path_missing")
    assert run.code == 1 and run.record["failure_type"] == "ValueError"
    assert run.record["negative_control"]["reason"] == "path_missing"
    assert run.record["final_path_missing"] == "unavailable"
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("poison", [None, False, 0, [], {}, "PRIVATE_PATH", ""])
def test_final_path_miss_projection_rejects_unapproved_values(poison):
    from native_interop_diagnostics import final_path_missing_observation
    assert final_path_missing_observation(poison) is None


def test_other_negative_failure_has_no_final_path_explanation(tmp_path, monkeypatch, capsys, sample):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample, point="zero_drop")
    assert run.code == 1 and run.record["negative_control"]["stage"] == "dropped_count"
    assert "final_path_missing" not in run.record


def test_successful_case_clears_prior_final_path_explanation_without_changing_retirement(
        monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success")
    stale = ValueError("PRIVATE_STALE")
    state.controller._final_path_failure = stale, "no_resource"
    state.controller.path_case("turn_tcp", "windows")
    assert state.controller._final_path_failure is None
    assert state.controller.failure_final_path(stale) == {}
    assert state.controller.cases[-1]["owner_retirement_acknowledged"] is True
    assert "final_path_missing" not in state.controller.cases[-1]


@pytest.mark.parametrize("scenario", ["turn_tcp", "turn_tls", "impaired"])
def test_final_ready_recovers_inside_original_restored_delivery_window(monkeypatch, sample, scenario):
    if scenario == "impaired": sample[0]["pair"]["rtt_ms"] = 10
    state = negative_control_case(monkeypatch, sample, point="success", scenario=scenario)
    original = state.controller.observe
    final_reads = []
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation >= 3:
            final_reads.append(state.now)
            if len(final_reads) == 1:
                kwargs["missing_reasons"].add("messaging_ready_not_true")
                return None
        return value
    state.controller.observe = observe
    state.controller.path_case(scenario, "windows")
    assert len(final_reads) == 2 and final_reads[1] - final_reads[0] == pytest.approx(0.25)
    assert state.controller.cases[-1]["negative"]["delivered_after_restore"] is True
    assert state.controller.cases[-1]["owner_retirement_acknowledged"] is True


@pytest.mark.parametrize("scenario", ["turn_tls", "impaired"])
def test_final_ready_persistent_unready_uses_last_reason_and_existing_deadline(monkeypatch, sample, scenario):
    state = negative_control_case(monkeypatch, sample, point="success", scenario=scenario)
    state.controller.deadline = 2.5
    original = state.controller.observe
    final_reads = []
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation >= 3:
            final_reads.append(state.now)
            kwargs["missing_reasons"].add("messaging_ready_not_true")
            return None
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as failure:
        state.controller.path_case(scenario, "windows")
    assert state.controller.failure_final_path(failure.value) == {
        "final_path_missing": "messaging_ready_not_true"}
    assert final_reads == [pytest.approx(2.0), pytest.approx(2.25)]
    assert state.now == pytest.approx(2.5) and not state.requests


def test_final_ready_budget_expired_before_snapshot_does_not_probe(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="turn_tls")
    state.kernel.endpoint_mode = True
    state.kernel.require_current = lambda: setattr(state, "now", 92.01)
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("turn_tls", "windows")
    assert state.controller.failure_final_path(failure.value) == {"final_path_missing": "unavailable"}
    assert state.observation == 2 and not state.requests


@pytest.mark.parametrize("scenario", ["turn_tls", "impaired"])
def test_restored_receipt_and_inbound_share_one_ninety_second_deadline(monkeypatch, sample, scenario):
    if scenario == "impaired": sample[0]["pair"]["rtt_ms"] = 10
    state = negative_control_case(monkeypatch, sample, point="success", scenario=scenario)
    original_core = state.controller.peer.core
    original_observe = state.controller.observe
    original_wait = state.controller.wait
    delayed, waits, final_reads = [False], [], []
    def core(operation, params, key=None):
        if operation == "message.query" and state.restored and not delayed[0]:
            delayed[0] = True
            state.now += 89
        return original_core(operation, params, key)
    def observe(*args, **kwargs):
        value = original_observe(*args, **kwargs)
        if state.observation >= 3:
            final_reads.append(state.now)
            if len(final_reads) == 1:
                kwargs["missing_reasons"].add("messaging_ready_not_true")
                return None
        return value
    def wait(action, **kwargs):
        waits.append(kwargs["timeout"])
        return original_wait(action, **kwargs)
    state.controller.peer.core = core
    state.controller.observe = observe
    state.controller.wait = wait
    state.controller.path_case(scenario, "windows")
    assert waits[3] == pytest.approx(90)
    assert waits[4] == pytest.approx(1)
    assert len(final_reads) == 2 and final_reads[-1] < 92


@pytest.mark.parametrize("scenario", ["turn_tls", "impaired"])
def test_ready_sample_returned_after_restoration_deadline_is_not_accepted(monkeypatch, sample, scenario):
    state = negative_control_case(monkeypatch, sample, point="success", scenario=scenario)
    if scenario == "turn_tls": state.kernel.endpoint_mode = True
    state.kernel.require_current = lambda: setattr(state, "now", 91.9)
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3: state.now = 92.1
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as failure:
        state.controller.path_case(scenario, "windows")
    assert state.controller.failure_final_path(failure.value) == {"final_path_missing": "unavailable"}
    assert state.observation == 3 and not state.requests


def test_final_ready_probe_error_after_unready_preserves_original_exception(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="turn_tls")
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3:
            kwargs["missing_reasons"].add("messaging_ready_not_true")
            return None
        if state.observation == 4: raise state.boundary_error
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("turn_tls", "windows")
    assert failure.value is state.boundary_error
    assert state.controller.failure_negative_control(failure.value) == {
        "negative_control": {"scenario": "turn_tls", "stage": "final_observation"}}
    assert state.controller.failure_final_path(failure.value) == {}


def test_final_ready_rechecks_current_endpoint_scope_after_wait(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="turn_tls")
    state.kernel.endpoint_mode = True
    checks = []
    def require_current():
        checks.append(state.observation)
        if state.observation >= 3: raise state.boundary_error
    state.kernel.require_current = require_current
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3:
            kwargs["missing_reasons"].add("messaging_ready_not_true")
            return None
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("turn_tls", "windows")
    assert failure.value is state.boundary_error and checks == [2, 4]
    assert state.controller.failure_negative_control(failure.value) == {
        "negative_control": {"scenario": "turn_tls", "stage": "kernel_restore_current"}}
    assert not state.requests


def test_final_ready_does_not_start_scope_probe_after_budget_expiry(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="turn_tls")
    state.kernel.endpoint_mode = True
    checks = []
    state.kernel.require_current = lambda: checks.append(state.observation)
    original = state.controller.final_ready_observation
    def final_ready(*args):
        value = original(*args)
        state.now = 92.01
        return value
    state.controller.final_ready_observation = final_ready
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("turn_tls", "windows")
    assert state.controller.failure_final_path(failure.value) == {"final_path_missing": "unavailable"}
    assert checks == [2] and not state.requests


@pytest.mark.parametrize("change", ["resource", "epoch", "pair", "counters"])
def test_final_ready_recovery_still_rejects_changed_identity_or_counters(monkeypatch, sample, change):
    state = negative_control_case(monkeypatch, sample, point="success", scenario="turn_tls")
    original = state.controller.observe
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        if state.observation == 3:
            kwargs["missing_reasons"].add("messaging_ready_not_true")
            return None
        if state.observation == 4:
            if change == "resource": value["resource"] = "PRIVATE_OTHER_RESOURCE"
            elif change == "epoch": value["adapter_epoch"] = "f" * 32
            elif change == "pair": value["pair"]["token"] = "f" * 32
            else: value["application"] = dict.fromkeys(evidence.APPLICATION, 0)
        return value
    state.controller.observe = observe
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("turn_tls", "windows")
    assert state.controller.failure_negative_control(failure.value) == {
        "negative_control": {"scenario": "turn_tls", "stage": "final_traffic"}}
    reason, fields = {
        "resource": ("native_identity_changed", ["resource"]),
        "epoch": ("native_identity_changed", ["adapter_epoch"]),
        "pair": ("selected_pair_changed", None),
        "counters": ("required_delta_missing", ["enqueued_packets", "enqueued_bytes",
            "received_packets", "received_bytes"]),
    }[change]
    selected = {"scenario": "turn_tls", "stage": "final_traffic", "reason": reason}
    if fields is not None: selected["fields"] = fields
    assert state.controller.failure_final_evidence(failure.value) == {"final_evidence_failure": selected}
    assert not state.requests


def test_final_ready_recovery_propagates_stale_native_sample(path_observer):
    state = path_observer
    state.value["pair"]["relay_protocol"] = "tls"
    state.controller.observe("logical", ready=True, scenario="turn_tls")
    state.value["messaging_ready"] = False
    def resume_with_stale_sequence():
        state.value["messaging_ready"] = True
        state.sequence = 0
    state.on_sleep = resume_with_stale_sequence
    with pytest.raises(ValueError) as failure:
        state.controller.final_ready_observation("logical", "turn_tls", state.now + 1)
    assert state.controller.samples.failure_reason(failure.value) == "sample_replay"
    assert len(state.challenges) == 3


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


def test_impaired_cleanup_preserves_primary_and_reports_fixed_cleanup_failure(
        tmp_path, monkeypatch, capsys, sample):
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample,
        scenario="impaired", point="receipt", cleanup_error=True)
    assert run.code == 1 and run.state.escaping_error is run.state.primary_error
    assert run.state.escaping_error is not run.state.cleanup_exception
    assert run.record["failure_type"] == "ValueError"
    assert run.record["negative_control"] == {"scenario": "impaired", "stage": "blocked_receipt",
                                              "reason": "receipt_while_blocked"}
    assert run.record["kernel_cleanup_failure"] == {"scenario": "impaired", "stage": "fault_cleanup",
                                                    "reason": "cleanup_incomplete"}
    assert run.record["cleanup_failed"] is True and "PRIVATE" not in run.output
    assert run.state.controller.failure_kernel_cleanup(run.state.cleanup_exception) == {}


def test_kernel_cleanup_projection_ignores_foreign_or_broken_private_record(monkeypatch, sample):
    state = negative_control_case(monkeypatch, sample, scenario="impaired", point="receipt",
                                  cleanup_error=True)
    with pytest.raises(ValueError) as failure:
        state.controller.path_case("impaired", "windows")
    assert failure.value is not state.cleanup_exception
    state.controller._fault_cleanup_failure = (RuntimeError("PRIVATE_FOREIGN"),
        {"scenario": "impaired", "stage": "fault_cleanup", "reason": "cleanup_incomplete"})
    assert state.controller.failure_kernel_cleanup(failure.value) == {}
    state.controller._fault_cleanup_failure = (failure.value, {"socket": "PRIVATE_SOCKET"})
    assert state.controller.failure_kernel_cleanup(failure.value) == {}


def test_impaired_cleanup_only_failure_remains_the_primary_error(tmp_path, monkeypatch, capsys, sample):
    sample[0]["pair"]["rtt_ms"] = 10
    run = run_negative_control_report(tmp_path, monkeypatch, capsys, sample,
        scenario="impaired", point="success", cleanup_error=True)
    assert run.code == 1 and run.state.escaping_error is run.state.cleanup_exception
    assert run.record["failure_type"] == "RuntimeError"
    assert run.record["negative_control"] == {"scenario": "impaired", "stage": "fault_cleanup"}
    assert "kernel_cleanup_failure" not in run.record and "PRIVATE" not in run.output


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


def readiness_case(state, *, scenario="turn_tls", initiator="windows"):
    instance = state.controller
    state.value["pair"]["relay_protocol"] = "tls"
    instance.contact = {"id": "PRIVATE_CONTACT"}
    instance.pairing = "PRIVATE_PAIRING"
    def negotiate(*_):
        instance.phase = scenario + "_supervisor_owned_pairing_" + initiator
        return "logical", None
    instance.negotiate = negotiate
    instance.peer.pairing_status = lambda operation: {"operation_id": operation, "state": "transferred"}
    return instance


def test_readiness_denial_keeps_original_error_and_exact_adopted_stage(path_observer):
    state = path_observer
    instance = readiness_case(state)
    state.inventory["resources"][0]["owner_state"] = "unavailable"
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value is state.error
    assert instance.failure_observation(caught.value) == {"failure_substage": "path_read"}
    assert instance.failure_readiness(caught.value) == {"readiness_observation": {
        "scenario": "turn_tls", "stage": "adopted_observation", "polls": 1,
        "polls_capped": False, "resource_count": 1, "resources_capped": False,
        "owner_state": "unavailable", "adopted": True, "skip_reason": "none"}}
    assert state.events == ["inventory", ("path", "logical", "physical")]
    assert instance.failure_readiness(controller.PeerFailure("contact_not_approved")) == {}
    instance.phase = "turn_udp_supervisor_owned_pairing_windows"
    assert instance.failure_readiness(caught.value) == {}


def test_unadopted_readiness_timeout_retains_exact_inventory_and_skip(path_observer):
    state = path_observer
    instance = readiness_case(state)
    state.inventory["resources"][0].update(owner_state="unadopted", adopted=False)
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value.code == "scenario_deadline"
    value = instance.failure_readiness(caught.value)["readiness_observation"]
    assert value["owner_state"] == "unadopted" and value["adopted"] is False
    assert value["skip_reason"] == "adopted_not_true" and value["polls"] == 128
    assert value["polls_capped"] is True and state.now == 130
    assert state.events == ["inventory"] * 480


def test_readiness_denial_after_cancel_has_distinct_outer_stage(path_observer):
    state = path_observer
    instance = readiness_case(state)
    def cancel(operation):
        state.error = controller.PeerFailure("contact_not_approved")
        return {"operation_id": operation, "state": "transferred"}
    instance.peer.pairing_cancel = cancel
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value is state.error
    assert instance.failure_readiness(caught.value)["readiness_observation"]["stage"] == "post_cancel_observation"
    assert instance.failure_observation(caught.value) == {"failure_substage": "path_read"}
    assert state.events == ["inventory", ("path", "logical", "physical"),
                            "inventory", ("path", "logical", "physical")]


def test_readiness_pending_deadline_caps_polls_without_extra_path_rpc(path_observer):
    state = path_observer
    instance = readiness_case(state)
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value.code == "scenario_deadline"
    assert instance.failure_readiness(caught.value) == {"readiness_observation": {
        "scenario": "turn_tls", "stage": "adopted_observation", "polls": 128,
        "polls_capped": True, "resource_count": 1, "resources_capped": False,
        "owner_state": "pending_adoption", "adopted": True, "skip_reason": "pending_adoption"}}
    assert state.now == 130 and state.sleeps == [0.25] * 480
    assert state.events == ["inventory"] * 480


@pytest.mark.parametrize("kind,skip,reads", [
    ("missing", "no_resource", 0), ("unready", "adopted_not_true", 2),
])
def test_readiness_failure_distinguishes_missing_resource_from_unready_path(
        path_observer, kind, skip, reads):
    state = path_observer
    instance = readiness_case(state)
    instance.negotiate("turn_tls", "windows")
    if kind == "missing":
        state.inventory["resources"] = []
    else:
        state.value["adopted"] = False
    with pytest.raises(controller.PeerFailure) as caught:
        with instance._readiness_scope("adopted_observation", "turn_tls", "logical"):
            with instance._substage("adopted_observation"):
                instance.wait(lambda: instance.observe("logical", scenario="turn_tls"), timeout=.5)
    assert caught.value.code == "scenario_deadline"
    value = instance.failure_readiness(caught.value)["readiness_observation"]
    assert value["resource_count"] == (0 if kind == "missing" else 1)
    assert value["skip_reason"] == skip and value["polls"] == 2
    assert len(state.challenges) == reads and len(state.sleeps) == 2


def test_broken_readiness_projection_cannot_replace_original_denial(path_observer, monkeypatch):
    state = path_observer
    instance = readiness_case(state)
    state.error = controller.PeerFailure("contact_not_approved")
    monkeypatch.setattr(controller, "readiness_failure_snapshot", lambda _: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_OBSERVER_ERROR")))
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value is state.error and instance.failure_readiness(caught.value) == {}
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("mismatch", ["logical", "scenario"])
def test_foreign_observe_inside_same_wait_cannot_inherit_prior_readiness_evidence(path_observer, mismatch):
    state = path_observer
    instance = readiness_case(state)
    instance.negotiate("turn_tls", "windows")
    state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        with instance._readiness_scope("adopted_observation", "turn_tls", "logical"):
            assert instance.observe("logical", scenario="turn_tls") is None
            state.inventory["resources"][0]["owner_state"] = "unavailable"
            if mismatch == "logical":
                state.inventory["resources"][0]["logical_session"] = "PRIVATE_FOREIGN"
            instance.observe("PRIVATE_FOREIGN" if mismatch == "logical" else "logical",
                             scenario="turn_udp" if mismatch == "scenario" else "turn_tls")
    assert caught.value is state.error
    assert instance.failure_readiness(caught.value) == {}
    assert state.events == ["inventory", "inventory", ("path", "PRIVATE_FOREIGN" if mismatch == "logical" else "logical", "physical")]


@pytest.mark.parametrize("resources,owner,adopted", [
    (2, "unknown", None), (1, "unknown", None),
])
def test_readiness_denial_fails_closed_for_ambiguous_or_malformed_inventory(
        path_observer, resources, owner, adopted):
    state = path_observer
    instance = readiness_case(state)
    if resources == 2:
        state.inventory["resources"].append(dict(state.inventory["resources"][0],
            physical_resource="PRIVATE_OTHER"))
    else:
        state.inventory["resources"][0].update(owner_state={"PRIVATE": "STATE"},
                                                adopted="PRIVATE_ADOPTION")
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        instance.path_case("turn_tls", "windows")
    assert caught.value is state.error
    value = instance.failure_readiness(caught.value)["readiness_observation"]
    assert value["resource_count"] == resources and value["owner_state"] == owner
    assert value["adopted"] is adopted and "PRIVATE" not in json.dumps(value)
    assert state.events[:2] == ["inventory", ("path", "logical", "physical")]


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


@pytest.mark.parametrize("kind", ["no_resource", "pending_adoption"])
def test_final_path_miss_uses_existing_inventory_without_path_rpc(path_observer, kind):
    state, reasons = path_observer, set()
    if kind == "no_resource": state.inventory["resources"][0]["logical_session"] = "PRIVATE_OTHER"
    else: state.inventory["resources"][0]["owner_state"] = "pending_adoption"
    assert state.controller.observe("logical", ready=True, scenario="turn_tcp", missing_reasons=reasons) is None
    assert reasons == {kind} and state.events == ["inventory"] and state.challenges == []


@pytest.mark.parametrize("readiness,expected", [
    ({"adopted": False, "attached": False, "messaging_ready": False}, "adopted_not_true"),
    ({"attached": False, "messaging_ready": False}, "attached_not_true"),
    ({"messaging_ready": False}, "messaging_ready_not_true"),
    ({"status": "PRIVATE_OTHER"}, "nonselected"),
])
def test_final_path_miss_uses_first_existing_skip_and_short_circuit(
        path_observer, readiness, expected):
    state, reasons, reads = path_observer, set(), []
    class ReadTrace(dict):
        def __deepcopy__(self, memo): return self
        def get(self, key, default=None):
            if key in {"adopted", "attached", "messaging_ready", "status"}: reads.append(key)
            return super().get(key, default)
    state.value = ReadTrace(state.value)
    state.value.update(readiness)
    assert state.controller.observe("logical", ready=True, scenario="turn_tcp", missing_reasons=reasons) is None
    expected_reads = ["adopted"]
    if expected != "adopted_not_true": expected_reads.append("attached")
    if expected not in {"adopted_not_true", "attached_not_true"}: expected_reads.append("messaging_ready")
    if expected == "nonselected": expected_reads.append("status")
    assert reads == expected_reads and reasons == {expected}
    assert state.events == ["inventory", ("path", "logical", "physical")]
    assert len(state.challenges) == 1 and state.controller.samples.previous == {}


def test_final_path_miss_mixed_from_same_two_path_reads(path_observer):
    state, reasons = path_observer, set()
    state.inventory["resources"].append(dict(logical_session="logical", physical_resource="PRIVATE_SECOND",
        owner_state="authorized"))
    original_path = state.controller.peer.path
    def path(logical, physical, challenge):
        value = original_path(logical, physical, challenge)
        if physical == "physical": value["adopted"] = False
        else: value["status"] = "PRIVATE_OTHER"
        return value
    state.controller.peer.path = path
    assert state.controller.observe("logical", ready=True, scenario="turn_tcp", missing_reasons=reasons) is None
    assert reasons == {"adopted_not_true", "nonselected"}
    assert state.events == ["inventory", ("path", "logical", "physical"),
        ("path", "logical", "PRIVATE_SECOND")]
    assert len(state.challenges) == 2 and state.controller.samples.previous == {}


@pytest.mark.parametrize("different", [False, True])
def test_final_path_miss_aggregates_at_most_two_distinct_reasons(path_observer, different):
    from native_interop_diagnostics import final_path_missing_reason
    state, reasons = path_observer, set()
    state.inventory["resources"].extend([
        dict(logical_session="logical", physical_resource="PRIVATE_SECOND", owner_state="authorized"),
        dict(logical_session="logical", physical_resource="PRIVATE_THIRD", owner_state="authorized")])
    original_path = state.controller.peer.path
    def path(logical, physical, challenge):
        value = original_path(logical, physical, challenge)
        if physical == "PRIVATE_SECOND" and different: value["attached"] = False
        elif physical == "PRIVATE_THIRD" and different: value["status"] = "PRIVATE_OTHER"
        else: value["adopted"] = False
        return value
    state.controller.peer.path = path
    assert state.controller.observe("logical", ready=True, scenario="turn_tcp", missing_reasons=reasons) is None
    assert reasons == ({"adopted_not_true", "attached_not_true"} if different else {"adopted_not_true"})
    assert final_path_missing_reason(reasons) == ("mixed" if different else "adopted_not_true")
    assert state.events == ["inventory", ("path", "logical", "physical"),
        ("path", "logical", "PRIVATE_SECOND"), ("path", "logical", "PRIVATE_THIRD")]
    assert len(state.challenges) == 3


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
        pending = (fault in {"approval_ready_observation", "adopted_report"}
            or (fault == "adopted_observation" and state.challenges)
            or (fault in {"post_cancel_observation", "post_cancel_report"} and state.cancelled))
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
        if fault in {"adopted_report", "post_cancel_report"}:
            instance.contact = contact
            def negotiate(*_):
                instance.phase = "direct_supervisor_owned_pairing_windows"
                return "logical", None
            instance.negotiate = negotiate
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


@pytest.mark.parametrize("fault,stage", [("adopted_report", "adopted_observation"),
                                        ("post_cancel_report", "post_cancel_observation")])
def test_actual_failure_report_adds_only_bounded_exact_readiness_context(
        tmp_path, monkeypatch, capsys, path_observer, fault, stage):
    run = run_approval_report(tmp_path, monkeypatch, capsys, path_observer, "windows", fault)
    assert run.code == 1 and run.record["error_code"] == "scenario_deadline"
    assert run.record["phase"] == "direct_supervisor_owned_pairing_windows"
    assert run.record["failure_substage"] == stage
    assert run.record["readiness_observation"] == {
        "scenario": "direct", "stage": stage, "polls": 128, "polls_capped": True,
        "resource_count": 1, "resources_capped": False, "owner_state": "pending_adoption",
        "adopted": True, "skip_reason": "pending_adoption"}
    assert len(run.state.sleeps) == 480
    assert "PRIVATE_" not in run.output and "logical" not in json.dumps(run.record["readiness_observation"])


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
        assert not {"failure_site", "pairing_state", "pairing_retirement", "failure_substage", "sample_rejection_reason",
                    "readiness_observation"} & set(run.record)
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


@pytest.mark.parametrize("suffix,detail", [
    ("device offline", "device_offline"),
    ("device offline (no transport)", "no_transport"),
    ("device offline (transport offline)", "transport_offline"),
    ("device still connecting", "device_connecting"),
    ("device still authorizing", "device_authorizing"),
    ("closed", "connection_closed"),
    ("failed to read transport id from server", "transport_id_read_failed"),
])
def test_actual_root_connect_failure_retains_only_fixed_detail(tmp_path, monkeypatch, capsys, suffix, detail):
    run = run_android_preflight_report(tmp_path, monkeypatch, capsys, site="android_root",
        failure_stderr=("adb: unable to connect for root: " + suffix + "\n").encode())
    assert run.exit_code == 1 and run.record["passed"] is False
    assert run.record["preflight_root_reason"] == "connect_failure"
    assert run.record.get("preflight_root_connect_detail") == detail
    assert run.script.calls == ["android_devices", "android_avd_create", "boot", "android_root", "kill"]
    assert run.events == [] and "PRIVATE_" not in run.output and "adb:" not in run.output
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
        "failure_type", "preflight_failure_site", "preflight_exit_status", "preflight_root_reason",
        "android_system_observation"}
    assert_empty_system_observation(run.record)
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
              "preflight_failure_site", "preflight_exit_status", "android_system_observation"}
    assert record["preflight_exit_status"] == 1
    if site == "android_root":
        fields.add("preflight_root_reason")
        assert record["preflight_root_reason"] == "unclassified"
    assert set(record) == fields
    assert_empty_system_observation(record)
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
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "phase", "failure_type",
              "android_system_observation"}
    if expected_type == "PeerFailure":
        fields.add("error_code")
        assert run.record["error_code"] == "invalid_request"
    assert set(run.record) == fields
    assert_empty_system_observation(run.record)
    assert "controller" not in run.events and "PRIVATE_" not in run.output
    assert not run.script.emulator.root.exists() and run.script.emulator.process is None


def assert_empty_system_observation(record):
    """An empty console cannot supply a guest cause for a preflight error."""
    observed = record["android_system_observation"]
    assert set(observed) == {"v", "counts", "events", "events_dropped", "oversized_lines",
                            "counters_saturate_at", "reader_eof", "reader_failed", "classifier_failed"}
    assert observed["events"] == [] and all(n == 0 for n in observed["counts"].values())
    assert observed["events_dropped"] == observed["oversized_lines"] == 0
    assert observed["reader_failed"] is observed["classifier_failed"] is False
    assert type(observed["reader_eof"]) is bool
    assert observed["v"] == 1 and observed["counters_saturate_at"] == 65535


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
                negative = {"blocked_packets": 2 if role == "android" else None,
                    "block_operation_ms": 3000 if role == "android" else None, "delivered_while_blocked": False,
                    "delivered_after_restore": True, "kernel_protocol": ("udp" if name == "impaired" else "tcp") if role == "android" else None,
                    "kernel_target": {"kind": "uid_udp_all_destinations" if name == "impaired" else "uid_tcp_turn_destination_set",
                        "digest": evidence.digest([name, "kernel target"]), "rule_count": 2 if name == "impaired" else 1} if role == "android" else None,
                    "outbound": message("negative:" + name, role)["outbound"], "inbound": message("negative:" + name, role)["inbound"]}
            impairment = None
            if name == "impaired" and role == "android":
                impairment = {"kind": "android_emulator_host_gateway_tc_netem", "delay_ms_each_way": 75,
                    "jitter_ms_each_way": 10, "loss_percent_each_way": 0.1, "added_nominal_rtt_ms": 150,
                    "link_scope": "owned_host_namespace_veth", "loss_observed": False,
                    "counters": {direction: {"bytes": 1000, "packets": 10, "dropped": 0} for direction in ("egress", "ingress")},
                    "gateway_coverage": {"external_links": 1, "namespace_bound": True,
                        "ipv6_disabled": True, "veth_identity_current": True,
                        "directional_veth_packets": {"egress": 10, "ingress": 10}}}
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
        if role == "android":
            result[-1]["execution"]["host_gateway"] = {"kind": "owned_linux_network_namespace",
                "cleanup": "passed", "helpers_retired": True}
    return tuple(result)


def test_complete_two_role_fixture_is_accepted_only_with_cross_matching_actual_message_identities():
    windows, android = interop_reports()
    assert evidence.verify_pair(windows, android, "a" * 40, "b" * 40) == (windows, android)


@pytest.mark.parametrize("change", ["wrong_kind", "zero_rules", "raw_address", "old_socket_name"])
def test_tcp_negative_artifact_requires_neutral_bounded_endpoint_target(change):
    windows, android = interop_reports()
    case = next(item for item in android["execution"]["scenarios"] if item["scenario"] == "turn_tcp")
    negative = case["negative"]
    if change == "wrong_kind": negative["kernel_target"]["kind"] = "pid_udp_socket_flow"
    elif change == "zero_rules": negative["kernel_target"]["rule_count"] = 0
    elif change == "raw_address": negative["kernel_target"]["address"] = "198.51.100.2"
    else: negative["kernel_socket"] = negative.pop("kernel_target")
    with pytest.raises(ValueError):
        evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


@pytest.mark.parametrize("change", ["extra_resource", "wrong_owner", "extra_lease", "new_profile"])
def test_endpoint_scope_requires_one_current_authorized_native_resource(change):
    before = {"logical_session": "logical", "resource": "physical",
        "service_incarnation": "a" * 32, "profile_incarnation": "b" * 32}
    inventory = {"service_incarnation": before["service_incarnation"],
        "profile_incarnation": before["profile_incarnation"],
        "resources": [{"logical_session": "logical", "physical_resource": "physical",
            "adopted": True, "owner_state": "authorized"}],
        "host_accounting": {"v": 1, "complete": True, "semantics": "native_allocation_leases",
            "availability": dict.fromkeys(evidence.ACCOUNTING, True), "capacity": 16,
            "reserved_count": 1, "creating_count": 0, "allocated_count": 1,
            "active_count": 1, "retiring_count": 0}}
    instance = controller.Controller("android", SimpleNamespace(inventory=lambda: inventory), None, None, {})
    assert instance.endpoint_resource_current(before) is True
    if change == "extra_resource": inventory["resources"].append(dict(inventory["resources"][0]))
    elif change == "wrong_owner": inventory["resources"][0]["owner_state"] = "pending_adoption"
    elif change == "extra_lease": inventory["host_accounting"].update(reserved_count=2, allocated_count=2, active_count=2)
    else: inventory["profile_incarnation"] = "c" * 32
    assert instance.endpoint_resource_current(before) is False


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


@pytest.mark.parametrize("change", ["missing", "extra", "overbound", "wrong_count", "unbound",
                                    "ipv6", "identity", "zero_packets", "missing_direction"])
def test_impaired_report_requires_exact_exclusive_gateway_coverage(change):
    windows, android = interop_reports()
    coverage = android["execution"]["scenarios"][-1]["impairment"]["gateway_coverage"]
    if change == "missing":
        del android["execution"]["scenarios"][-1]["impairment"]["gateway_coverage"]
    elif change == "extra": coverage["raw_device"] = "PRIVATE_NETDEV"
    elif change == "overbound": coverage["external_links"] = 2
    elif change == "wrong_count": coverage["external_links"] = True
    elif change == "unbound": coverage["namespace_bound"] = False
    elif change == "ipv6": coverage["ipv6_disabled"] = False
    elif change == "identity": coverage["veth_identity_current"] = False
    elif change == "zero_packets": coverage["directional_veth_packets"]["ingress"] = 0
    else: del coverage["directional_veth_packets"]["egress"]
    with pytest.raises(ValueError):
        evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


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
    from native_interop_rendezvous import CASE_COMPLETION_PHASES, NEGATIVE_CONTROL_PHASES
    windows = {"key", "reconnect_capabilities", *OFFER_PHASES, *CASE_COMPLETION_PHASES}
    android = {"key", "reconnect_capabilities", "offer", "approved", "impaired_ready", *NEGATIVE_CONTROL_PHASES, *CASE_COMPLETION_PHASES}
    assert len(windows) == 13 and len(android) == 14
    # The calling qualification workflow and its components can upload at most
    # 20 other artifacts (including both native reports and the aggregate gate).
    assert len(windows) + len(android) + 2 * (10 + 10) + 20 == 87 <= 100
    assert len(windows) + 1 == 14 and len(android) + 1 == 15
    quick = {"case_complete_direct_windows", "case_complete_direct_android", "case_complete_turn_udp_windows"}
    assert len({"key", "offer", "offer_turn_udp", "reconnect_capabilities", *quick}) + 1 == 8
    assert len({"key", "offer", "approved", "reconnect_capabilities", *quick}) + 1 == 8
    assert len({"key", "offer", "offer_turn_udp", "reconnect_capabilities", *quick}) + 2 + 1 == 10
    assert len({"key", "offer", "approved", "reconnect_capabilities", *quick}) + 2 + 1 == 10
    assert all(name in NEGATIVE_CONTROL_PHASES for name in windows | android if name.startswith("negative"))


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


INITIALIZE_CALLS = ["peer.start", "runtime.capabilities", "application.snapshot", "inventory",
    "settings.update", "call.settings_update", "call.ice_servers", "key.manifest", "key.publish", "key.wait", "key.bind"]
INITIALIZE_SITES = dict(zip(INITIALIZE_CALLS, ["initialize_peer_start", "initialize_runtime_capabilities",
    "initialize_snapshot", "initialize_inventory", "initialize_settings_update", "initialize_call_settings_update",
    "initialize_ice_servers", "initialize_key_publish", "initialize_key_publish", "initialize_key_wait", "initialize_key_bind"]))


def run_initialize_report(tmp_path, monkeypatch, capsys, *, role="android", point=None, kind="peer", guard=None,
                          foreign=False, later_error=False, cleanup_error=False, core_observation=None,
                          network_diagnostic=None):
    """Actual initialize/run/main and failure scope; external hosts/setup and later workload are inert."""
    import connection_ci
    state = SimpleNamespace(events=[], point=point, guard=guard, errors=[], now=100.0,
        error=(controller.PeerFailure("internal") if kind == "peer" else
            controller.RendezvousUnavailable("PRIVATE_URL_TOKEN") if kind == "rendezvous" else ValueError("PRIVATE_ID_URL_CREDENTIAL")),
        foreign=ValueError("PRIVATE_UNRELATED_ERROR"), cleanup_error=ValueError("PRIVATE_CLEANUP_ERROR"), terminal=False)
    state.error.failure_site = "PRIVATE_FORGED_SITE"
    def step(name):
        state.events.append(name)
        if state.point == name: raise state.error
    class Peer:
        process = SimpleNamespace(pid=17)
        processes_started, forced_exits, clean_exits = 0, 0, 0
        def core_failure_observation(self, error):
            return core_observation if error is state.error else None
        def network_diagnostic(self, *, timeout):
            state.events.append(("network_diagnostic", timeout))
            assert 0 < timeout <= 2
            if isinstance(network_diagnostic, Exception): raise network_diagnostic
            return network_diagnostic
        def start(self):
            step("peer.start")
            self.processes_started += 1
            return {}
        def core(self, operation, params, key=None):
            assert key is None
            if operation in {"native.command", "connection.stop"}:
                state.events.append("terminal:" + operation)
                state.terminal = True
                return {}
            step(operation)
            if operation == "runtime.capabilities": return {"profiles": [] if guard == "profile_count" else ["PRIVATE_PROFILE"]}
            if operation == "application.snapshot": return {"profile": {"destination_hash": "PRIVATE_DESTINATION"},
                "contacts": [{}] if guard == "snapshot_contacts" else [],
                "messages": [{}] if guard == "snapshot_messages" else []}
            if operation == "call.ice_servers": return {"ice": {"iceServers": []}}
            assert operation in {"settings.update", "call.settings_update"}
            if operation == "settings.update":
                assert params == {"profile": "PRIVATE_PROFILE", "settings": {
                    "nearby_discovery": False, "lan_fallback": False, "help_route": False}}
            else:
                assert params["settings"]["turn_broker_consent"] is True
                assert params["settings"]["relay_only"] is False and params["settings"]["store_call_signaling"] is True
            return {}
        def inventory(self):
            if state.terminal:
                state.events.append("terminal:inventory")
                return terminal_inventory()
            step("inventory")
            return terminal_inventory(active=int(guard == "inventory_nonzero"))
        def stop(self, **kwargs):
            state.events.append(("host.stop", kwargs))
            self.process = None
            if cleanup_error: raise state.cleanup_error
            if kwargs.get("crash"): self.forced_exits += 1
            else: self.clean_exits += 1
    class Transport:
        def publish(self, phase, value):
            assert phase == "key" and value == {"public_key": "PRIVATE_KEY_DOC"}
            step("key.publish")
        def wait(self, partner, phase, *, timeout):
            assert phase == "key" and timeout == 900 and partner == ("windows" if role == "android" else "android")
            step("key.wait")
            return {"public_key": "PRIVATE_PARTNER_KEY_DOC"}
        def close(self): state.events.append("transport.close")
    class Rendezvous:
        def public_manifest(self):
            step("key.manifest")
            return {"public_key": "PRIVATE_KEY_DOC"}
        def bind_partner(self, value):
            assert value == {"public_key": "PRIVATE_PARTNER_KEY_DOC"}
            step("key.bind")
        def close(self): state.events.append("rendezvous.close")
    monkeypatch.setattr(controller, "time", SimpleNamespace(monotonic=lambda: state.now,
        sleep=lambda seconds: pytest.fail("No wait should need a sleep in this fixture")))
    peer, transport, rendezvous = Peer(), Transport(), Rendezvous()
    instance = controller.Controller(role, peer, transport, rendezvous, {"source_commit": "a" * 40})
    def path_case(scenario, initiator):
        state.events.append("later:path_case")
        if later_error: raise state.foreign
        instance.contact = {"id": "PRIVATE_CONTACT", "core_handle": "PRIVATE_PEER"}
    monkeypatch.setattr(instance, "path_case", path_case)
    monkeypatch.setattr(instance, "cold_starts", lambda: state.events.append("later:cold_starts"))
    original_run, original_site = instance.run, instance.failure_site
    def execute():
        try: return original_run()
        except Exception as error:
            state.original_error = error
            if foreign:
                state.escaping_error = state.foreign
                raise state.foreign
            state.escaping_error = error
            raise
    def observed_site(error):
        state.errors.append(error)
        return original_site(error)
    monkeypatch.setattr(instance, "run", execute)
    monkeypatch.setattr(instance, "failure_site", observed_site)
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(start=lambda *args, **kwargs: None, close=lambda: None))
    monkeypatch.setattr(controller, "WindowsPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: transport)
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: rendezvous)
    import check_native_windows_messaging
    monkeypatch.setattr(check_native_windows_messaging, "descendants", lambda _: [])
    output = tmp_path / "initialize.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", role, "--workload", "full", "--expected-source", "a" * 40, "--output", str(output)])
    code = controller.main()
    captured = capsys.readouterr()
    return SimpleNamespace(record=json.loads(output.read_text()), code=code, state=state, controller=instance,
        output=output.read_text() + captured.out + captured.err)


@pytest.mark.parametrize("point", INITIALIZE_CALLS)
@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("kind", ["peer", "value"])
def test_actual_initialize_failure_reports_fixed_call_site_and_original_error(tmp_path, monkeypatch, capsys, point, role, kind):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point=point, role=role, kind=kind)
    assert run.code == 1 and run.record["phase"] == "initialize"
    assert run.record.get("failure_site") == INITIALIZE_SITES[point]
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.error]
    assert run.record["failure_type"] == ("PeerFailure" if kind == "peer" else "ValueError")
    assert run.record.get("error_code") == ("internal" if kind == "peer" else None)
    assert [event for event in run.state.events if event in INITIALIZE_CALLS] == INITIALIZE_CALLS[:INITIALIZE_CALLS.index(point) + 1]
    assert ("host.stop", {"crash": True}) in run.state.events and "later:path_case" not in run.state.events
    assert "PRIVATE" not in run.output and run.controller.deadline == 3100


@pytest.mark.parametrize("guard,point,message", [
    ("profile_count", "runtime.capabilities", "Native qualification requires one fresh synthetic profile"),
    ("snapshot_contacts", "application.snapshot", "Initial pairing must not begin with approved contacts or messages"),
    ("snapshot_messages", "application.snapshot", "Initial pairing must not begin with approved contacts or messages"),
    ("inventory_nonzero", "inventory", "Native allocation leases have not all retired"),
])
@pytest.mark.parametrize("role", ["windows", "android"])
def test_actual_initialize_guards_keep_existing_error_and_stop_at_call_site(tmp_path, monkeypatch, capsys, guard, point, message, role):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, role=role, guard=guard)
    assert run.code == 1 and run.record["phase"] == "initialize"
    assert run.record.get("failure_site") == INITIALIZE_SITES[point]
    assert run.state.errors == [run.state.original_error]
    assert str(run.state.original_error) == message
    assert [event for event in run.state.events if event in INITIALIZE_CALLS] == INITIALIZE_CALLS[:INITIALIZE_CALLS.index(point) + 1]
    assert "later:path_case" not in run.state.events and "PRIVATE" not in run.output


@pytest.mark.parametrize("role", ["windows", "android"])
def test_actual_initialize_success_keeps_calls_workload_cleanup_and_report_schema(tmp_path, monkeypatch, capsys, role):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, role=role)
    assert run.code == 0 and run.record["passed"] is True
    assert set(run.record) == {"v", "passed", "evidence_level", "role", "scope", "workload", "context",
        "source_commit", "source_tree", "platform", "preflight", "artifacts", "execution"}
    assert [event for event in run.state.events if event in INITIALIZE_CALLS] == INITIALIZE_CALLS
    assert run.state.events.count("later:path_case") == len(run.controller.workload["paths"])
    assert run.state.events.count("later:cold_starts") == 1
    assert run.state.events.count("terminal:native.command") == run.state.events.count("terminal:connection.stop") == 1
    assert ("host.stop", {"delete_profile": True} if role == "android" else {}) in run.state.events
    assert run.state.errors == [] and run.controller.deadline == 3100
    assert set(run.record["execution"]) == {"identity", "scenarios", "receipt_iterations", "processes_started",
        "forced_exits", "clean_exits", "webview_processes", "final_host_accounting", "cleanup"}
    # Later workload is inert here; a successful diagnostic fixture cannot qualify native interop.
    with pytest.raises(ValueError):
        evidence.verify_report(run.record, "a" * 40, "b" * 40, role)


@pytest.mark.parametrize("point", INITIALIZE_CALLS)
def test_actual_initialize_label_cannot_follow_unrelated_escaping_error(tmp_path, monkeypatch, capsys, point):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point=point, foreign=True)
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.foreign]
    assert run.code == 1 and "failure_site" not in run.record and "PRIVATE" not in run.output


@pytest.mark.parametrize("point", INITIALIZE_CALLS)
def test_actual_initialize_success_clears_prior_same_error_label(tmp_path, monkeypatch, capsys, point):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point=point)
    assert run.controller.failure_site(run.state.error) == INITIALIZE_SITES[point]
    run.state.point = None
    run.state.terminal = False
    run.controller.initialize()
    assert run.controller.failure_site(run.state.error) is None


@pytest.mark.parametrize("point", ["key.publish", "key.wait", "key.bind"])
@pytest.mark.parametrize("role", ["windows", "android"])
def test_actual_initialize_key_rendezvous_unavailable_keeps_type_and_private_text(tmp_path, monkeypatch, capsys, point, role):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point=point, role=role, kind="rendezvous")
    assert run.code == 1 and run.record.get("failure_site") == INITIALIZE_SITES[point]
    assert run.record["failure_type"] == "RendezvousUnavailable" and "error_code" not in run.record
    # Existing RendezvousUnavailable handling also consults the site for its fixed receive/publish projection.
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.error, run.state.error]
    assert [event for event in run.state.events if event in INITIALIZE_CALLS] == INITIALIZE_CALLS[:INITIALIZE_CALLS.index(point) + 1]
    assert "PRIVATE" not in run.output


def test_actual_initialize_later_unrelated_failure_omits_initialization_label(tmp_path, monkeypatch, capsys):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, later_error=True)
    assert run.code == 1 and "failure_site" not in run.record
    assert run.state.errors == [run.state.foreign] and "PRIVATE" not in run.output
    assert [event for event in run.state.events if event in INITIALIZE_CALLS] == INITIALIZE_CALLS


@pytest.mark.parametrize("point", INITIALIZE_CALLS)
def test_actual_initialize_cleanup_failure_preserves_primary_error_label(tmp_path, monkeypatch, capsys, point):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point=point, cleanup_error=True)
    assert run.code == 1 and run.record.get("failure_site") == INITIALIZE_SITES[point]
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.error]
    assert run.record["cleanup_failed"] is True
    assert ("host.stop", {"crash": True}) in run.state.events
    assert "PRIVATE" not in run.output


def test_initialize_failure_site_catalog_extends_existing_fixed_labels_only():
    assert controller.FAILURE_SITES == frozenset(INITIALIZE_SITES.values()) | {
        "negotiate_settings_update", "pairing_offer_begin", "pairing_answer_begin", "pairing_status",
        "rendezvous_receive", "rendezvous_publish", "negotiate_inventory", "negotiate_native_stats"}


CORE_FAILURE_OBSERVATION = {"v": 1, "operation": "ice_servers", "stage": "tls_context",
    "category": "unexpected", "cause": "file_not_found"}


@pytest.mark.parametrize("role,point,kind,foreign,expected", [
    ("android", "call.ice_servers", "peer", False, True),
    ("android", "runtime.capabilities", "peer", False, True),
    ("windows", "call.ice_servers", "peer", False, False),
    ("android", "call.ice_servers", "value", False, False),
    ("android", "call.ice_servers", "peer", True, False),
])
def test_actual_controller_failure_report_uses_only_same_android_core_error(
        tmp_path, monkeypatch, capsys, role, point, kind, foreign, expected):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, role=role, point=point, kind=kind,
        foreign=foreign, core_observation=CORE_FAILURE_OBSERVATION)
    assert run.code == 1
    assert run.record.get("core_failure_observation") == (CORE_FAILURE_OBSERVATION if expected else None)
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("observation", [
    {**CORE_FAILURE_OBSERVATION, "secret": "PRIVATE_CREDENTIAL"},
    {**CORE_FAILURE_OBSERVATION, "stage": "broker_json", "category": "response_encoding"},
    {**CORE_FAILURE_OBSERVATION, "operation": "runtime_capabilities", "stage": "tls_context"},
    {**CORE_FAILURE_OBSERVATION, "cause": "PRIVATE_CREDENTIAL"},
])
def test_actual_controller_rejects_invalid_core_observation(tmp_path, monkeypatch, capsys, observation):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point="call.ice_servers",
        core_observation=observation)
    assert run.code == 1 and "core_failure_observation" not in run.record
    assert "PRIVATE" not in run.output


BROKER_NAME_RESOLUTION = {"v": 1, "operation": "ice_servers", "stage": "broker_open",
    "category": "network_unavailable", "cause": "name_resolution"}
ANDROID_NETWORK_DIAGNOSTIC = {"v": 1, "scope": "post_failure_app_process", "internet_permission": True, "active_network": True,
    "internet_capability": True, "validated_network": False, "dns_servers_present": True,
    "process_bound_network": False, "connect_target": "broker"}


def test_actual_android_dns_failure_adds_one_bounded_guest_snapshot_after_original_error(
        tmp_path, monkeypatch, capsys):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point="call.ice_servers",
        core_observation=BROKER_NAME_RESOLUTION, network_diagnostic=ANDROID_NETWORK_DIAGNOSTIC)
    assert run.code == 1 and run.record["error_code"] == "internal"
    assert run.record["failure_site"] == "initialize_ice_servers"
    assert run.record["core_failure_observation"] == BROKER_NAME_RESOLUTION
    assert run.record["android_network_diagnostic"] == ANDROID_NETWORK_DIAGNOSTIC
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.error]
    assert [event for event in run.state.events if isinstance(event, tuple) and event[0] == "network_diagnostic"] == [
        ("network_diagnostic", 2.0)]
    assert ("host.stop", {"crash": True}) in run.state.events and "PRIVATE" not in run.output


@pytest.mark.parametrize("role,point,kind,foreign,observation", [
    ("windows", "call.ice_servers", "peer", False, BROKER_NAME_RESOLUTION),
    ("android", "runtime.capabilities", "peer", False, BROKER_NAME_RESOLUTION),
    ("android", "call.ice_servers", "value", False, BROKER_NAME_RESOLUTION),
    ("android", "call.ice_servers", "peer", True, BROKER_NAME_RESOLUTION),
    ("android", "call.ice_servers", "peer", False, CORE_FAILURE_OBSERVATION),
])
def test_guest_snapshot_is_only_for_same_android_broker_dns_failure(
        tmp_path, monkeypatch, capsys, role, point, kind, foreign, observation):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, role=role, point=point, kind=kind,
        foreign=foreign, core_observation=observation, network_diagnostic=ANDROID_NETWORK_DIAGNOSTIC)
    assert run.code == 1 and "android_network_diagnostic" not in run.record
    assert not any(isinstance(event, tuple) and event[0] == "network_diagnostic" for event in run.state.events)
    assert "PRIVATE" not in run.output


@pytest.mark.parametrize("diagnostic", [
    {**ANDROID_NETWORK_DIAGNOSTIC, "proxy_url": "PRIVATE_CREDENTIAL"},
    {**ANDROID_NETWORK_DIAGNOSTIC, "connect_target": "PRIVATE_HOST"},
    {**ANDROID_NETWORK_DIAGNOSTIC, "dns_servers_present": "true"},
    {**ANDROID_NETWORK_DIAGNOSTIC, "active_network": False},
    ValueError("PRIVATE_HOST_CREDENTIAL"),
])
def test_guest_snapshot_failure_never_replaces_core_failure_or_leaks_values(
        tmp_path, monkeypatch, capsys, diagnostic):
    run = run_initialize_report(tmp_path, monkeypatch, capsys, point="call.ice_servers",
        core_observation=BROKER_NAME_RESOLUTION, network_diagnostic=diagnostic)
    assert run.code == 1 and run.record["error_code"] == "internal"
    assert run.record["core_failure_observation"] == BROKER_NAME_RESOLUTION
    assert "android_network_diagnostic" not in run.record
    assert run.state.original_error is run.state.error and run.state.errors == [run.state.error]
    assert len([event for event in run.state.events if isinstance(event, tuple) and event[0] == "network_diagnostic"]) == 1
    assert ("host.stop", {"crash": True}) in run.state.events and "PRIVATE" not in run.output


@pytest.mark.parametrize("proxy,bypass,broker,expected", [
    (None, None, "https://broker.example/credentials", "broker"),
    ("http://proxy.example:8080", None, "https://broker.example/credentials", "proxy"),
    ("http://proxy.example:8080", "broker.example", "https://broker.example/credentials", "broker"),
    (None, None, "PRIVATE_INVALID_URL", "unknown"),
])
def test_actual_embedded_guest_route_selector_obeys_https_proxy_and_bypass(
        monkeypatch, proxy, bypass, broker, expected):
    for name in list(os.environ):
        if name.lower().endswith("_proxy"): monkeypatch.delenv(name)
    if proxy is not None: monkeypatch.setenv("https_proxy", proxy)
    if bypass is not None: monkeypatch.setenv("no_proxy", bypass)
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)
    monkeypatch.setattr(urllib.request, "proxy_bypass", urllib.request.proxy_bypass_environment)
    binding = install_guest_route_modules(monkeypatch, broker)
    source = (Path(__file__).resolve().parents[3] / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest"
        "/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text(encoding="utf-8")
    match = re.search(r'private val NETWORK_DIAGNOSTIC = """(.*?)"""\.trimIndent\(\)', source, re.DOTALL)
    assert match is not None
    namespace = {}
    exec(textwrap.dedent(match.group(1)), namespace)
    assert namespace["current"](binding)
    selected = json.loads(namespace["connect_target"](binding))
    assert selected == {"connect_target": expected}
    assert "PRIVATE" not in json.dumps(selected)


def test_guest_route_selector_uses_unknown_when_proxy_implementation_is_not_proven(monkeypatch):
    binding = install_guest_route_modules(monkeypatch, "https://broker.example/credentials")
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "PRIVATE_PROXY"})
    source = (Path(__file__).resolve().parents[3] / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest"
        "/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text(encoding="utf-8")
    match = re.search(r'private val NETWORK_DIAGNOSTIC = """(.*?)"""\.trimIndent\(\)', source, re.DOTALL)
    namespace = {}
    exec(textwrap.dedent(match.group(1)), namespace)
    assert json.loads(namespace["connect_target"](binding)) == {"connect_target": "unknown"}


@pytest.mark.parametrize("custom,selected_proxy", [
    ("build_opener", False), ("build_opener", True),
    ("ProxyHandler", False), ("ProxyHandler", True),
    ("proxy_open", False), ("proxy_open", True),
])
def test_actual_embedded_guest_route_selector_uses_unknown_for_custom_route_builder(
        monkeypatch, custom, selected_proxy):
    for name in list(os.environ):
        if name.lower().endswith("_proxy"): monkeypatch.delenv(name)
    if selected_proxy: monkeypatch.setenv("https_proxy", "http://proxy.example:8080")
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)
    monkeypatch.setattr(urllib.request, "proxy_bypass", urllib.request.proxy_bypass_environment)
    binding = install_guest_route_modules(monkeypatch, "https://broker.example/credentials")
    if custom == "build_opener":
        monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: None)
    elif custom == "ProxyHandler":
        class CustomProxyHandler(urllib.request.ProxyHandler): pass
        monkeypatch.setattr(urllib.request, "ProxyHandler", CustomProxyHandler)
    else:
        monkeypatch.setattr(urllib.request.ProxyHandler, "proxy_open", lambda self, req, proxy, type: None)
    source = (Path(__file__).resolve().parents[3] / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest"
        "/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text(encoding="utf-8")
    match = re.search(r'private val NETWORK_DIAGNOSTIC = """(.*?)"""\.trimIndent\(\)', source, re.DOTALL)
    assert match is not None
    namespace = {}
    exec(textwrap.dedent(match.group(1)), namespace)
    assert namespace["standard_route_builder"]() is False
    assert json.loads(namespace["connect_target"](binding)) == {"connect_target": "unknown"}


def test_guest_route_selector_rejects_rebound_publication(monkeypatch):
    binding = install_guest_route_modules(monkeypatch, "https://broker.example/credentials")
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)
    monkeypatch.setattr(urllib.request, "proxy_bypass", urllib.request.proxy_bypass_environment)
    source = (Path(__file__).resolve().parents[3] / "plugins/tauri-plugin-mesh-runtime/android/src/androidTest"
        "/java/com/meshchat/runtime/PackagedNativeInteropBoundaryTest.kt").read_text(encoding="utf-8")
    match = re.search(r'private val NETWORK_DIAGNOSTIC = """(.*?)"""\.trimIndent\(\)', source, re.DOTALL)
    namespace = {}
    exec(textwrap.dedent(match.group(1)), namespace)
    assert namespace["current"](binding)
    sys.modules["mesh_chat.core_api"].qualification_host._android_publication.binding = "b" * 64
    assert not namespace["current"](binding)
    assert json.loads(namespace["connect_target"](binding)) == {"connect_target": "unknown"}


def install_guest_route_modules(monkeypatch, broker):
    binding = "a" * 64
    mesh = ModuleType("mesh_chat")
    mesh.__path__ = []
    mesh.mobile_bridge = SimpleNamespace(_service=SimpleNamespace(call_settings=lambda: {"turn_broker_url": broker}))
    core = ModuleType("mesh_chat.core_api")
    core.__path__ = []
    core.qualification_host = SimpleNamespace(_android_publication=SimpleNamespace(binding=binding, current=lambda: True))
    mesh.core_api = core
    monkeypatch.setitem(sys.modules, "mesh_chat", mesh)
    monkeypatch.setitem(sys.modules, "mesh_chat.core_api", core)
    return binding


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


def run_negotiate_report(tmp_path, monkeypatch, capsys, role, fault, *, status_reply=None,
                         inventory_reply=None, stats_reply=None):
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
            if stats_reply is not None: return stats_reply()
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
            if inventory_reply is not None: return inventory_reply()
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


def gather_example():
    return {"as_of": "phase_deadline", "worker": "started", "stage": "native_accept",
            "stage_state": "entered", "last_completed": "ice_config", "queue_age": "lt1s",
            "stage_age": "20to25s"}


def failed_gather_example():
    return {**gather_example(), "as_of": "failed_result",
            "exception_kind": "native_unavailable", "native_code": "no_candidates"}


@pytest.mark.parametrize("case", ["valid_failed", "wrong_as_of_failed", "wrong_as_of_tick",
    "bad_pair", "private_key", "wrong_reason", "wrong_phase"])
def test_failed_gather_report_requires_retirement_affinity_and_coherent_dto(
        tmp_path, monkeypatch, capsys, case):
    failure = {"phase": "gather_answer", "event": "failed", "reason": "invalid_document"}
    tick = {"phase": "gather_answer", "event": "tick", "reason": "phase_timeout"}
    retirement = tick if case == "wrong_as_of_tick" else dict(failure)
    if case == "wrong_reason": retirement["reason"] = "transient"
    if case == "wrong_phase": retirement["phase"] = "wait_answer"
    gather = failed_gather_example()
    if case == "wrong_as_of_failed": gather = gather_example()
    if case == "bad_pair": gather = {**gather, "native_code": "not_applicable"}
    if case == "private_key": gather = {**gather, "sdp": "PRIVATE_SDP"}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement",
        status_reply=lambda operation: {"operation_id": operation, "state": "retired",
            "retirement": retirement, "gather_failure": gather})
    assert run.exit_code == 1 and run.record["error_code"] == "supervisor_pairing_retired"
    assert run.record.get("gather_failure") == (gather if case == "valid_failed" else None)
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("valid", [True, False])
def test_gather_failure_attaches_only_to_terminal_pairing_status_error(tmp_path, monkeypatch, capsys, valid):
    gather = gather_example()
    supplied = gather if valid else {**gather, "sdp": "PRIVATE_SDP"}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement",
        status_reply=lambda operation: {"operation_id": operation, "state": "retired",
            "retirement": {"phase": "gather_answer", "event": "tick", "reason": "phase_timeout"},
            "gather_failure": supplied})
    assert run.exit_code == 1 and run.record["error_code"] == "supervisor_pairing_retired"
    assert run.record.get("gather_failure") == (gather if valid else None)
    assert "PRIVATE_" not in run.output


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
        status_reply=lambda _: {"operation_id": "PRIVATE_FOREIGN_ID", "state": state,
                                "retirement": value, "gather_failure": gather_example()})
    assert run.record["error_code"] == "invalid_pairing_identity" and run.record["failure_site"] == "pairing_status"
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    assert "gather_failure" not in run.record
    assert "PRIVATE_" not in run.output


@pytest.mark.parametrize("fault", ["caught_status_then_unrelated", "caught_status_then_success", "caught_status_then_foreign"])
def test_retirement_detail_belongs_only_to_same_active_status_exception(tmp_path, monkeypatch, capsys, fault):
    value = retirement_example()
    calls = []
    def reply(operation):
        calls.append(operation)
        if len(calls) == 1: return {"operation_id": operation, "state": "retired",
                                    "retirement": value, "gather_failure": gather_example()}
        return {"operation_id": "PRIVATE_OTHER_ID" if fault.endswith("foreign") else operation,
                "state": "retired" if fault.endswith("foreign") else "offer_ready",
                "retirement": value, "gather_failure": gather_example()}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "windows", fault, status_reply=reply)
    assert run.exit_code == 1 and run.record["passed"] is False
    assert "pairing_state" not in run.record and "pairing_retirement" not in run.record
    assert "gather_failure" not in run.record
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
            "pairing_code": "PRIVATE_SIGNED_CODE", "retirement": value,
            "gather_failure": gather_example()})
    assert run.exit_code == 0 and run.record["passed"] is True
    assert not {"failure_site", "pairing_state", "pairing_retirement", "gather_failure"} & set(run.record)
    assert "PRIVATE_" not in run.output
    # This intentionally incomplete component fixture cannot qualify native CI.
    with pytest.raises(ValueError): evidence.verify_report(run.record, "a" * 40, "b" * 40, role)


@pytest.mark.parametrize("role", ["windows", "android"])
def test_terminal_pairing_reports_last_existing_open_predicate_without_more_calls(
        tmp_path, monkeypatch, capsys, role):
    reads = [0]
    def status(operation):
        reads[0] += 1
        state = ("offer_ready" if role == "windows" and reads[0] == 1 else
                 "awaiting_approval" if reads[0] <= (2 if role == "windows" else 1) else "retired")
        return {"operation_id": operation, "state": state, "pairing_code": "PRIVATE_CODE",
                "retirement": retirement_example()}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, role, "retirement",
        status_reply=status, stats_reply=lambda: {"ice_connection_state": "checking",
            "data_channel_state": "connecting", "sdp": "PRIVATE_SDP"})
    assert run.record["pairing_open_last"] == {"status": "awaiting_approval", "resources": "one",
        "ice": "checking", "channel": "connecting"}
    assert run.record["error_code"] == "supervisor_pairing_retired"
    assert run.record["pairing_retirement"] == retirement_example()
    assert run.events == (["settings", "begin_offer", "status", "publish", "status", "inventory", "stats", "status"]
                          if role == "windows" else
                          ["settings", "receive", "begin_answer", "status", "inventory", "stats", "status"])
    assert "PRIVATE" not in run.output


def test_last_poll_replaces_old_stats_with_unread_when_status_becomes_reserved(
        tmp_path, monkeypatch, capsys):
    states = iter(("awaiting_approval", "reserved", "retired"))
    def status(operation):
        return {"operation_id": operation, "state": next(states),
                "retirement": retirement_example()}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement",
        status_reply=status, stats_reply=lambda: {"ice_connection_state": "checking",
            "data_channel_state": "connecting"})
    assert run.record["pairing_open_last"] == {"status": "reserved", "resources": "unread",
        "ice": "unread", "channel": "unread"}
    assert run.events == ["settings", "receive", "begin_answer", "status", "inventory", "stats",
                          "status", "status"]


def test_multiple_resources_and_private_labels_never_escape_pairing_diagnostic(
        tmp_path, monkeypatch, capsys):
    states = iter(("PRIVATE_STATE", "retired"))
    def status(operation):
        return {"operation_id": operation, "state": next(states), "pairing_code": "PRIVATE_CODE",
                "retirement": retirement_example()}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement",
        status_reply=status, inventory_reply=lambda: {"resources": [
            {"logical_session": "PRIVATE_1"}, {"logical_session": "PRIVATE_2"}]},
        stats_reply=lambda: pytest.fail("Stats must not be read for multiple resources"))
    assert run.record["pairing_open_last"] == {"status": "unknown", "resources": "multiple",
        "ice": "unread", "channel": "unread"}
    assert run.events == ["settings", "receive", "begin_answer", "status", "inventory", "status"]
    assert "PRIVATE" not in run.output


def test_foreign_status_after_open_poll_cannot_inherit_pairing_diagnostic(
        tmp_path, monkeypatch, capsys):
    reads = [0]
    def status(operation):
        reads[0] += 1
        return {"operation_id": operation if reads[0] == 1 else "PRIVATE_FOREIGN_ID",
            "state": "awaiting_approval" if reads[0] == 1 else "retired"}
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "foreign_status",
        status_reply=status, stats_reply=lambda: {"ice_connection_state": "PRIVATE_ICE",
            "data_channel_state": "PRIVATE_CHANNEL", "raw_sdp": "PRIVATE_SDP"})
    assert run.record["error_code"] == "invalid_pairing_identity"
    assert run.record["failure_site"] == "pairing_status"
    assert "pairing_open_last" not in run.record
    assert "pairing_state" not in run.record
    assert run.events == ["settings", "receive", "begin_answer", "status", "inventory", "stats", "status"]
    assert "PRIVATE" not in run.output


def test_unknown_native_stats_labels_are_bounded_in_terminal_diagnostic(
        tmp_path, monkeypatch, capsys):
    states = iter(("awaiting_approval", "retired"))
    run = run_negotiate_report(tmp_path, monkeypatch, capsys, "android", "retirement",
        status_reply=lambda operation: {"operation_id": operation, "state": next(states)},
        stats_reply=lambda: {"ice_connection_state": "PRIVATE_ICE",
            "data_channel_state": "PRIVATE_CHANNEL", "raw_sdp": "PRIVATE_SDP"})
    assert run.record["pairing_open_last"] == {"status": "awaiting_approval", "resources": "one",
        "ice": "unknown", "channel": "unknown"}
    assert "PRIVATE" not in run.output


def test_open_session_deadline_records_only_its_exact_last_predicate(negotiating_peer):
    state = negotiating_peer("android")
    state.status_value = "reserved"
    state.controller.deadline = state.now + 0.5
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == "scenario_deadline"
    assert state.controller.failure_pairing_open(failure.value) == {"pairing_open_last": {
        "status": "reserved", "resources": "unread", "ice": "unread", "channel": "unread"}}
    assert state.events == [*state.prefix, "status", "status"]
    assert state.sleeps == [0.25, 0.25]
    state.status_value = "awaiting_approval"
    state.controller.deadline = state.now + 1
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    assert state.controller.failure_pairing_open(failure.value) == {}


def test_pairing_open_observer_fault_never_changes_success_or_terminal_error(
        negotiating_peer, monkeypatch):
    state = negotiating_peer("android")
    def broken(_value): raise RuntimeError("PRIVATE_OBSERVER")
    monkeypatch.setattr(controller, "pairing_open_observation", broken, raising=False)
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    state.status_value = "awaiting_approval"
    state.stats_value = {"data_channel_state": "connecting"}
    state.on_sleep = lambda: setattr(state, "status_value", "retired")
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == "supervisor_pairing_retired"
    assert state.controller.failure_pairing_open(failure.value) == {}


@pytest.mark.parametrize("stage", ["status", "resources"])
def test_pairing_open_observer_fault_at_early_poll_stage_does_not_change_outcome(
        negotiating_peer, monkeypatch, stage):
    state = negotiating_peer("android")
    original = controller.pairing_open_observation
    def broken(value):
        if ((stage == "status" and value["resources"] == "unread")
                or (stage == "resources" and value["resources"] == "one" and value["ice"] == "unread")):
            raise RuntimeError("PRIVATE_OBSERVER")
        return original(value)
    monkeypatch.setattr(controller, "pairing_open_observation", broken)
    assert state.controller.negotiate("direct", "windows") == ("logical-session", None)
    state.stats_value = {"ice_connection_state": "checking", "data_channel_state": "connecting"}
    state.on_sleep = lambda: setattr(state, "status_value", "retired")
    with pytest.raises(controller.PeerFailure) as failure:
        state.controller.negotiate("direct", "windows")
    assert failure.value.code == "supervisor_pairing_retired"
    assert state.controller.failure_pairing_open(failure.value) == {"pairing_open_last": {
        "status": "awaiting_approval", "resources": "one", "ice": "checking", "channel": "connecting"}}


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
    endpoint_mode = False
    target_kind, target_material, rule_count = "uid_tcp_turn_destination_set", {"modeled_target": True}, 1
    def __init__(self, peer, _sample, _url, *, diagnostics=None, path_diagnostics=None, **_kwargs):
        assert type(path_diagnostics) is completion_faults.NativePathDiagnostics
        self.world = peer.world
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

    def inventory(self, *, operation_id=None, request_id=None, carrier_observation=None):
        if carrier_observation is not None:
            assert carrier_observation == {"operation_id": self.operation, "logical_session": self.logical,
                "expected_physical": self.physical, "expected_service_incarnation": self.service,
                "expected_profile_incarnation": self.profile}
            assert operation_id is None and request_id is None
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
        observer._prepare_negative_control = lambda _, r=role: SimpleNamespace(
            send=lambda stage: world.publish(r, "negative_" + stage, {"approved": True}),
            receive=lambda stage, **_: world.receive(
                "android" if r == "windows" else "windows", "negative_" + stage) == {"approved": True})
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
