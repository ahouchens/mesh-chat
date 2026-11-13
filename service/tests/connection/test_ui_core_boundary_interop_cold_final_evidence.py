"""Cold-loop final evidence attribution; scripted observations are not native proof."""

import copy
import pytest

from test_ui_core_boundary_interop_controller import cold_setup_controller, controller, evidence
from test_ui_core_boundary_interop_evidence import sample


def cold_final_case(monkeypatch, sample, failure):
    state = cold_setup_controller(monkeypatch, role="android")
    instance, peer = state.controller, state.controller.peer
    instance.workload = controller.required_workload("quick")
    instance.identity = evidence.digest("PRIVATE_IDENTITY")
    state.index, state.exchanges, state.observations, state.starts = -1, [], [], 0
    original_core = peer.core
    def core(operation, params, key=None):
        if operation == "runtime.capabilities": return {"profiles": [instance.profile]}
        return original_core(operation, params, key)
    def inventory():
        return {"service_incarnation": str(state.starts), "resources": ["PRIVATE_RESOURCE"]}
    def start():
        state.starts += 1
        return inventory()
    def ready():
        state.index += 1
        value = copy.deepcopy(sample[0])
        value["sample_sequence"] = state.index * 2 + 1
        value["application"] = dict.fromkeys(evidence.APPLICATION, state.index * 2 + 1)
        state.before = value
        return value
    def observe(logical, *, ready, missing_reasons=None):
        assert logical == state.before["logical_session"] and ready is True
        state.observations.append(state.index)
        value = copy.deepcopy(state.before)
        value["sample_sequence"] += 1
        value["application"] = {key: count + 1 for key, count in value["application"].items()}
        return failure(state, value, missing_reasons) if state.index == 1 else value
    def exchange(scenario, index):
        assert scenario == "cold_start_receipts"
        state.exchanges.append(index)
        return {"outbound": "a" * 64, "inbound": "b" * 64}, f"PRIVATE_MESSAGE_{index}"
    monkeypatch.setattr(peer, "core", core)
    monkeypatch.setattr(peer, "inventory", inventory)
    monkeypatch.setattr(peer, "stop", lambda **_: None)
    monkeypatch.setattr(peer, "start", start, raising=False)
    monkeypatch.setattr(instance, "approved_contact", lambda: instance.contact)
    monkeypatch.setattr(instance, "snapshot", lambda: {"profile": {"destination_hash": "PRIVATE_IDENTITY"}})
    monkeypatch.setattr(instance, "delivered", lambda _: True)
    monkeypatch.setattr(instance, "cold_ready_observation", ready)
    monkeypatch.setattr(instance, "observe", observe)
    monkeypatch.setattr(instance, "exchange", exchange)
    monkeypatch.setattr(instance, "warm_counts", lambda: {"leases": 1})
    monkeypatch.setattr(instance, "wait", lambda callback, **_: callback())
    return state


@pytest.mark.parametrize("reason", ["no_resource", "pending_adoption", "pending_negotiation", "adopted_not_true",
                                    "attached_not_true", "messaging_ready_not_true", "nonselected"])
def test_cold_exact_missing_path_retains_existing_skip_without_retry(monkeypatch, sample, reason):
    def missing(state, value, reasons):
        controller.record_final_path_skip(reasons, reason)
        return None
    state = cold_final_case(monkeypatch, sample, missing)
    deadline = state.controller.deadline
    with pytest.raises(ValueError, match="Cold-start receipt lost its exact native resource") as caught:
        state.controller.cold_starts()
    assert state.controller.failure_final_evidence(caught.value) == {"final_evidence_failure": {
        "scenario": "cold_start_receipts", "stage": "final_observation", "reason": "path_missing", "skip_reason": reason}}
    assert state.controller.failure_cold_start(caught.value)["cold_start_failure"] == {
        "iteration": 2, "completed": 1, "stage": "exact_path", "restarted": False,
        "path_recheck": "unread", "retired_reads": 0, "retired_reads_capped": False}
    assert state.observations == state.exchanges == [0, 1]
    assert state.starts == 1 and state.controller.deadline == deadline
    assert state.controller.failure_final_evidence(ValueError("PRIVATE_FOREIGN")) == {}


