"""Offline owner observations; simulated boundaries are not native qualification."""
from copy import deepcopy
from dataclasses import replace
import json
import socket
from threading import Event
from time import monotonic
from types import SimpleNamespace
import urllib.request
from uuid import uuid4

import pytest

from mesh_chat.connection.model import (
    Adopted, Authority, ConnectionKey, ConnectionState, Desired, Execution,
    Phase, Resource,
)
from mesh_chat.connection.runtime import ConnectionRuntime
from mesh_chat.errors import ContactNotApproved
from test_native_path_evidence import REQUEST, evidence
from test_carrier_recovery import recovery
from test_pairing_runtime import native_pairing, ready_handoff, run_until


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline adoption control attempted external I/O")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    yield
    assert not attempts


def pending_owner(profile_id="peer", scope="contact"):
    owner, source = ready_handoff()
    target = ConnectionKey(scope, profile_id, "local", "remote")
    physical = Resource("native", "physical-peer")
    assert owner.commit_handoff(source.operation, physical, target, 0.2)
    owner.register(ConnectionState(target, "epoch", Authority(1, True, True, True), Desired.ENABLED))
    owner.tick(0.2)
    work, = owner.drain()
    return owner, source.operation, target, physical, work


def owner_facts(owner):
    return deepcopy({name: getattr(owner, name) for name in (
        "_states", "_pending", "_running", "_control", "_retired", "_retiring",
        "_handoffs", "_surrendered", "_handoff_committed", "_pairing_traces")})


def test_pending_query_is_read_only_and_does_not_authorize_adoption():
    owner, source, target, physical, work = pending_owner()
    before = owner_facts(owner)
    assert owner.pending_handoff_adoption(target, physical, 0.3)
    assert owner_facts(owner) == before
    assert owner.snapshot(target).carrier is None
    owner.dispatch(target, Adopted(work.operation, 0.4, physical))
    assert not owner.pending_handoff_adoption(target, physical, 0.5)
    assert source not in owner._handoffs
    assert owner.snapshot(target).carrier.resource == physical


