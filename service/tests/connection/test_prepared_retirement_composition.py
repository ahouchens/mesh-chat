"""Prepared private port + actual owner/Windows native disposal on loopback.

Both role labels use WindowsNativeWebRTCHost. Contact approval/Reticulum are
the existing fixture models. These tests do not execute full Controller.path_case,
authenticate message receipts, or qualify Android/JNI/packaged transports.
Native notifications are retained verbatim from the real host, never synthesized.
"""
from contextlib import contextmanager
from threading import Event, Lock
from uuid import uuid4

import pytest

from mesh_chat.errors import ContactNotApproved, NativeUnavailable
from test_native_lease_retirement_composition import (
    await_retirement, correlated_retired, delayed_native_close, manual_carriers,
    native_pairing, prepare_retirement, request_retirement, retirement_observation,
    retirement_requests, reticulum,
)
from native_interop_peers import PeerFailure


def ticket(state, role):
    return state.peers[role].contexts[state.intents[role]]["carrier_retirement"].ticket


def act(state, requests, role, action):
    return state.peers[role].retire_carrier(**requests[role], action=action)


@contextmanager
def retained_closed(state, role, monkeypatch):
    """Delay delivery, not disposal: forward the exact actual callback once."""
    host, physical = state.hosts[role], state.physical[role]
    notify = host._notify
    received, consumed, lock, retained = Event(), Event(), Lock(), []
    forwarding = False
    handle = state.services[role]._handle_native_webrtc_event
    def consume(event, resource, data=""):
        result = handle(event, resource, data)
        if (event, resource, data) == ("closed", physical, ""):
            consumed.set()
        return result
    def capture(event, resource, data):
        with lock:
            if event == "closed" and resource == physical and not forwarding:
                retained.append((event, resource, data))
                received.set()
                return
        notify(event, resource, data)
    def release():
        nonlocal forwarding
        with lock:
            forwarding = True
            values, retained[:] = list(retained), []
        for value in values:
            notify(*value)
        return values
    monkeypatch.setattr(host, "_notify", capture)
    monkeypatch.setattr(state.services[role], "_handle_native_webrtc_event", consume)
    try:
        yield received, consumed, release
    finally:
        release()  # Independent backstop; never wait for retirement to release.


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_prepare_keeps_actual_carrier_inspection_and_packet_permission(manual_carriers):
    state = manual_carriers
    requests = retirement_requests(state)
    before = {role: peer.inventory()["host_accounting"] for role, peer in state.peers.items()}
    prepare_retirement(state, requests)
    for role, observer in state.controllers.items():
        value = ticket(state, role)
        runtime = state.services[role]._connection_runtime
        assert not value.committed and not value.admission.retired and not value.close_started
        assert runtime.permits_carrier(value.key.profile_id, value.resource)
        sample = state.drive(lambda: observer.observe(state.sessions[role], ready=True, scenario="direct"))
        assert sample["resource"] == requests[role]["expected_physical"]
        assert state.peers[role].inventory()["host_accounting"] == before[role]
        assert act(state, requests, role, "prepare")["state"] == "prepared"
        assert ticket(state, role) is value
        with pytest.raises(ContactNotApproved):
            state.peers[role].pairing_begin(str(uuid4()), "offer")
    for role in requests:
        assert act(state, requests, role, "commit")["state"] == "pending"
    await_retirement(state, requests)