@pytest.mark.parametrize("change,reason,fields", [
    ("resource", "native_identity_changed", ["resource"]),
    ("pair", "selected_pair_changed", None),
    ("sequence", "sample_sequence_not_increasing", None),
    ("received_packets", "required_delta_missing", ["received_packets"]),
])
def test_cold_final_traffic_rejection_retains_fixed_labels(monkeypatch, sample, change, reason, fields):
    def changed(state, value, reasons):
        if change == "resource": value["resource"] = "PRIVATE_OTHER"
        elif change == "pair": value["pair"]["token"] = "f" * 32
        elif change == "sequence": value["sample_sequence"] = state.before["sample_sequence"]
        else: value["application"][change] = state.before["application"][change]
        return value
    state = cold_final_case(monkeypatch, sample, changed)
    with pytest.raises(ValueError) as caught:
        state.controller.cold_starts()
    expected = {"scenario": "cold_start_receipts", "stage": "final_traffic", "reason": reason}
    if fields is not None: expected["fields"] = fields
    assert state.controller.failure_final_evidence(caught.value) == {"final_evidence_failure": expected}
    assert state.controller.failure_cold_start(caught.value)["cold_start_failure"]["stage"] == "evidence"
    assert state.observations == state.exchanges == [0, 1] and len(state.controller.cycles) == 1


def test_cold_observation_error_preserves_original_path_substage(monkeypatch, sample):
    failure = ValueError("PRIVATE_PATH_ERROR")
    def broken(state, value, reasons):
        with state.controller._substage("path_validation"):
            raise failure
    state = cold_final_case(monkeypatch, sample, broken)
    with pytest.raises(ValueError) as caught:
        state.controller.cold_starts()
    assert caught.value is failure
    assert state.controller.failure_observation(failure) == {"failure_substage": "path_validation"}
    assert state.controller.failure_final_evidence(failure) == {}
    assert state.observations == [0, 1]


def test_cold_optional_skip_projection_cannot_replace_missing_path(monkeypatch, sample):
    state = cold_final_case(monkeypatch, sample, lambda *_: None)
    def broken(*_): raise RuntimeError("PRIVATE_PROJECTION_ERROR")
    monkeypatch.setattr(controller, "final_path_missing_reason", broken)
    with pytest.raises(ValueError, match="Cold-start receipt lost its exact native resource") as caught:
        state.controller.cold_starts()
    assert state.controller.failure_final_evidence(caught.value)["final_evidence_failure"]["skip_reason"] == "unavailable"
    assert state.observations == [0, 1]


@pytest.mark.parametrize("broken", ["classifier", "validator"])
def test_cold_traffic_optional_projection_preserves_original_error(monkeypatch, sample, broken):
    def missing_delta(state, value, reasons):
        value["application"]["received_packets"] = state.before["application"]["received_packets"]
        return value
    state = cold_final_case(monkeypatch, sample, missing_delta)
    primary = []
    original = controller.traffic
    def traffic(before, after):
        try: return original(before, after)
        except ValueError as error:
            primary.append(error)
            raise
    def fail(*_): raise RuntimeError("PRIVATE_PROJECTION_ERROR")
    monkeypatch.setattr(controller, "traffic", traffic)
    monkeypatch.setattr(controller, "traffic_failure_details" if broken == "classifier"
                        else "final_evidence_failure_observation", fail)
    with pytest.raises(ValueError) as caught:
        state.controller.cold_starts()
    assert primary == [caught.value]
    assert state.controller.failure_final_evidence(caught.value) == {}
    assert state.observations == state.exchanges == [0, 1]