@pytest.mark.parametrize("fault", [
    "missing_state", "state_key", "pairing_target", "retired", "state_epoch", "unauthorized", "stopped",
    "locked", "blocked", "no_step", "wrong_phase", "no_operation", "work_expired", "work_missing",
    "operation_runtime", "operation_key", "operation_generation", "operation_revision",
    "work_phase", "work_resource", "work_operation", "work_deadline_expired", "work_deadline_mismatch",
    "missing_lease", "uncommitted",
    "lease_expired", "foreign_target", "foreign_resource", "lease_runtime", "non_pairing_source",
    "retiring_physical", "retiring_source", "surrendered_target", "owned_elsewhere", "ambiguous_lease",
    "lease_key", "ambiguous_foreign_lease",
])
def test_invalid_pending_proof_is_false_without_mutation(fault):
    owner, source, target, physical, work = pending_owner()
    state, lease = owner.snapshot(target), owner._handoffs[source]
    query_target, now = target, 0.3
    if fault == "missing_state": owner._states.pop(target)
    elif fault == "state_key": owner._states[target] = replace(state, key=source.key)
    elif fault == "pairing_target": query_target = source.key
    elif fault == "retired": owner._retired.add(target)
    elif fault == "state_epoch": owner._states[target] = replace(state, runtime_epoch="old")
    elif fault == "unauthorized": owner._states[target] = replace(state, authority=replace(state.authority, authorized=False))
    elif fault == "stopped": owner._states[target] = replace(state, desired=Desired.STOPPED)
    elif fault == "locked": owner._states[target] = replace(state, execution=Execution.LOCKED)
    elif fault == "blocked": owner._states[target] = replace(state, blocked=True)
    elif fault == "no_step": owner._states[target] = replace(state, negotiation=None)
    elif fault == "wrong_phase": owner._states[target] = replace(state, negotiation=replace(state.negotiation, phase=Phase.CHECKING))
    elif fault == "no_operation": owner._states[target] = replace(state, negotiation=replace(state.negotiation, operation=None))
    elif fault == "work_expired": now = state.negotiation.deadline
    elif fault == "work_missing": owner._running.pop(work.operation)
    elif fault.startswith("operation_"):
        field, value = {"operation_runtime": ("runtime_epoch", "old"), "operation_key": ("key", source.key),
                        "operation_generation": ("generation", work.operation.generation + 1),
                        "operation_revision": ("policy_revision", work.operation.policy_revision + 1)}[fault]
        operation = replace(work.operation, **{field: value})
        owner._states[target] = replace(state, negotiation=replace(state.negotiation, operation=operation))
        owner._running.pop(work.operation)
        owner._running[operation] = replace(work, operation=operation)
    elif fault == "work_phase": owner._running[work.operation] = replace(work, phase=Phase.CHECKING)
    elif fault == "work_resource": owner._running[work.operation] = replace(work, resource=physical)
    elif fault == "work_operation": owner._running[work.operation] = replace(work, operation=source)
    elif fault == "work_deadline_expired": owner._running[work.operation] = replace(work, deadline=now)
    elif fault == "work_deadline_mismatch": owner._running[work.operation] = replace(work, deadline=work.deadline + 1)
    elif fault == "missing_lease": owner._handoffs.clear()
    elif fault == "uncommitted": owner._handoff_committed.clear()
    elif fault == "lease_expired": now = lease.deadline
    elif fault == "foreign_target": owner._handoffs[source] = replace(lease, target=source.key)
    elif fault == "foreign_resource": physical = Resource("native", "replacement")
    elif fault in {"lease_runtime", "non_pairing_source"}:
        operation = replace(source, **({"runtime_epoch": "old"} if fault == "lease_runtime" else {"key": target}))
        owner._handoffs[source] = replace(lease, operation=operation)
        owner._handoff_committed.add(operation)
    elif fault == "retiring_physical": owner._retiring.add(physical)
    elif fault == "retiring_source": owner._retiring.add(lease.source)
    elif fault == "surrendered_target": owner._surrendered[target] = (physical,)
    elif fault == "owned_elsewhere":
        other = ConnectionKey("contact", "other", "local", "remote")
        owner._states[other] = replace(state, key=other, negotiation=replace(state.negotiation, resource=physical))
    elif fault == "ambiguous_lease": owner._handoffs[work.operation] = lease
    elif fault == "lease_key": owner._handoffs[work.operation] = owner._handoffs.pop(source)
    elif fault == "ambiguous_foreign_lease": owner._handoffs[work.operation] = replace(lease, target=source.key)
    before = owner_facts(owner)
    assert not owner.pending_handoff_adoption(query_target, physical, now)
    assert owner_facts(owner) == before


@pytest.mark.parametrize("fence", [None, "contact", "workspace", "global", "veto", "authority", "quarantine", "stop", "missing", "ambiguous", "profile_identity"])
def test_runtime_pending_query_preserves_fences_and_profiles(fence):
    owner, _, target, physical, _ = pending_owner(scope="workspace" if fence == "workspace" else "contact")
    runtime = ConnectionRuntime("epoch", lambda *_: SimpleNamespace(retire=lambda _: None), profiles=lambda: {},
                                execution=lambda: Execution.AVAILABLE, activate=lambda _: None, now=lambda: 0.3)
    runtime.owner = owner
    profile = {"id": target.profile_id, "contact_id": "contact", "workspace_id": "team"}
    runtime._profile_keys[target.profile_id] = {target}
    runtime._profile_values[target] = profile
    if fence == "contact": runtime._contact_fences.add("contact")
    elif fence == "workspace": runtime._contact_fences.add(("workspace", "team"))
    elif fence == "global": runtime._all_fenced = True
    elif fence == "veto": runtime._veto.add(target)
    elif fence == "authority": runtime._authority_changes["contact"] = 1
    elif fence == "quarantine": runtime._quarantined = True
    elif fence == "stop": runtime._stop.set()
    elif fence == "missing": runtime._profile_values.clear()
    elif fence == "ambiguous": runtime._profile_keys[target.profile_id].add(replace(target, remote_device="other"))
    elif fence == "profile_identity": profile["id"] = "foreign"
    before = owner_facts(owner), deepcopy(runtime._profile_values), deepcopy(runtime._profile_keys)
    try:
        assert runtime.pending_handoff_adoption(target.profile_id, physical) is (fence is None)
        assert (owner_facts(owner), runtime._profile_values, runtime._profile_keys) == before
    finally:
        runtime.stop()
        runtime.wait()


