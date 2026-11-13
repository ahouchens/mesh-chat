"""Exact prepared retirement component controls; no native qualification claim."""
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest

from mesh_chat.connection.model import Bridge, Carrier, ContextChanged, Execution, Health, Observed, Phase, Resource, Tick, Work
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.errors import ContactNotApproved, NativeUnavailable, ValidationError
from test_native_carrier_retirement import qualified_owner, offline, observation, retire
from test_pairing_runtime import native_pairing, run_until


def prepare(f):
    return f.port.dispatch("qualification.retire_carrier", {**f.payload, "action": "prepare"})


def commit(f):
    return f.port.dispatch("qualification.retire_carrier", {**f.payload, "action": "commit"})


def ticket(f):
    return f.context["carrier_retirement"].ticket


def lose_carrier(f):
    value = ticket(f)
    f.service._connection_runtime.owner.dispatch(value.key,
        Observed(value.resource, monotonic() + 1, Health.ABSENT, Bridge.DETACHED))


def test_prepare_preserves_current_carrier_without_scheduling_disposal(qualified_owner):
    f = qualified_owner
    payload = {**f.payload, "action": "prepare"}
    reply = f.port.dispatch("qualification.retire_carrier", payload)
    assert reply == {"request_id": f.payload["request_id"], "state": "prepared"}
    assert observation(f)["state"] == "prepared"
    assert f.closed == []
    assert f.service._native_carrier_authorized(f.payload["logical_session"])
    assert f.service._connection_runtime.owner.drain() == ()

    runtime = f.service._connection_runtime
    value = ticket(f)
    runtime.owner.dispatch(value.key, Tick(monotonic() + 6))
    work, = runtime.owner.drain()
    assert isinstance(work, Work) and work.phase is Phase.INSPECT and work.resource == value.resource
    assert runtime.permits_carrier(value.key.profile_id, value.resource)


def test_missing_action_is_not_legacy_disposal(qualified_owner):
    f = qualified_owner
    with pytest.raises(ValidationError):
        f.port.dispatch("qualification.retire_carrier", {k: v for k, v in f.payload.items() if k != "action"})
    assert f.closed == [] and "carrier_retirement" not in f.context


@pytest.mark.parametrize("action", [None, True, 1, [], {}, "", "abort", "PREPARE"])
def test_unknown_action_cannot_prepare_or_dispose(qualified_owner, action):
    f = qualified_owner
    with pytest.raises(ValidationError):
        f.port.dispatch("qualification.retire_carrier", {**f.payload, "action": action})
    assert f.closed == [] and "carrier_retirement" not in f.context


def test_commit_without_preparation_is_not_admission(qualified_owner):
    f = qualified_owner
    with pytest.raises(NativeUnavailable): commit(f)
    assert f.closed == [] and "carrier_retirement" not in f.context


@pytest.mark.parametrize("fenced", [False, True])
def test_initial_fresh_contact_mismatch_rejects_before_guard_insertion(qualified_owner, fenced):
    f = qualified_owner
    runtime = f.service._connection_runtime
    state = next(state for state in runtime.owner.snapshots() if state.carrier is not None)
    runtime._profile_values[state.key]["contact_id"] = "different-cached-contact"
    if fenced:
        runtime.fence("fresh-trusted-association")
    # Same owner key/signature; the fresh trusted contact association differs.
    assert runtime.owner.snapshot(state.key).carrier is not None
    if fenced:
        with pytest.raises(ValueError):
            runtime.prepare_carrier_retirement(state.key, state.carrier.resource, state.generation,
                state.authority.revision, contact_id="fresh-trusted-association")
    else:
        with pytest.raises(NativeUnavailable): prepare(f)
    assert "carrier_retirement" not in f.context
    assert not runtime.owner.snapshot(state.key).retirement_prepared
    assert not runtime._carrier_retirements and f.closed == []


def test_prepared_late_commit_uses_actual_owner_cleanup_and_raw_closed_after_mapping_release(qualified_owner):
    f = qualified_owner
    f.native_notifications = False
    prepare(f)
    runtime, value = f.service._connection_runtime, ticket(f)
    lose_carrier(f)
    assert value.admission.retired
    run_until(f.service, lambda: value.cleanup_acknowledged)
    assert f.service._native_resources.resolve(f.payload["expected_physical"]) is None
    assert observation(f)["state"] == "prepared" and not value.native_acknowledged
    for now in (monotonic() + 60, monotonic() + 600):
        runtime.owner.dispatch(value.key, Tick(now))
        assert not any(isinstance(effect, Work) for effect in runtime.owner.drain())
        assert runtime.owner.snapshot(value.key).generation == value.generation
    # This is the actual service raw-event consumer, after logical lookup is gone.
    f.service._handle_native_webrtc_event("closed", f.payload["expected_physical"])
    assert value.native_acknowledged
    assert commit(f)["state"] == "pending"
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    assert f.closed == [f.payload["expected_physical"]] and len(f.created) == 1
    assert not runtime.owner.snapshot(value.key).retirement_prepared


