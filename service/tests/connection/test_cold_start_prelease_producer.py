"""Focused source-level reproduction of the ordinary reconnect pre-lease window."""

from dataclasses import replace
from threading import Event
from time import monotonic

import pytest

from mesh_chat.connection.model import Phase, Resource, Work
from mesh_chat.errors import ContactNotApproved
from test_pairing_runtime import native_pairing
from test_reconnect_service import _add_contact, _consent, mailbox


@pytest.mark.parametrize("gate_method,phase", [
    ("createOffer", Phase.GATHER_OFFER), ("acceptOffer", Phase.GATHER_ANSWER),
])
def test_fresh_reconnect_allocation_is_visible_before_owner_carrier_commit(
        native_pairing, mailbox, gate_method, phase):
    create, _ = native_pairing
    alex, alex_host, *_ = create()
    blair, blair_host, *_ = create()
    _add_contact(alex, "contact-blair", blair._identity, blair._require_profile()["destination_hash"])
    _add_contact(blair, "contact-alex", alex._identity, alex._require_profile()["destination_hash"])
    _consent(alex, blair)

    entered, release = Event(), Event()
    observed = []
    for service, host in ((alex, alex_host), (blair, blair_host)):
        original = getattr(host, gate_method)
        def blocked(physical, *args, _original=original, _service=service):
            observed.append((_service, physical))
            entered.set()
            assert release.wait(20)
            return _original(physical, *args)
        setattr(host, gate_method, blocked)

    alex.reconnect_start("contact-blair")
    blair.reconnect_start("contact-alex")
    try:
        deadline = monotonic() + 15
        while not entered.is_set() and monotonic() < deadline:
            alex._connection_runtime.step()
            blair._connection_runtime.step()
            Event().wait(.005)
        assert entered.is_set(), ({
            "states": [(service._connection_runtime.snapshots(),
                        [(state.negotiation.phase.value if state.negotiation else None,
                          state.authority.authorized, state.desired.value, state.execution.value)
                         for state in service._connection_runtime.owner.snapshots()])
                       for service in (alex, blair)],
            "published": len(mailbox.published)})
        service, physical = observed[0]
        session = service._native_resources.resolve(physical)
        assert session is not None and session in service._native_webrtc_creating
        assert session not in service._native_recovered_bindings
        row, = service.native_webrtc_inspection_resources()["resources"]
        assert row["physical_resource"] == physical
        assert row["adopted"] is True and row["owner_state"] == "pending_negotiation"
        state = next(state for state in service._connection_runtime.owner.snapshots()
                     if state.key.profile_id in service._native_webrtc_profile_sessions)
        assert state.carrier is None and state.negotiation.phase is phase
        step = state.negotiation
        assert state.authority.authorized and state.desired.value == "enabled"
        assert state.execution.value == "available" and not state.blocked
        assert step.resource == Resource("native", session) and session != physical
        assert step.operation.runtime_epoch == service._connection_runtime.owner.runtime_epoch
        assert step.operation.generation == state.generation
        assert step.operation.policy_revision == state.authority.revision
        assert step.deadline > service._connection_runtime.now()
        work = service._connection_runtime.owner._running[step.operation]
        assert work.phase is step.phase and work.resource == step.resource and work.deadline == step.deadline
        owner = service._connection_runtime.owner
        owner.tick(service._connection_runtime.now())
        current = next(snapshot for snapshot in owner.snapshots() if snapshot.key == state.key)
        assert current.negotiation == step and current.sequence > step.operation.sequence
        assert service.native_webrtc_inspection_resources()["resources"][0]["owner_state"] == "pending_negotiation"
        assert not service._connection_runtime.pending_native_negotiation(
            state.key.profile_id, Resource("native", "other-logical"), Resource("native", physical))
        assert not owner.pending_native_negotiation(
            state.key, Resource("native", session), Resource("native", physical), step.deadline)
        stale_operation = replace(step.operation, sequence=step.operation.sequence + 1000)
        with owner._lock:
            owner._running[stale_operation] = Work(stale_operation, phase, step.resource, step.deadline)
        try:
            assert service.native_webrtc_inspection_resources()["resources"][0]["owner_state"] == "unavailable"
        finally:
            with owner._lock:
                del owner._running[stale_operation]
        service._native_webrtc_profile_sessions["ambiguous-profile"] = session
        try:
            assert service.native_webrtc_inspection_resources()["resources"][0]["owner_state"] == "unavailable"
        finally:
            del service._native_webrtc_profile_sessions["ambiguous-profile"]
        assert not service._connection_runtime.permits_carrier(
            state.key.profile_id, Resource("native", physical))
        with pytest.raises(ContactNotApproved):
            service.native_webrtc_path_evidence(session, physical, "f" * 32)
    finally:
        release.set()