@pytest.mark.parametrize("initiator", ["windows", "android"])
@pytest.mark.parametrize("closed_before_commit", [False, True])
def test_fast_commit_preserves_slow_original_native_proof_after_mapping_release(
        manual_carriers, monkeypatch, initiator, closed_before_commit):
    state = manual_carriers
    fast, slow = initiator, "android" if initiator == "windows" else "windows"
    requests = retirement_requests(state)
    prepare_retirement(state, requests)
    original = ticket(state, slow)
    # Explicitly model the post-marker/precommit schedule by withholding the
    # slow caller's commit here. This component test has no marker transport;
    # both real owners are already prepared. Release never depends on commit.
    with retained_closed(state, slow, monkeypatch) as (received, consumed, release):
        assert act(state, requests, fast, "commit")["state"] == "pending"
        state.drive(lambda: original.cleanup_acknowledged and received.is_set())
        service = state.services[slow]
        assert service._native_resources.resolve(requests[slow]["expected_physical"]) is None
        assert service._native_resources.physical(requests[slow]["logical_session"]) is None
        assert original.admission.retired and original.close_started
        assert not original.committed and not original.native_acknowledged and not original.acknowledged
        assert retirement_observation(state, slow, requests[slow])["state"] == "prepared"
        # Actual global zero alone is insufficient for this request's receipt.
        assert state.controllers[slow].retired() is not None
        # Controller polling deliberately rejects precommit 'prepared', even
        # with actual global zero; it only accepts pending/acknowledged.
        with pytest.raises(PeerFailure, match="^invalid_carrier_retirement_reply$"):
            correlated_retired(state, slow, requests[slow])
        if closed_before_commit:
            assert release() == [("closed", requests[slow]["expected_physical"], "")]
            state.drive(consumed.is_set)
            assert original.native_acknowledged
            assert retirement_observation(state, slow, requests[slow])["state"] == "prepared"
            assert not original.acknowledged
        assert act(state, requests, slow, "commit")["state"] == "pending"
        assert ticket(state, slow) is original
        if not closed_before_commit:
            assert retirement_observation(state, slow, requests[slow])["state"] == "pending"
            assert correlated_retired(state, slow, requests[slow]) is None
            assert release() == [("closed", requests[slow]["expected_physical"], "")]
            state.drive(consumed.is_set)
            assert original.native_acknowledged
        await_retirement(state, requests)
        assert original.native_acknowledged and original.cleanup_acknowledged and original.acknowledged
        assert not original.invalidated


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_real_close_start_allows_exact_manual_projection_before_native_cleanup(
        manual_carriers, monkeypatch, initiator):
    state = manual_carriers
    requests = retirement_requests(state)
    service, host = state.services[initiator], state.hosts[initiator]
    runtime = service._connection_runtime
    close, entered, release, locks = host.close, Event(), Event(), []
    def gated_close(physical):
        assert physical == requests[initiator]["expected_physical"]
        locks.append((service._dispatch_lock._is_owned(), service._native_webrtc_lock._is_owned(),
                      runtime._lock._is_owned(), runtime.owner._lock._is_owned()))
        entered.set()
        assert release.wait(5), "independent host-close gate was not released"
        return close(physical)
    monkeypatch.setattr(host, "close", gated_close)
    try:
        request_retirement(state, requests)
        state.drive(entered.is_set)
        value = ticket(state, initiator)
        assert value.close_started and value.admission.retired
        assert not value.native_acknowledged and not value.cleanup_acknowledged
        assert state.sessions[initiator] not in service._native_webrtc_live
        runtime.synchronize()
        state.drive(lambda: value.projection_revision is not None)
        assert runtime._signatures[value.key] == (value.cleared_signature, value.revision + 1)
        runtime.synchronize()
        assert retirement_observation(state, initiator, requests[initiator])["state"] == "pending"
        assert not value.invalidated and not value.acknowledged
        assert locks == [(False, False, False, False)]
        counts = state.peers[initiator].inventory()["host_accounting"]
        assert counts["reserved_count"] == counts["allocated_count"] == 1
        assert correlated_retired(state, initiator, requests[initiator]) is None
    finally:
        release.set()
    await_retirement(state, requests)


@pytest.mark.parametrize("initiator", ["windows", "android"])
def test_stop_invalidates_prepared_ticket_without_preventing_real_cleanup(
        manual_carriers, monkeypatch, initiator):
    state = manual_carriers
    requests = retirement_requests(state)
    prepare_retirement(state, requests)
    value = ticket(state, initiator)
    with delayed_native_close(state, initiator, monkeypatch) as entered:
        state.controllers[initiator].native("reconnect_stop", contact_id=state.contacts[initiator])
        state.drive(entered.is_set)
        assert value.invalidated and not value.committed and not value.acknowledged
        with pytest.raises((ContactNotApproved, NativeUnavailable)):
            act(state, requests, initiator, "commit")
        counts = state.peers[initiator].inventory()["host_accounting"]
        assert counts["reserved_count"] == counts["allocated_count"] == counts["retiring_count"] == 1
    state.drive(lambda: all(observer.retired() is not None for observer in state.controllers.values()))
    state.controllers[initiator].native("reconnect_start", contact_id=state.contacts[initiator])
    with pytest.raises((ContactNotApproved, NativeUnavailable)):
        act(state, requests, initiator, "commit")
    assert value.invalidated and not value.acknowledged