def test_fresh_direct_claim_waits_for_owner_commit(native_pairing, monkeypatch):
    """Approval/contact rows are explicit component fixtures, not bootstrap qualification."""
    from test_reconnect_service import _add_contact
    create, _ = native_pairing
    first, _, created, _, _, _ = create()
    second, _, _, _, _, _ = create()
    first_id, second_id = str(uuid4()), str(uuid4())
    def checkpoint(state):
        assert state == "transferred"
        assert first._native_pairing_contexts[first_id]["state"] == state
        operation = next(iter(first._connection_runtime._handoff_attempts.values()))
        assert first._connection_runtime.owner.handoff_committed(operation)
    first.native_pairing_begin(first_id, role="offer", authorized=lambda: True, on_terminal=checkpoint, allow_direct_ip_disclosure=True)
    run_until(first, lambda: first.native_pairing_status(first_id)["pairing_code"] is not None)
    code = first.native_pairing_status(first_id)["pairing_code"]
    second.native_pairing_begin(second_id, role="answer", pairing_code=code, authorized=lambda: True, allow_direct_ip_disclosure=True)
    run_until(second, lambda: second.native_pairing_status(second_id)["state"] == "awaiting_approval")
    first._connection_runtime.now = lambda: monotonic() + 6
    run_until(first, lambda: first.native_pairing_status(first_id)["state"] == "awaiting_approval")
    _add_contact(first, "contact-second", second._identity, second._require_profile()["destination_hash"])
    _add_contact(second, "contact-first", first._identity, first._require_profile()["destination_hash"])

    first_context = first._native_pairing_contexts[first_id]
    session, physical = first_context['session'], first_context['physical']
    assert first._native_webrtc_descriptions[session]['ice_policy'] == 'all'
    assert not first._native_webrtc_profile_sessions
    assert first.reconnect_consent_set('contact-second', False, True)['changed'] is True
    assert second.reconnect_consent_set('contact-first', False, True)['changed'] is True
    for service, intent, other, contact in ((first, first_id, second, 'contact-first'), (second, second_id, first, 'contact-second')):
        context = service._native_pairing_contexts[intent]
        document = other._reconnect_profile_for_contact(contact)['local_capabilities']
        service._native_control_receive(context['session'], 'mesh-onboarding', json.dumps({'type': 'connection_capabilities', 'document': document}))
    profile_id = first._native_webrtc_controls[session]['profile_id']
    assert first._native_pairing_ready(first_context)
    assert not first._native_webrtc_profile_sessions
    claimed, release = Event(), Event()
    from mesh_chat.connection import composition
    original_claim = composition._claim_carrier
    def pause_after_claim(service, key):
        result = original_claim(service, key)
        if service is first and result is not None:
            claimed.set()
            assert release.wait(3), 'bounded claim gate exceeded'
        return result
    monkeypatch.setattr(composition, '_claim_carrier', pause_after_claim)
    native_calls = []
    def inspect(resource, sample_request):
        native_calls.append(resource)
        return json.dumps({'ok': True, 'result': evidence(resource, len(native_calls), sample_request)})
    first._native_webrtc_host().pathEvidence = inspect
    first.webrtc_attach_native = lambda *args, **kwargs: {'bridge_id': 'fixture-bridge'}
    first.reconnect_path_status = lambda _: {'has_path': True, 'ready': True}
    first._connection_runtime.now = lambda: monotonic() + 12
    try:
        run_until(first, claimed.is_set)
        inventory = first.native_webrtc_inspection_resources()
        row = next(row for row in inventory['resources'] if row['logical_session'] == session)
        assert row['adopted'] is True and row['owner_state'] == 'pending_adoption'
        before = owner_facts(first._connection_runtime.owner)
        first._native_webrtc_profile_sessions['ambiguous-profile'] = session
        try:
            assert first._native_inspection_owner_state(session) == 'unavailable'
        finally:
            del first._native_webrtc_profile_sessions['ambiguous-profile']
        incarnation = first._runtime_incarnation
        first._runtime_incarnation = 'foreign-incarnation'
        try:
            assert first._native_inspection_owner_state(session) == 'unavailable'
        finally:
            first._runtime_incarnation = incarnation
        assert owner_facts(first._connection_runtime.owner) == before
        assert not first._native_carrier_authorized(session)
        runtime = first._connection_runtime
        with runtime._lock, runtime.owner._lock:
            matching_keys = runtime._profile_keys[profile_id]
            assert len(matching_keys) == 1
            key = next(iter(matching_keys))
            profile = runtime._profile_values[key]
            assert not runtime._is_fenced(key, profile)
            state = runtime.owner._states[key]
            assert state.carrier is None
            assert state.authority.authorized
            assert state.desired is Desired.ENABLED
            assert state.execution is Execution.AVAILABLE
            assert state.negotiation.phase is Phase.DISCOVER
            operation = state.negotiation.operation
            work = runtime.owner._running[operation]
            assert work.operation == operation
            assert work.phase is Phase.DISCOVER
            assert work.resource == state.negotiation.resource
            assert operation.runtime_epoch == runtime.owner.runtime_epoch
            assert operation.generation == state.generation
            assert operation.policy_revision == state.authority.revision
            assert work.deadline == state.negotiation.deadline
            assert runtime.now() < work.deadline
            leases = [lease for lease in runtime.owner._handoffs.values()
                      if lease.target == key and lease.resource == Resource('native', physical)]
            assert len(leases) == 1
            lease = leases[0]
            assert lease.operation in runtime.owner._handoff_committed
            assert lease.operation.key.scope == 'pairing'
            assert lease.operation.runtime_epoch == runtime.owner.runtime_epoch
            assert runtime.now() < lease.deadline
            assert lease.resource not in runtime.owner._retiring
            assert lease.source not in runtime.owner._retiring
            assert key not in runtime.owner._retired
            assert not runtime.owner._owned_elsewhere(key, lease.resource)
        with pytest.raises(ContactNotApproved, match='authority is unavailable') as caught:
            first.native_webrtc_path_evidence(session, physical, REQUEST)
        assert caught.value.code == 'contact_not_approved'
        assert native_calls == []
        assert first.store.get('contact', 'contact-second')['trust'] == 'approved'
        assert first_context['state'] == 'transferred'
    finally:
        release.set()
        composition._claim_carrier = original_claim
    first._connection_runtime.now = monotonic
    run_until(first, lambda: first._native_carrier_authorized(session))
    assert first.native_webrtc_path_evidence(session, physical, REQUEST)['adopted'] is True
    assert len(created) == 1
    row = next(row for row in first.native_webrtc_inspection_resources()['resources'] if row['logical_session'] == session)
    assert row['adopted'] is True and row['owner_state'] == 'authorized'



