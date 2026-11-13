"""Exact, bounded, private carrier-loss observation; no native host calls."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from mesh_chat.connection.model import (
    Authority, Bridge, Carrier, ConnectionKey, ConnectionState, ContextChanged, Desired,
    Health, Observed, Policy, Resource, Tick,
)
from mesh_chat.connection.supervisor import ConnectionSupervisor
from mesh_chat.core_api.qualification_host import QualificationControl
from mesh_chat.errors import ContactNotApproved, ValidationError
from mesh_chat.native_pairing_service import NativePairingServiceMixin
from test_native_carrier_retirement import qualified_owner, retire, run_until
from test_pairing_runtime import native_pairing


def owner(name="target", *, policy=Policy()):
    supervisor = ConnectionSupervisor("runtime", policy)
    key = ConnectionKey("contact", name, "local", "remote")
    resource = Resource("native", "physical-" + name)
    supervisor.register(ConnectionState(
        key, "runtime", Authority(1, True, True, True), Desired.ENABLED,
        carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 1), generation=3))
    return supervisor, key, resource


def test_first_exact_suspect_and_grace_loss_are_retained_after_state_release():
    supervisor, key, resource = owner()
    trace = supervisor.watch_carrier_observation(key, resource)
    assert supervisor.carrier_observation(trace) == {
        "availability": "selected", "owner_loss": None, "suspect_precursor": None,
        "native_close": "not_observed", "order": "not_observed"}
    supervisor.dispatch(key, Observed(resource, 2, Health.SUSPECT, Bridge.READY))
    supervisor.dispatch(key, Tick(12))
    expected = supervisor.carrier_observation(trace)
    assert expected["suspect_precursor"] == {"event": "observed", "phase": "none", "reason": "observed"}
    assert expected["owner_loss"] == {"event": "tick", "phase": "none",
                                      "reason": "carrier_lost", "prior_health": "suspect"}
    assert expected["order"] == "unknown"
    expected["owner_loss"]["reason"] = "tampered"
    assert supervisor.carrier_observation(trace)["owner_loss"]["reason"] == "carrier_lost"
    supervisor.native_carrier_observation(trace, "local_request")
    assert supervisor.carrier_observation(trace)["order"] == "owner_first"
    supervisor.native_carrier_observation(trace, "callback")
    assert supervisor.carrier_observation(trace)["native_close"] == "callback_after_local_request"


def test_native_close_first_and_direct_authority_loss_are_separate_edges():
    supervisor, key, resource = owner()
    trace = supervisor.watch_carrier_observation(key, resource)
    supervisor.native_carrier_observation(trace, "callback")
    supervisor.dispatch(key, ContextChanged(2, desired=Desired.STOPPED))
    result = supervisor.carrier_observation(trace)
    assert result["native_close"] == "callback_without_local_request"
    assert result["order"] == "native_first"
    assert result["owner_loss"] == {"event": "context_changed", "phase": "none",
                                    "reason": "ineligible", "prior_health": "open"}
    assert result["suspect_precursor"] is None
    supervisor.native_carrier_observation(trace, "local_request")
    assert supervisor.carrier_observation(trace)["native_close"] == "callback_without_local_request"


def test_wrong_actor_and_resource_do_not_contaminate_selected_trace():
    supervisor, key, resource = owner()
    other = ConnectionKey("contact", "other", "local", "remote")
    supervisor.register(replace(supervisor.snapshot(key), key=other,
                                carrier=Carrier(Resource("native", "other"), 1,
                                                Health.OPEN, Bridge.READY, 1)))
    trace = supervisor.watch_carrier_observation(key, resource)
    supervisor.dispatch(other, ContextChanged(2, desired=Desired.STOPPED))
    supervisor.dispatch(key, Observed(Resource("native", "wrong"), 2, Health.ABSENT, Bridge.DETACHED))
    assert supervisor.carrier_observation(trace)["owner_loss"] is None


def test_bounded_eviction_is_unavailable_instead_of_not_observed():
    supervisor, key, resource = owner(policy=Policy(max_diagnostics=1))
    first = supervisor.watch_carrier_observation(key, resource)
    second_key = ConnectionKey("contact", "second", "local", "remote")
    second_resource = Resource("native", "second")
    supervisor.register(replace(supervisor.snapshot(key), key=second_key,
                                carrier=Carrier(second_resource, 1, Health.OPEN, Bridge.READY, 1)))
    second = supervisor.watch_carrier_observation(second_key, second_resource)
    assert supervisor.carrier_observation(first) == {
        "availability": "unavailable", "owner_loss": None, "suspect_precursor": None,
        "native_close": "unavailable", "order": "unknown"}
    assert supervisor.carrier_observation(second)["availability"] == "selected"


def test_late_watch_and_same_resource_new_tenure_are_unavailable():
    supervisor, key, resource = owner()
    trace = supervisor.watch_carrier_observation(key, resource)
    supervisor.dispatch(key, ContextChanged(2, desired=Desired.STOPPED))
    assert supervisor.watch_carrier_observation(key, resource) is None
    assert supervisor.carrier_observation(trace)["owner_loss"] is not None
    supervisor._states[key] = replace(supervisor.snapshot(key), desired=Desired.ENABLED,
        generation=4, carrier=Carrier(resource, 1, Health.OPEN, Bridge.READY, 3))
    assert supervisor.carrier_observation(trace)["availability"] == "unavailable"


def test_new_exact_watch_invalidates_previous_tenure():
    supervisor, key, resource = owner()
    first = supervisor.watch_carrier_observation(key, resource)
    second = supervisor.watch_carrier_observation(key, resource)
    assert first is not second
    assert supervisor.carrier_observation(first)["availability"] == "unavailable"
    assert supervisor.carrier_observation(second)["availability"] == "selected"


def test_native_observer_predicate_failure_does_not_escape_into_close():
    context = {"carrier_observation_anchor": (object(),), "state": "transferred",
               "session": "logical", "physical": "physical", "runtime_epoch": "runtime",
               "identity": lambda: 1 / 0}
    service = SimpleNamespace(_native_pairing_contexts={"operation": context},
                              _runtime_incarnation="runtime")
    NativePairingServiceMixin._native_pairing_carrier_edge(service, "logical", "physical", "local_request")
    assert context["carrier_observation_anchor"] is None


def test_private_inventory_exact_transferred_anchor_survives_native_release(qualified_owner):
    facts = qualified_owner
    request = {"operation_id": facts.payload["operation_id"],
               "logical_session": facts.payload["logical_session"],
               "expected_physical": facts.payload["expected_physical"],
               "expected_service_incarnation": facts.payload["expected_service_incarnation"],
               "expected_profile_incarnation": facts.sample["profile_incarnation"]}
    def observe(port=facts.port, **changes):
        return port.dispatch("qualification.inventory", {
            "carrier_observation": {**request, **changes}})["carrier_observation"]
    assert observe()["availability"] == "selected"
    assert observe(QualificationControl(lambda: facts.service, caller="other"))["availability"] == "unavailable"
    assert observe(expected_physical="wrong")["availability"] == "unavailable"
    assert observe(expected_profile_incarnation="0" * 32)["availability"] == "unavailable"
    assert observe(expected_service_incarnation="0" * 32)["availability"] == "unavailable"
    with pytest.raises(ContactNotApproved):
        observe(QualificationControl(lambda: facts.service, authorize=lambda: False))
    with pytest.raises(ValidationError):
        observe(expected_profile_incarnation="A" * 32)
    with pytest.raises(ValidationError):
        observe(expected_service_incarnation="short")
    baseline = facts.port.dispatch("qualification.inventory", {})
    identity = facts.context["identity"]
    facts.context["identity"] = lambda: object()
    assert observe()["availability"] == "unavailable"
    facts.context["identity"] = identity
    host = facts.context["host"]
    facts.context["host"] = object()
    assert observe()["availability"] == "unavailable"
    facts.context["host"] = host
    duplicate = dict(facts.context)
    facts.service._native_pairing_contexts["duplicate"] = duplicate
    assert observe()["availability"] == "unavailable"
    del facts.service._native_pairing_contexts["duplicate"]
    anchor = facts.context["carrier_observation_anchor"]
    facts.context["carrier_observation_anchor"] = (object(),)
    assert observe()["availability"] == "unavailable"
    facts.context["carrier_observation_anchor"] = anchor
    trace = anchor[-1]
    trace.owner_loss = object()
    assert observe()["availability"] == "unavailable"
    trace.owner_loss = None
    assert {key: value for key, value in facts.port.dispatch("qualification.inventory", {
        "carrier_observation": request}).items() if key != "carrier_observation"} == baseline
    assert retire(facts)["state"] == "pending"
    run_until(facts.service, lambda: facts.closed == [request["expected_physical"]])
    result = observe()
    assert result["availability"] == "selected"
    assert result["owner_loss"]["event"] == "context_changed"
    assert result["owner_loss"]["reason"] == "ineligible"
    assert result["native_close"] in {"local_request", "callback_after_local_request"}
    assert result["order"] == "owner_first"
