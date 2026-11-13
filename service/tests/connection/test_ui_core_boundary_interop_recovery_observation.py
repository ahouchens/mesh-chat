"""Failure-only blocked-message evidence from existing controller query polls."""

from pathlib import Path
import copy
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_diagnostics as diagnostics


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def blocked_controller(monkeypatch, restored_states, *, role="windows", blocked_state="sending"):
    clock = Clock()
    monkeypatch.setattr(controller, "time", SimpleNamespace(
        monotonic=clock.monotonic, sleep=clock.sleep))
    calls = []
    holder = {}
    restored_polls = [0]

    class Peer:
        def core(self, operation, params, key=None):
            calls.append((operation, dict(params)))
            if operation == "message.enqueue":
                return {"accepted": True, "message": "PRIVATE_HANDLE"}
            assert operation == "message.query"
            assert params["message"] == "PRIVATE_HANDLE"
            observer = holder["instance"]._recovery_diagnostics
            phase = observer._phase if observer is not None else (
                "restored_delivery" if clock.now >= 2 else "blocked_receipt")
            if phase == "blocked_receipt":
                return {"state": blocked_state}
            position = restored_polls[0]
            restored_polls[0] += 1
            return {"state": restored_states[min(position, len(restored_states) - 1)]}

    instance = controller.Controller(role, Peer(), None, None,
        {"run_id": "PRIVATE_RUN", "run_attempt": 1})
    holder["instance"] = instance
    instance.profile = "PRIVATE_PROFILE"
    instance.contact = {"core_handle": "PRIVATE_RECIPIENT"}
    instance.receive = lambda _: {"approved": True}
    instance.publish = lambda *_: None
    instance._prepare_negative_control = lambda _: SimpleNamespace(
        send=lambda *_: None, receive=lambda *_, **__: True)
    instance.records = lambda *_: [{"id": "PRIVATE_RECORD"}]
    return instance, clock, calls


@pytest.mark.parametrize("last_state", ["sending", "queued", "received_by_endpoint"])
def test_restored_failure_records_existing_query_states_and_preserves_deadline(
        monkeypatch, last_state):
    instance, clock, calls = blocked_controller(monkeypatch, [last_state])
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(None, "impaired")
    assert caught.value.code == "scenario_deadline"
    assert clock.now == pytest.approx(92.0)
    assert instance.failure_negative_control(caught.value) == {
        "negative_control": {"scenario": "impaired", "stage": "restored_delivery"}}
    evidence = instance.failure_recovery(caught.value)["recovery_delivery"]
    assert evidence["scenario"] == "impaired"
    blocked, restored = evidence["blocked_receipt"], evidence["restored_delivery"]
    assert blocked["polls"] > 0 and blocked["first_state"] == blocked["last_state"] == "sending"
    assert blocked["first_elapsed_ms"] == 0
    assert restored["polls"] > 0 and restored["first_state"] == restored["last_state"] == last_state
    assert restored["transitions"] == 0
    assert restored["first_transition_elapsed_ms"] is None
    assert restored["last_transition_elapsed_ms"] is None
    assert 0 <= restored["first_elapsed_ms"] <= restored["last_elapsed_ms"] <= 90000
    assert sum(name == "message.enqueue" for name, _ in calls) == 1
    assert all(name in {"message.enqueue", "message.query"} for name, _ in calls)
    assert "PRIVATE" not in str(evidence)


def test_success_delivery_uses_same_boolean_and_has_no_failure_wire(monkeypatch):
    instance, clock, calls = blocked_controller(monkeypatch,
        ["sending", "queued", "received_by_endpoint", "delivered"])
    result, deadline = instance.negative(None, "impaired")
    assert result["delivered_after_restore"] is True
    assert result["delivered_while_blocked"] is False
    assert deadline == pytest.approx(92.0)
    assert clock.now < deadline
    assert instance.failure_recovery(controller.PeerFailure("scenario_deadline")) == {}
    assert sum(name == "message.enqueue" for name, _ in calls) == 1
    assert "recovery_delivery" not in result


def test_blocked_receipt_failure_never_emits_recovery_evidence(monkeypatch):
    instance, _, _ = blocked_controller(monkeypatch, ["sending"], blocked_state="delivered")
    with pytest.raises(ValueError) as caught:
        instance.negative(None, "impaired")
    assert instance.failure_negative_control(caught.value) == {
        "negative_control": {
            "scenario": "impaired", "stage": "blocked_receipt", "reason": "receipt_while_blocked"}}
    assert instance.failure_recovery(caught.value) == {}