@pytest.mark.parametrize("event,data,physical", [
    ("channel", "mesh-reticulum:closed", "exact"), ("ice", "closed", "exact"),
    ("closed", "not-a-native-ack", "exact"), ("closed", "", "foreign")])
def test_absence_cleanup_and_nonmatching_events_cannot_supply_native_ack(qualified_owner, event, data, physical):
    f = qualified_owner
    f.native_notifications = False
    retire(f)
    value = ticket(f)
    run_until(f.service, lambda: value.cleanup_acknowledged)
    assert f.service.native_webrtc_inspection_resources()["resources"] == []
    f.service._handle_native_webrtc_event(event,
        f.payload["expected_physical"] if physical == "exact" else "native-foreign", data)
    f.service._connection_runtime.step()
    assert observation(f)["state"] == "pending" and not value.native_acknowledged
    f.service._handle_native_webrtc_event("closed", f.payload["expected_physical"])
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")


@pytest.mark.parametrize("committed", [False, True])
def test_same_request_is_bounded_idempotent_and_changed_nonce_cannot_retarget(qualified_owner, committed):
    f = qualified_owner
    prepare(f)
    value = ticket(f)
    if committed: commit(f)
    expected = "pending" if committed else "prepared"
    assert prepare(f)["state"] == expected
    assert ticket(f) is value and len(f.service._connection_runtime._carrier_retirements) == 1
    with pytest.raises(ValidationError):
        f.port.dispatch("qualification.retire_carrier", {**f.payload, "request_id": "d" * 32})
    assert ticket(f) is value
    with pytest.raises(ContactNotApproved):
        f.port.dispatch("qualification.pairing_begin", {"operation_id": str(uuid4()), "role": "offer"})


@pytest.mark.parametrize("denial", ["contact_stop", "all_stop", "authority", "quarantine", "execution", "generation",
                                    "host", "identity", "adapter", "observed_callback", "callback_exception"])
@pytest.mark.parametrize("committed", [False, True])
def test_active_invalidation_is_sticky_before_or_after_resume(qualified_owner, denial, committed):
    f = qualified_owner
    prepare(f)
    if committed: commit(f)
    runtime, value = f.service._connection_runtime, ticket(f)
    restore = lambda: None
    if denial == "contact_stop": runtime.fence("second"); runtime.committed_start("second")
    elif denial == "all_stop": runtime.fence(); runtime.committed_start()
    elif denial == "authority":
        token = runtime.begin_authority_change("second")
        runtime.commit_authority_change("second", token)
    elif denial == "quarantine": runtime.quarantine()
    elif denial == "execution":
        old = runtime.execution
        runtime.execution = lambda: Execution.PAUSED
        runtime.synchronize()
        runtime.execution = old
    elif denial == "generation":
        state = runtime.owner.snapshot(value.key)
        runtime.owner._states[value.key] = replace(state, generation=state.generation + 1)
    elif denial == "host":
        old = f.service._native_host
        f.service._native_host = object()
        restore = lambda: setattr(f.service, "_native_host", old)
    elif denial == "identity":
        old = f.service._identity
        f.service._identity = object()
        restore = lambda: setattr(f.service, "_identity", old)
    elif denial == "adapter":
        old = f.service._native_path_sequences[value.resource.resource_id]
        f.service._native_path_sequences[value.resource.resource_id] = ("d" * 32, old[1])
        restore = lambda: f.service._native_path_sequences.__setitem__(value.resource.resource_id, old)
    else:
        old = f.context["authorized"]
        def denied(): raise OSError("Controlled authorization callback failure")
        f.context["authorized"] = denied if denial == "callback_exception" else lambda: False
        restore = lambda: f.context.__setitem__("authorized", old)
    try:
        with pytest.raises((NativeUnavailable, ContactNotApproved)): observation(f)
    finally:
        restore()
    assert value.invalidated
    with pytest.raises((NativeUnavailable, ContactNotApproved)): commit(f)
    assert not runtime.owner.snapshot(value.key).retirement_prepared


@pytest.mark.parametrize("fault", ["missing_epoch", "recovered"])
def test_fresh_binding_is_required_for_initial_preparation(qualified_owner, fault):
    f = qualified_owner
    if fault == "missing_epoch":
        f.service._native_path_sequences.pop(f.payload["expected_physical"])
    else:
        f.service._native_recovered_bindings[f.payload["logical_session"]] = object()
    with pytest.raises(NativeUnavailable): prepare(f)
    assert "carrier_retirement" not in f.context and not f.closed


