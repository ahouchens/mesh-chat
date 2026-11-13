"""Existing-poll carrier loss evidence; no native qualification claims."""

import copy
import json

import pytest

from test_ui_core_boundary_interop_controller import controller, path_observer
from test_ui_core_boundary_interop_evidence import sample
from test_ui_core_boundary_interop_peers import peers
import native_interop_carrier_observation as diagnostic


TARGET = {"operation_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    "logical_session": "logical", "expected_physical": "physical",
    "expected_service_incarnation": "b" * 32, "expected_profile_incarnation": "c" * 32}
CAUSE = {"availability": "selected", "owner_loss": None, "suspect_precursor": None,
    "native_close": "not_observed", "order": "not_observed"}


@pytest.mark.parametrize("role", ["windows", "android"])
def test_carrier_target_uses_one_existing_inventory_request(role):
    calls = []
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    if role == "windows": peer.private = lambda *args: calls.append(args) or {"resources": []}
    else: peer._request = lambda *args: calls.append(args) or {"resources": []}
    assert peer.inventory(carrier_observation=TARGET) == {"resources": []}
    expected = ("qualification.inventory", {"carrier_observation": TARGET}) if role == "windows" else (
        "inspect", {"command": "qualification.inventory", "payload": {"carrier_observation": TARGET}})
    assert calls == [expected]
    with pytest.raises(peers.PeerFailure):
        peer.inventory(carrier_observation=TARGET, operation_id=TARGET["operation_id"], request_id="d" * 32)
    assert len(calls) == 1


def setup_observation(state):
    instance = state.controller
    instance.pairing = TARGET["operation_id"]
    instance.phase = "turn_tcp_kernel_block_negative_control"
    before = dict(state.value, service_incarnation="b" * 32, profile_incarnation="c" * 32)
    state.inventory.update(service_incarnation="b" * 32, profile_incarnation="c" * 32,
                           carrier_observation=copy.deepcopy(CAUSE))
    requests = []
    original = instance.peer.inventory
    def inventory(**kwargs):
        requests.append(kwargs)
        return original()
    instance.peer.inventory = inventory
    return instance, before, requests


def test_existing_final_polls_capture_loss_without_extra_calls(path_observer):
    state = path_observer
    instance, before, requests = setup_observation(state)
    state.inventory["resources"] = []
    instance._begin_final_carrier_observation(before, "turn_tcp")
    assert instance.final_ready_observation("logical", "turn_tcp", state.now + 0.5) == (None, {"no_resource"})
    result = instance._final_carrier_observation.snapshot()
    assert result["polls"] == 2 and result["first_missing_ms"] == 0
    assert result["first"]["matching_resources"] == result["last"]["matching_resources"] == 0
    assert result["last"]["carrier_observation"] == CAUSE
    assert requests == [{"carrier_observation": TARGET}] * 2
    assert state.events == ["inventory"] * 2 and state.sleeps == [0.25] * 2
    assert all(json.dumps(secret) not in json.dumps(result) for secret in TARGET.values())


@pytest.mark.parametrize("foreign", ["phase", "pairing", "logical", "scenario"])
def test_foreign_poll_invalidates_carrier_attribution(path_observer, foreign):
    state = path_observer
    instance, before, requests = setup_observation(state)
    state.inventory["resources"] = []
    instance._begin_final_carrier_observation(before, "turn_tcp")
    if foreign == "phase": instance.phase = "other"
    if foreign == "pairing": instance.pairing = "other"
    instance.observe("other" if foreign == "logical" else "logical",
                     scenario="turn_tls" if foreign == "scenario" else "turn_tcp")
    assert requests == [{}]
    assert instance._final_carrier_observation is None


def test_expired_final_window_keeps_zero_inventory_calls(path_observer):
    state = path_observer
    instance, before, requests = setup_observation(state)
    instance._begin_final_carrier_observation(before, "turn_tcp")
    assert instance.final_ready_observation("logical", "turn_tcp", state.now) == (None, set())
    assert requests == [] and instance._final_carrier_observation.snapshot() is None


