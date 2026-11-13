"""Cold readiness races; scripted peer calls are not native qualification."""

import copy

import pytest

from test_ui_core_boundary_interop_controller import controller, path_observer
from test_ui_core_boundary_interop_evidence import sample


def retiring_peer(state, *, replacement=True):
    state.controller.phase = "cold_start_receipts"
    state.inventory.update(v=1, qualification_only=True)
    for name, value in (("service_incarnation", "a" * 32), ("profile_incarnation", "b" * 32)):
        state.inventory[name] = state.value[name] = value
    state.error = controller.PeerFailure("native_unavailable")
    original = state.controller.peer.path
    original_row = copy.deepcopy(state.inventory["resources"][0])

    def path(*args):
        if state.error is not None:
            state.inventory["resources"] = []
        return original(*args)

    def replace():
        if replacement:
            state.inventory["resources"] = [original_row]
            state.error = None

    state.controller.peer.path = path
    state.on_sleep = replace
    return state.error


def test_cold_readiness_discards_retired_inventory_then_requires_fresh_selected_sample(path_observer):
    state = path_observer
    retiring_peer(state)
    result = state.controller.cold_ready_observation()
    assert result["resource"] == "physical"
    assert state.events == ["inventory", ("path", "logical", "physical"), "inventory",
                            "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and len(set(state.challenges)) == 2


@pytest.mark.parametrize("remaining", [0.5, 120])
def test_retired_cold_candidate_never_extends_readiness_deadline(path_observer, remaining):
    state = path_observer
    retiring_peer(state, replacement=False)
    state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.cold_ready_observation()
    assert caught.value.code == "scenario_deadline"
    assert state.now == 10 + remaining and state.sequence == 0


@pytest.mark.parametrize("code", ["contact_not_approved", "peer_closed", "invalid_peer_reply", "native_unavailable"])
def test_current_resource_and_other_errors_are_never_retried(path_observer, code):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    state.error = controller.PeerFailure(code)
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.cold_ready_observation()
    assert caught.value is state.error and state.sleeps == []


@pytest.mark.parametrize("field", ["service_incarnation", "profile_incarnation"])
def test_retirement_with_changed_incarnation_preserves_original_error(path_observer, field):
    state = path_observer
    failure = retiring_peer(state)
    original = state.controller.peer.path

    def changed(*args):
        state.inventory[field] = "c" * 32
        return original(*args)

    state.controller.peer.path = changed
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.cold_ready_observation()
    assert caught.value is failure and state.sleeps == []


def test_post_receipt_observation_never_recovers_retired_exact_resource(path_observer):
    state = path_observer
    failure = retiring_peer(state)
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.observe("logical", ready=True)
    assert caught.value is failure
    assert state.events == ["inventory", ("path", "logical", "physical")]


@pytest.mark.parametrize("fault", ["v_bool", "qualification", "service_missing", "profile_invalid", "rows_missing",
    "rows_not_list", "duplicate_logical", "duplicate_physical", "owner_invalid", "adopted_invalid", "physical_invalid",
    "still_current", "changed_service", "changed_profile", "too_many", "original_unadopted"])
def test_invalid_or_nonretired_inventory_cannot_authorize_fresh_discovery(path_observer, fault):
    from native_interop_cold_start import inventory_relation
    state = path_observer
    retiring_peer(state)
    before = copy.deepcopy(state.inventory)
    resource = before["resources"][0]
    after = copy.deepcopy(before)
    after["resources"] = []
    if fault == "v_bool": after["v"] = True
    elif fault == "qualification": after["qualification_only"] = 1
    elif fault == "service_missing": del after["service_incarnation"]
    elif fault == "profile_invalid": after["profile_incarnation"] = "private invalid text"
    elif fault == "rows_missing": del after["resources"]
    elif fault == "rows_not_list": after["resources"] = ()
    elif fault in {"changed_service", "changed_profile"}: after[fault.removeprefix("changed_") + "_incarnation"] = "c" * 32
    elif fault == "original_unadopted": resource.update(adopted=False, owner_state="unadopted")
    else:
        after["resources"] = [copy.deepcopy(resource)]
        row = after["resources"][0]
        if fault == "duplicate_logical": after["resources"].append({**row, "physical_resource": "other"})
        elif fault == "duplicate_physical": after["resources"].append({**row, "logical_session": "other"})
        elif fault == "owner_invalid": row["owner_state"] = []
        elif fault == "adopted_invalid": row["adopted"] = 1
        elif fault == "physical_invalid": row["physical_resource"] = "private invalid text"
        elif fault == "too_many": after["resources"] *= 257
    assert inventory_relation(before, resource, after) != "retired"


def test_same_logical_new_physical_requires_new_poll_and_never_uses_recheck_as_success(path_observer):
    state = path_observer
    retiring_peer(state)
    original = state.controller.peer.path
    def changed(*args):
        try: return original(*args)
        finally:
            state.inventory["resources"] = [{"logical_session": "logical", "physical_resource": "replacement",
                "adopted": True, "owner_state": "authorized"}]
    state.controller.peer.path = changed
    assert state.controller.observe(retirement_deadline=state.now + 120.0) is None
    assert state.sequence == 0 and state.controller._cold_retired_reads == 1


@pytest.mark.parametrize("late", [False, True])
def test_failed_or_late_recheck_preserves_primary_path_error(path_observer, late):
    state = path_observer
    failure = retiring_peer(state)
    original = state.controller.peer.inventory
    def inventory():
        if len(state.events) == 2:
            if not late: raise RuntimeError("PRIVATE_SECONDARY_ERROR")
            state.now += 121
        return original()
    state.controller.peer.inventory = inventory
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.cold_ready_observation()
    assert caught.value is failure and state.sleeps == []
    assert state.controller._cold_recheck == ("deadline" if late else "unavailable")


def test_late_valid_sample_cannot_extend_cold_readiness_budget(path_observer):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    original = state.controller.observe
    def observe(**kwargs):
        value = original(**kwargs)
        state.now += 121
        return value
    state.controller.observe = observe
    with pytest.raises(controller.PeerFailure, match="scenario_deadline"):
        state.controller.cold_ready_observation()
    assert state.sequence == 1 and state.sleeps == []


@pytest.mark.parametrize("stage", ["restart", "identity_receipt", "readiness", "exchange", "exact_path", "accounting", "evidence"])
def test_cold_failure_progress_is_bounded_and_exact_error_bound(path_observer, stage):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    error = controller.PeerFailure("native_unavailable")
    with pytest.raises(controller.PeerFailure):
        with state.controller._cold_step(0, True, stage):
            raise error
    assert state.controller.failure_cold_start(error) == {"cold_start_failure": {
        "iteration": 1, "completed": 0, "stage": stage, "restarted": True,
        "path_recheck": "unread", "retired_reads": 0, "retired_reads_capped": False}}
    assert state.controller.failure_cold_start(controller.PeerFailure("native_unavailable")) == {}
    state.controller.phase = "other"
    assert state.controller.failure_cold_start(error) == {}


def test_optional_cold_diagnostics_preserve_original_failure_when_projection_throws(path_observer, monkeypatch):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    error = controller.PeerFailure("native_unavailable")
    def broken(_): raise RuntimeError("PRIVATE_DIAGNOSTIC_ERROR")
    monkeypatch.setattr(controller, "cold_failure_snapshot", broken)
    with pytest.raises(controller.PeerFailure) as caught:
        with state.controller._cold_step(0, True, "readiness"):
            raise error
    assert caught.value is error and state.controller.failure_cold_start(error) == {}
    state.controller._cold_failure = (error, {})
    assert state.controller.failure_cold_start(error) == {}