def test_recovered_manual_claim_needs_owner_commit_without_pending_handoff(recovery):
    from mesh_chat.carrier_recovery import reconcile_carriers
    service, binding, _, _, _ = recovery
    reconcile_carriers(service, lambda _: True)
    session = service.claim_native_reconnect_carrier('profile', 'local', 'remote')
    owner, _, target, _, work = pending_owner('profile')
    owner._handoffs.clear()  # Recovered claims have no pairing handoff lease.
    runtime = ConnectionRuntime('epoch', lambda *_: SimpleNamespace(retire=lambda _: None),
        profiles=lambda: {}, execution=lambda: Execution.AVAILABLE, activate=lambda _: None, now=lambda: 0.3)
    runtime.owner = owner
    runtime._profile_keys['profile'] = {target}
    runtime._profile_values[target] = {'id': 'profile', 'contact_id': 'contact'}
    service._runtime_incarnation = 'epoch'
    service._connection_runtime = runtime
    physical = Resource('native', binding.resource)
    try:
        assert service._native_inspection_owner_state(session) == 'unavailable'
        assert not runtime.pending_handoff_adoption('profile', physical)
        owner.dispatch(target, Adopted(work.operation, 0.4, physical))
        assert service._native_inspection_owner_state(session) == 'authorized'
        assert not runtime.pending_handoff_adoption('profile', physical)
    finally:
        runtime.stop()
        runtime.wait()