@pytest.mark.parametrize("change", ["none", "exception", "phase", "pairing", "scenario", "observer", "cleanup"])
def test_failure_projection_binds_exact_final_error_and_target(path_observer, change):
    state = path_observer
    instance, before, _ = setup_observation(state)
    state.inventory["resources"] = []
    instance._negative_diagnostics = controller.reset_negative_control(instance._negative_diagnostics, "turn_tcp")
    instance._begin_final_carrier_observation(before, "turn_tcp")
    instance.final_ready_observation("logical", "turn_tcp", state.now + 0.25)
    error = ValueError("PRIVATE_FAILURE")
    instance._final_path_failure = error, "no_resource"
    instance._record_final_carrier_failure(error)
    controller.negative_control_error(instance._negative_diagnostics, "final_observation", error, "path_missing")
    if change == "exception": error = ValueError("PRIVATE_OTHER")
    if change == "phase": instance.phase = "other"
    if change == "pairing": instance.pairing = "other"
    if change == "scenario": instance._final_carrier_observation.scenario = "turn_tls"
    if change == "observer": instance._final_carrier_observation = None
    if change == "cleanup":
        error = ValueError("PRIVATE_CLEANUP")
        controller.negative_control_error(instance._negative_diagnostics, "fault_cleanup", error)
    result = instance.failure_final_carrier(error)
    assert bool(result) is (change == "none")
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("mutation", [
    {"availability": "PRIVATE"}, {"extra": "PRIVATE"}, {"native_close": "PRIVATE"},
    {"order": "native_first"}, {"availability": "unavailable"},
    {"owner_loss": {"event": "tick", "phase": "inspect", "reason": "PRIVATE", "prior_health": "suspect"}},
    {"owner_loss": []}, {"suspect_precursor": {"event": "PRIVATE"}},
])
def test_untrusted_cause_is_explicitly_unavailable_without_changing_poll(path_observer, mutation):
    state = path_observer
    instance, before, requests = setup_observation(state)
    state.inventory["resources"] = []
    state.inventory["carrier_observation"].update(mutation)
    instance._begin_final_carrier_observation(before, "turn_tcp")
    assert instance.final_ready_observation("logical", "turn_tcp", state.now + 0.25)[0] is None
    result = instance._final_carrier_observation.snapshot()
    assert result["last"]["carrier_observation"] == diagnostic.unavailable_cause()
    assert "PRIVATE" not in json.dumps(result) and len(requests) == 1


def test_bounded_summary_retains_first_loss_and_explicit_count_caps():
    observation = diagnostic.FinalCarrierObservation(dict(TARGET), "turn_tcp", "phase", 0)
    inventory = {"resources": [], "carrier_observation": CAUSE}
    observation.observe(inventory, 1)
    inventory["resources"] = [{"logical_session": "logical", "physical_resource": "physical",
        "owner_state": "authorized", "adopted": True}] * 20
    for index in range(600):
        inventory["service_incarnation"] = TARGET["expected_service_incarnation"] if index % 2 else "other"
        observation.observe(inventory, index + 2)
    result = observation.snapshot()
    assert result["polls"] == result["transitions"] == 512
    assert result["polls_capped"] is result["transitions_capped"] is True
    assert result["first_missing_ms"] == 1000 and result["first"]["matching_resources"] == 0
    assert result["last"]["matching_resources"] == result["last"]["total_resources"] == 16
    assert result["last"]["matching_capped"] is result["last"]["total_capped"] is True
    assert result["last"]["owner_state"] == "unknown" and result["last"]["adopted"] is None


@pytest.mark.parametrize("mutation", [
    {"operation_id": "PRIVATE"}, {"operation_id": TARGET["operation_id"].upper()},
    {"logical_session": "x" * 129}, {"expected_physical": "PRIVATE\n"},
    {"expected_service_incarnation": True}, {"expected_profile_incarnation": "C" * 32},
    {"extra": "PRIVATE"},
])
@pytest.mark.parametrize("role", ["windows", "android"])
def test_invalid_target_rejected_before_io(role, mutation):
    peer = object.__new__(peers.WindowsPeer if role == "windows" else peers.AndroidPeer)
    def unexpected(*args): pytest.fail("Invalid target reached I/O")
    peer.private = peer._request = unexpected
    with pytest.raises(peers.PeerFailure, match="invalid_carrier_observation_request"):
        peer.inventory(carrier_observation={**TARGET, **mutation})