def test_failure_observation_is_bound_to_exact_error_scope_and_fixed_schema(monkeypatch):
    instance, _, _ = blocked_controller(monkeypatch, ["sending"])
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(None, "impaired")
    error = caught.value
    assert instance.failure_recovery(controller.PeerFailure("scenario_deadline")) == {}
    original = instance._recovery_failure
    instance._recovery_failure = error, "impaired", "FOREIGN_HANDLE", original[3]
    assert instance.failure_recovery(error) == {}
    instance._recovery_failure = original
    malformed = original[3]._phases["restored_delivery"]
    malformed["last_state"] = "PRIVATE_PATH"
    assert instance.failure_recovery(error) == {}
    assert diagnostics.recovery_delivery_observation({
        "scenario": "impaired", "blocked_receipt": {}, "restored_delivery": {}}) is None


def test_broken_failure_projection_cannot_replace_primary_exception(monkeypatch):
    instance, _, _ = blocked_controller(monkeypatch, ["sending"])
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(None, "impaired")
    monkeypatch.setattr(diagnostics.RecoveryDeliveryDiagnostics, "failure_observation",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE_PROJECTION")))
    assert instance.failure_recovery(caught.value) == {}
    assert caught.value.code == "scenario_deadline"


def test_broken_optional_observer_preserves_original_failure_and_cleanup(monkeypatch):
    instance, clock, _ = blocked_controller(monkeypatch, ["sending"], role="android")
    fault = SimpleNamespace(blocked=False, unblocked=False)
    def block():
        fault.blocked = True
    def unblock():
        fault.unblocked = True
        return 1
    fault.block, fault.unblock = block, unblock
    monkeypatch.setattr(diagnostics.RecoveryDeliveryDiagnostics, "observe",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE_OBSERVER")))
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(fault, "impaired")
    assert caught.value.code == "scenario_deadline"
    assert fault.blocked and fault.unblocked
    assert clock.now == pytest.approx(92.0)
    assert instance.failure_recovery(caught.value) == {}
    assert instance.failure_negative_control(caught.value) == {
        "negative_control": {"scenario": "impaired", "stage": "restored_delivery"}}


def test_unknown_core_state_disables_optional_evidence_without_changing_deadline(monkeypatch):
    instance, clock, _ = blocked_controller(monkeypatch, ["PRIVATE_UNKNOWN_STATE"])
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(None, "impaired")
    assert caught.value.code == "scenario_deadline"
    assert clock.now == pytest.approx(92.0)
    assert instance.failure_recovery(caught.value) == {}


def test_recovery_observer_caps_counts_and_projects_no_private_fields():
    observer = diagnostics.RecoveryDeliveryDiagnostics("turn_tcp", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "sending", 0.0)
    observer.start("restored_delivery", 2.0)
    for index in range(600):
        observer.observe("PRIVATE_HANDLE", "queued" if index % 2 else "sending", 2.0 + index)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    value = observer.failure_observation(error, "turn_tcp", "PRIVATE_HANDLE")
    restored = value["restored_delivery"]
    assert restored["polls"] == diagnostics.RECOVERY_POLL_CAP and restored["polls_capped"]
    assert restored["transitions"] == diagnostics.RECOVERY_POLL_CAP and restored["transitions_capped"]
    assert restored["first_transition_elapsed_ms"] == 1000
    assert restored["last_transition_elapsed_ms"] == diagnostics.RECOVERY_ELAPSED_MS_CAP
    assert restored["last_elapsed_ms"] == diagnostics.RECOVERY_ELAPSED_MS_CAP
    assert restored["elapsed_capped"]
    assert "PRIVATE" not in str(value)


def test_recovery_observer_records_first_and_last_transition_from_existing_polls():
    observer = diagnostics.RecoveryDeliveryDiagnostics("impaired", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "queued", 0.0)
    observer.observe("FOREIGN_HANDLE", "sending", 0.5)
    observer.observe("PRIVATE_HANDLE", "sending", 1.0)
    observer.observe("PRIVATE_HANDLE", "queued", 2.0)
    observer.start("restored_delivery", 3.0)
    observer.observe("PRIVATE_HANDLE", "sending", 3.0)
    observer.observe("PRIVATE_HANDLE", "queued", 4.0)
    observer.observe("PRIVATE_HANDLE", "sending", 5.0)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    value = observer.failure_observation(error, "impaired", "PRIVATE_HANDLE")
    for phase in ("blocked_receipt", "restored_delivery"):
        item = value[phase]
        assert item["transitions"] == 2
        assert item["first_transition_elapsed_ms"] == 1000
        assert item["last_transition_elapsed_ms"] == 2000
    assert "PRIVATE" not in str(value)


def test_one_sending_to_queued_transition_keeps_its_time_after_later_polls():
    observer = diagnostics.RecoveryDeliveryDiagnostics("impaired", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "sending", 0.0)
    observer.start("restored_delivery", 2.0)
    observer.observe("PRIVATE_HANDLE", "sending", 2.0)
    observer.observe("PRIVATE_HANDLE", "queued", 20.0)
    observer.observe("PRIVATE_HANDLE", "queued", 90.0)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    value = observer.failure_observation(error, "impaired", "PRIVATE_HANDLE")
    restored = value["restored_delivery"]
    assert restored["transitions"] == 1
    assert restored["first_transition_elapsed_ms"] == 18000
    assert restored["last_transition_elapsed_ms"] == 18000
    assert restored["last_elapsed_ms"] == 88000
    restored["last_transition_elapsed_ms"] = 19000
    assert diagnostics.recovery_delivery_observation(value) is None


@pytest.mark.parametrize("damage", [
    "foreign_state", "state_subclass", "impossible_transition", "state_changed_without_transition",
    "one_poll_mismatched_times", "elapsed_flag_without_cap", "extra_private_field",
    "transition_time_without_transition", "noninteger_transition_time",
])
def test_malformed_recovery_summary_is_rejected(damage):
    observer = diagnostics.RecoveryDeliveryDiagnostics("impaired", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "sending", 0.0)
    observer.start("restored_delivery", 2.0)
    observer.observe("PRIVATE_HANDLE", "sending", 2.0)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    value = copy.deepcopy(observer.failure_observation(error, "impaired", "PRIVATE_HANDLE"))
    restored = value["restored_delivery"]
    if damage == "foreign_state":
        restored["last_state"] = "PRIVATE_STATE"
    elif damage == "state_subclass":
        restored["last_state"] = type("StateSubclass", (str,), {})("sending")
    elif damage == "impossible_transition":
        restored["transitions"] = 2
    elif damage == "state_changed_without_transition":
        restored["last_state"] = "queued"
    elif damage == "one_poll_mismatched_times":
        restored["last_elapsed_ms"] = 1
    elif damage == "elapsed_flag_without_cap":
        restored["elapsed_capped"] = True
    elif damage == "transition_time_without_transition":
        restored["first_transition_elapsed_ms"] = 0
    elif damage == "noninteger_transition_time":
        restored["last_transition_elapsed_ms"] = True
    else:
        restored["private_handle"] = "PRIVATE_HANDLE"
    assert diagnostics.recovery_delivery_observation(value) is None


@pytest.mark.parametrize("damage", ["missing_first", "missing_last", "reverse_order", "after_last_poll"])
def test_malformed_transition_timing_is_rejected(damage):
    observer = diagnostics.RecoveryDeliveryDiagnostics("impaired", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "sending", 0.0)
    observer.start("restored_delivery", 2.0)
    observer.observe("PRIVATE_HANDLE", "sending", 2.0)
    observer.observe("PRIVATE_HANDLE", "queued", 3.0)
    observer.observe("PRIVATE_HANDLE", "sending", 4.0)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    value = copy.deepcopy(observer.failure_observation(error, "impaired", "PRIVATE_HANDLE"))
    restored = value["restored_delivery"]
    if damage == "missing_first":
        restored["first_transition_elapsed_ms"] = None
    elif damage == "missing_last":
        restored["last_transition_elapsed_ms"] = None
    elif damage == "reverse_order":
        restored["first_transition_elapsed_ms"] = 3000
    else:
        restored["last_transition_elapsed_ms"] = 3000
    assert diagnostics.recovery_delivery_observation(value) is None


@pytest.mark.parametrize("time_value", [float("nan"), float("inf"), -1.0])
def test_nonfinite_or_backward_clock_disables_optional_observation(time_value):
    observer = diagnostics.RecoveryDeliveryDiagnostics("impaired", "PRIVATE_HANDLE")
    observer.start("blocked_receipt", 0.0)
    observer.observe("PRIVATE_HANDLE", "sending", 0.0)
    observer.start("restored_delivery", 2.0)
    observer.observe("PRIVATE_HANDLE", "sending", time_value)
    error = controller.PeerFailure("scenario_deadline")
    observer.failed(error)
    assert observer.failure_observation(error, "impaired", "PRIVATE_HANDLE") is None