@pytest.mark.parametrize("change", ["reason", "consent", "manual_reversal"])
def test_extra_authority_change_after_close_start_cannot_use_projection_exception(qualified_owner, monkeypatch, change):
    f = qualified_owner
    entered, release = Event(), Event()
    original = f.host.close
    runtime = f.service._connection_runtime
    def close(physical):
        entered.set()
        assert release.wait(3)
        original(physical)
    monkeypatch.setattr(f.host, "close", close)
    try:
        retire(f)
        value = ticket(f)
        runtime.step()
        assert entered.wait(2)
        runtime.synchronize()
        assert value.projection_revision == value.revision + 1
        if change == "manual_reversal":
            monkeypatch.setattr(f.service, "native_manual_carrier_authorized", lambda _: True)
        elif change == "consent":
            profile = f.service._reconnect_profile(value.key.profile_id)
            f.service.store.put("reconnect_profile", profile["id"], {**profile, "auto_reconnect": True})
        else:
            public = f.service._reconnect_profile_public
            monkeypatch.setattr(f.service, "_reconnect_profile_public", lambda profile: {
                **public(profile), "effective": {"ready": False, "reasons": ["peer_capabilities_expired"]}})
        with pytest.raises((ContactNotApproved, NativeUnavailable)): observation(f)
        assert value.invalidated
    finally:
        release.set()


def test_close_start_allows_only_one_exact_projection_successor_before_cleanup(qualified_owner, monkeypatch):
    f = qualified_owner
    entered, release = Event(), Event()
    original = f.host.close
    runtime = f.service._connection_runtime
    locks = []
    def close(physical):
        locks.append((f.service._dispatch_lock._is_owned(), f.service._native_webrtc_lock._is_owned(),
                      runtime._lock._is_owned(), runtime.owner._lock._is_owned()))
        entered.set()
        assert release.wait(3)
        original(physical)
    monkeypatch.setattr(f.host, "close", close)
    try:
        retire(f)
        value = ticket(f)
        runtime.step()
        assert entered.wait(2)
        assert value.close_started and not value.native_acknowledged and not value.cleanup_acknowledged
        runtime.synchronize()
        assert runtime._signatures[value.key] == (value.cleared_signature, value.revision + 1)
        assert value.projection_revision == value.revision + 1
        runtime.synchronize()
        assert observation(f)["state"] == "pending" and not value.invalidated
        assert locks == [(False, False, False, False)]
    finally:
        release.set()
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")


def test_terminal_receipt_survives_later_generation_without_touching_new_owner(qualified_owner):
    f = qualified_owner
    retire(f)
    run_until(f.service, lambda: observation(f)["state"] == "acknowledged")
    runtime, value = f.service._connection_runtime, ticket(f)
    state = runtime.owner.snapshot(value.key)
    replacement = Resource("native", "new-physical")
    runtime.owner._states[value.key] = replace(state, generation=state.generation + 1,
        carrier=Carrier(replacement, state.authority.revision, Health.OPEN, Bridge.READY, monotonic()))
    before = runtime.owner.snapshot(value.key)
    assert prepare(f)["state"] == commit(f)["state"] == observation(f)["state"] == "acknowledged"
    assert runtime.owner.snapshot(value.key) == before and f.closed == [f.payload["expected_physical"]]


@pytest.mark.parametrize("edge", ["carrier_retirement_close_started", "carrier_retirement_native_closed"])
def test_throwing_proof_and_secondary_invalidation_do_not_block_disposal(qualified_owner, monkeypatch, edge):
    f = qualified_owner
    prepare(f)
    runtime, value = f.service._connection_runtime, ticket(f)
    commit(f)
    def failed(*_args, **_kwargs):
        raise OSError("Controlled proof observer failure")
    with monkeypatch.context() as scoped:
        scoped.setattr(runtime, edge, failed)
        scoped.setattr(runtime, "invalidate_carrier_retirement", failed)
        runtime._effects()
        deadline = monotonic() + 3
        while f.service._native_resources.resolve(f.payload["expected_physical"]) is not None and monotonic() < deadline:
            Event().wait(.002)
        assert f.service._native_resources.resolve(f.payload["expected_physical"]) is None
        # Drain the real callback consumer before restoring the controlled faults.
        f.service._handle_native_webrtc_event("closed", f.payload["expected_physical"])
        assert value.invalidated
        assert f.closed == [f.payload["expected_physical"]]
        with pytest.raises((NativeUnavailable, ContactNotApproved)): observation(f)
    runtime.invalidate_carrier_retirement(value)
    assert not runtime.owner.snapshot(value.key).retirement_prepared


def test_authorization_denial_at_final_private_recheck_invalidates_preparation(qualified_owner):
    f = qualified_owner
    prepare(f)
    calls = []
    def authorize():
        calls.append(True)
        return len(calls) == 1
    port = QualificationControl(lambda: f.service, authorize=authorize)
    with pytest.raises(ContactNotApproved):
        port.dispatch("qualification.retire_carrier", {**f.payload, "action": "commit"})
    assert ticket(f).invalidated
    with pytest.raises((NativeUnavailable, ContactNotApproved)): commit(f)