def test_owner_loss_and_native_order_remain_exact_fixed_facts():
    cause = {**CAUSE, "owner_loss": {"event": "tick", "phase": "none", "reason": "carrier_lost", "prior_health": "suspect"},
        "suspect_precursor": {"event": "failed", "phase": "inspect", "reason": "phase_timeout"},
        "native_close": "callback_after_local_request", "order": "owner_first"}
    assert diagnostic.carrier_cause(cause) == cause
    projected = diagnostic.carrier_cause(cause)
    cause["owner_loss"]["reason"] = "PRIVATE"
    assert projected["owner_loss"]["reason"] == "carrier_lost"


def test_inventory_observer_failure_does_not_replace_original_path_denial(path_observer, monkeypatch):
    state = path_observer
    instance, before, requests = setup_observation(state)
    instance._begin_final_carrier_observation(before, "turn_tcp")
    def fail(*args): raise RuntimeError("PRIVATE_DIAGNOSTIC")
    monkeypatch.setattr(instance._final_carrier_observation, "observe", fail)
    state.error = peers.PeerFailure("contact_not_approved")
    with pytest.raises(peers.PeerFailure) as caught:
        instance.observe("logical", scenario="turn_tcp")
    assert caught.value is state.error and len(requests) == 1
    assert instance._final_carrier_observation is None


@pytest.mark.parametrize("change", ["service_incarnation", "profile_incarnation", "replacement"])
def test_incarnation_mismatch_discards_cause_but_replacement_does_not(change):
    inventory = {"resources": [], "service_incarnation": "b" * 32,
        "profile_incarnation": "c" * 32, "carrier_observation": CAUSE}
    if change == "replacement":
        inventory["resources"] = [{"logical_session": "logical", "physical_resource": "replacement"}]
    else: inventory[change] = "d" * 32
    result = diagnostic.inventory_fact(inventory, TARGET)
    assert result["carrier_observation"] == (CAUSE if change == "replacement" else diagnostic.unavailable_cause())
    if change == "replacement": assert result["expected_physical"] is False


def test_malformed_active_observer_cannot_replace_inventory_or_path_error(path_observer):
    state = path_observer
    instance, _, requests = setup_observation(state)
    instance._final_carrier_observation = {"PRIVATE": "MALFORMED"}
    state.error = peers.PeerFailure("contact_not_approved")
    with pytest.raises(peers.PeerFailure) as caught:
        instance.observe("logical", scenario="turn_tcp")
    assert caught.value is state.error and requests == [{}]
    assert instance._final_carrier_observation is None


@pytest.mark.parametrize("cleanup_error", [False, True])
def test_main_emits_only_exact_final_carrier_failure(tmp_path, monkeypatch, capsys, sample, cleanup_error):
    import test_ui_core_boundary_interop_controller as harness
    original_factory = harness.negative_control_case
    actual_observe = controller.Controller.observe
    def factory(*args, **kwargs):
        state = original_factory(*args, **kwargs)
        instance = state.controller
        instance.deadline = 2.5
        initial_observe = instance.observe
        def observe(*args, **kwargs):
            if state.observation < 2: return initial_observe(*args, **kwargs)
            return actual_observe(instance, *args, **kwargs)
        def inventory(*, carrier_observation):
            assert carrier_observation == {"operation_id": instance.pairing,
                "logical_session": state.current["logical_session"], "expected_physical": state.current["resource"],
                "expected_service_incarnation": "b" * 32, "expected_profile_incarnation": "c" * 32}
            state.inventories.append("final")
            return {"resources": [], "service_incarnation": "b" * 32,
                "profile_incarnation": "c" * 32, "carrier_observation": CAUSE}
        instance.observe, instance.peer.inventory = observe, inventory
        return state
    monkeypatch.setattr(harness, "negative_control_case", factory)
    run = harness.run_negative_control_report(tmp_path, monkeypatch, capsys, sample,
        point="success", cleanup_error=cleanup_error)
    assert run.code == 1 and "PRIVATE" not in run.output
    assert run.state.inventories == ["final", "final"] and not run.state.requests
    if cleanup_error:
        assert run.record["failure_type"] == "RuntimeError" and "final_carrier_observation" not in run.record
    else:
        assert run.record["failure_type"] == "ValueError" and run.record["final_path_missing"] == "no_resource"
        result = run.record["final_carrier_observation"]
        assert result["polls"] == 2 and result["last"]["carrier_observation"] == CAUSE
