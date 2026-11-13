"""Scripted controller scheduling controls, not native qualification evidence."""

import pytest

from test_ui_core_boundary_interop_controller import controller, path_observer
from test_ui_core_boundary_interop_evidence import sample


def test_unadopted_inventory_waits_through_claim_until_owner_commit(path_observer):
    state = path_observer
    row = state.inventory["resources"][0]
    row.update(owner_state="unadopted", adopted=False)
    state.error = controller.PeerFailure("contact_not_approved")

    def advance_adoption():
        if row["owner_state"] == "unadopted":
            row.update(owner_state="pending_adoption", adopted=True)
        else:
            row["owner_state"] = "authorized"
            state.error = None

    state.on_sleep = advance_adoption
    result = state.controller.wait(
        lambda: state.controller.observe("logical", scenario="turn_udp"), timeout=120)
    assert result["resource"] == "physical"
    assert state.events == ["inventory"] * 3 + [("path", "logical", "physical")]
    assert state.sleeps == [0.25, 0.25] and state.sequence == 1


@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_unadopted_inventory_keeps_original_readiness_deadline(path_observer, remaining, polls):
    state = path_observer
    state.inventory["resources"][0].update(owner_state="unadopted", adopted=False)
    state.error = controller.PeerFailure("contact_not_approved")
    state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.wait(lambda: state.controller.observe("logical"), timeout=120)
    assert caught.value.code == "scenario_deadline"
    assert state.events == ["inventory"] * polls and state.sleeps == [0.25] * polls
    assert state.now == 10 + remaining and state.controller.samples.previous == {}


@pytest.mark.parametrize("mode", ["raw", "ambiguous", "inconsistent", "missing", "unknown", "revoked", "authorized"])
def test_unadopted_guard_never_swallows_other_authority_denials(path_observer, mode):
    state = path_observer
    row = state.inventory["resources"][0]
    row.update(owner_state="unadopted", adopted=False)
    if mode == "ambiguous":
        state.inventory["resources"].append(dict(row, physical_resource="other"))
    elif mode == "inconsistent": row["adopted"] = True
    elif mode == "missing": row.pop("adopted")
    elif mode == "unknown": row["owner_state"] = "unknown"
    elif mode == "revoked": row["owner_state"] = "unavailable"
    elif mode == "authorized": row.update(owner_state="authorized", adopted=True)
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.observe("logical", ready=mode != "raw")
    assert caught.value is state.error and state.sleeps == []
    assert state.events == ["inventory", ("path", "logical", "physical")]


def test_unadopted_inventory_records_missing_readiness_without_path_probe(path_observer):
    state, reasons = path_observer, set()
    state.inventory["resources"][0].update(owner_state="unadopted", adopted=False)
    state.error = controller.PeerFailure("contact_not_approved")
    assert state.controller.observe("logical", missing_reasons=reasons) is None
    assert reasons == {"adopted_not_true"} and state.events == ["inventory"]


def test_authority_lost_after_authorized_inventory_still_fails_exact_path_read(path_observer):
    state = path_observer
    assert state.controller.observe("logical", scenario="turn_udp")["resource"] == "physical"
    original_inventory = state.controller.peer.inventory
    denial = controller.PeerFailure("contact_not_approved")

    def inventory_then_revoke():
        result = original_inventory()
        state.inventory["resources"][0]["owner_state"] = "unavailable"
        state.error = denial
        return result

    state.controller.peer.inventory = inventory_then_revoke
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.observe("logical", scenario="turn_udp")
    assert caught.value is denial and state.sleeps == []
    assert state.events == ["inventory", ("path", "logical", "physical")] * 2
    assert state.sequence == 1


@pytest.mark.parametrize("logical", [None, "logical"])
def test_pending_reconnect_candidate_waits_for_carrier_permission(path_observer, logical):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    row = state.inventory["resources"][0]
    row.update(owner_state="pending_negotiation", adopted=True)
    state.error = controller.PeerFailure("contact_not_approved")

    def commit():
        row["owner_state"] = "authorized"
        state.error = None

    state.on_sleep = commit
    result = state.controller.wait(lambda: state.controller.observe(logical), timeout=120)
    assert result["resource"] == "physical"
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.sequence == 1


@pytest.mark.parametrize("remaining,polls", [(120, 480), (0.5, 2)])
def test_pending_reconnect_keeps_original_readiness_deadline(path_observer, remaining, polls):
    state = path_observer
    state.controller.phase = "cold_start_receipts"
    state.inventory["resources"][0].update(owner_state="pending_negotiation", adopted=True)
    state.error = controller.PeerFailure("contact_not_approved")
    state.controller.deadline = state.now + remaining
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.wait(lambda: state.controller.observe(), timeout=120)
    assert caught.value.code == "scenario_deadline"
    assert state.events == ["inventory"] * polls and state.sleeps == [0.25] * polls
    assert state.now == 10 + remaining and state.controller.samples.previous == {}


@pytest.mark.parametrize("mode", ["raw", "ambiguous", "inconsistent", "missing", "revoked", "authorized"])
def test_pending_reconnect_hint_never_swallows_authority_denials(path_observer, mode):
    state = path_observer
    row = state.inventory["resources"][0]
    row.update(owner_state="pending_negotiation", adopted=True)
    if mode == "ambiguous":
        state.inventory["resources"].append(dict(row, physical_resource="other"))
    elif mode == "inconsistent": row["adopted"] = False
    elif mode == "missing": row.pop("adopted")
    elif mode == "revoked": row["owner_state"] = "unavailable"
    elif mode == "authorized": row["owner_state"] = "authorized"
    state.error = controller.PeerFailure("contact_not_approved")
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.observe(ready=mode != "raw")
    assert caught.value is state.error and state.sleeps == []
    assert state.events == ["inventory", ("path", "logical", "physical")]


def test_pending_reconnect_then_revoked_fails_without_cached_permission(path_observer):
    state = path_observer
    row = state.inventory["resources"][0]
    row.update(owner_state="pending_negotiation", adopted=True)
    denial = controller.PeerFailure("contact_not_approved")
    state.error = denial
    state.on_sleep = lambda: row.update(owner_state="unavailable")
    with pytest.raises(controller.PeerFailure) as caught:
        state.controller.wait(lambda: state.controller.observe(), timeout=120)
    assert caught.value is denial
    assert state.events == ["inventory", "inventory", ("path", "logical", "physical")]
    assert state.sleeps == [0.25] and state.controller.samples.previous == {}


def test_pending_reconnect_records_the_reason_without_inspecting_native_path(path_observer):
    state, reasons = path_observer, set()
    state.inventory["resources"][0].update(owner_state="pending_negotiation", adopted=True)
    assert state.controller.observe(missing_reasons=reasons) is None
    assert reasons == {"pending_negotiation"}
    assert state.events == ["inventory"] and state.controller.samples.previous == {}
