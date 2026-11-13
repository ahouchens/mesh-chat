"""Baseline receipt failures retain bounded evidence from existing polls only."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
from native_interop_exchange_observation import ReceiptExchangeObservation, receipt_exchange_snapshot
from native_interop_faults import NativePathDiagnostics


def exchange_controller(monkeypatch, states, inbound):
    clock = SimpleNamespace(now=0.0)
    def sleep(seconds):
        clock.now += seconds
    monkeypatch.setattr(controller, "time", SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep))
    calls = []
    instance = controller.Controller("windows", None, None, None,
        {"run_id": "PRIVATE_RUN", "run_attempt": 1})
    instance.profile = "PRIVATE_PROFILE"
    instance.contact = {"core_handle": "PRIVATE_CONTACT"}
    instance.pairing = "PRIVATE_OPERATION"
    instance.phase = "impaired_authenticated_receipts"
    instance._path_diagnostics = NativePathDiagnostics("impaired")
    own = instance.text("impaired:windows", 7, padded=True)
    other = instance.text("impaired:windows", 7, sender="android", padded=True)
    query_count = 0
    def core(operation, params=None, key=None):
        nonlocal query_count
        calls.append(operation)
        if operation == "message.enqueue":
            return {"accepted": True, "message": "PRIVATE_HANDLE"}
        if operation == "message.query":
            state = states[min(query_count, len(states) - 1)]
            query_count += 1
            return {"state": state}
        assert operation == "application.snapshot"
        return {"messages": [
            {"kind": "chat", "direction": "outbound", "text": own,
             "id": "PRIVATE_OUTBOUND", "native_message_id": "PRIVATE_NATIVE"},
            *([{"kind": "chat", "direction": "inbound", "text": other,
                "id": "PRIVATE_INBOUND"}] if inbound else [])]}
    instance.core = core
    return instance, clock, calls


def exchange(instance):
    return instance.exchange("impaired:windows", 7, padded=True,
                             path_diagnostics=instance._path_diagnostics)


@pytest.mark.parametrize("state", ["sending", "queued", "received_by_endpoint"])
def test_delivery_timeout_retains_index_and_existing_message_states(monkeypatch, state):
    instance, clock, calls = exchange_controller(monkeypatch, ["queued", state], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    assert caught.value.code == "scenario_deadline"
    assert clock.now == 90
    value = instance.failure_exchange(caught.value)["receipt_exchange"]
    assert (value["scenario"], value["initiator"], value["index"], value["stage"]) == (
        "impaired", "windows", 7, "receipt_delivery_wait")
    assert value["delivery"]["first_state"] == "queued"
    assert value["delivery"]["last_state"] == state
    assert value["delivery"]["polls"] == calls.count("message.query") == 360
    assert value["records"] is None  # No snapshot has been requested in this wait.
    assert set(calls) == {"message.enqueue", "message.query"}
    assert "PRIVATE" not in json.dumps(value)


def test_inbound_timeout_retains_delivered_state_and_both_record_counts(monkeypatch):
    instance, clock, calls = exchange_controller(monkeypatch, ["delivered"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    value = instance.failure_exchange(caught.value)["receipt_exchange"]
    assert value["stage"] == "receipt_inbound_wait"
    assert value["delivery"]["last_state"] == "delivered"
    assert value["records"] == {"polls": 360, "polls_capped": False,
        "inbound": 0, "inbound_capped": False, "outbound": 1,
        "outbound_capped": False, "outbound_native_id_present": True}
    assert calls.count("application.snapshot") == 360
    assert clock.now == 90
    assert "PRIVATE" not in json.dumps(value)


def test_success_keeps_result_and_clears_optional_evidence(monkeypatch):
    instance, clock, calls = exchange_controller(monkeypatch, ["sending", "delivered"], True)
    result, handle = exchange(instance)
    assert result["authenticated_receipt"] and handle == "PRIVATE_HANDLE"
    assert clock.now == .25
    assert calls == ["message.enqueue", "message.query", "message.query",
                     "application.snapshot", "application.snapshot"]
    assert instance._exchange_observation is None
    assert instance.failure_exchange(controller.PeerFailure("scenario_deadline")) == {}


@pytest.mark.parametrize("damage", ["error", "phase", "pairing", "observer", "path_stage"])
def test_failure_is_bound_to_exact_exchange_and_escaping_error(monkeypatch, damage):
    instance, _, _ = exchange_controller(monkeypatch, ["sending"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    error = caught.value
    if damage == "error": error = controller.PeerFailure("scenario_deadline")
    elif damage == "phase": instance.phase = "impaired_kernel_block_negative_control"
    elif damage == "pairing": instance.pairing = "OTHER_OPERATION"
    elif damage == "observer": instance._exchange_observation = None
    else: instance._path_diagnostics = NativePathDiagnostics("impaired")
    assert instance.failure_exchange(error) == {}


def test_unknown_state_cannot_leak_or_change_original_failure(monkeypatch):
    instance, clock, calls = exchange_controller(monkeypatch, ["PRIVATE_UNKNOWN"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    assert caught.value.code == "scenario_deadline" and clock.now == 90
    assert instance.failure_exchange(caught.value) == {}


def test_new_exchange_cannot_reuse_old_failure(monkeypatch):
    instance, _, _ = exchange_controller(monkeypatch, ["sending"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    instance.enqueue = lambda _: (_ for _ in ()).throw(ValueError("new enqueue failure"))
    with pytest.raises(ValueError):
        exchange(instance)
    assert instance.failure_exchange(caught.value) == {}


@pytest.mark.parametrize("method", ["delivery", "records", "failed", "failure"])
def test_broken_optional_observer_cannot_change_timeout(monkeypatch, method):
    instance, clock, _ = exchange_controller(monkeypatch, ["delivered"], False)
    def broken(*_):
        raise RuntimeError("PRIVATE_OBSERVER_FAILURE")
    monkeypatch.setattr(ReceiptExchangeObservation, method, broken)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    assert caught.value.code == "scenario_deadline" and clock.now == 90
    assert instance.failure_exchange(caught.value) == {}


def test_counts_cap_and_duplicate_records_never_report_a_unique_native_identity():
    observer = ReceiptExchangeObservation("impaired:android", 19, "PRIVATE_OP",
        "impaired_authenticated_receipts", "PRIVATE_HANDLE", "PRIVATE_OWN", "PRIVATE_OTHER")
    rows = [{"kind": "chat", "direction": "outbound", "text": "PRIVATE_OWN",
             "native_message_id": "PRIVATE_ID"}] * 3
    for index in range(600):
        observer.delivery("PRIVATE_HANDLE", "queued" if index % 2 else "sending")
        observer.records(rows)
    error = ValueError("PRIVATE_FAILURE")
    observer.failed(error)
    value = observer.failure(error, observer.phase, observer.pairing,
        {"scenario": "impaired", "stage": "receipt_record_validation"})
    assert value["delivery"]["polls"] == value["delivery"]["transitions"] == 512
    assert value["delivery"]["polls_capped"] and value["delivery"]["transitions_capped"]
    assert value["records"]["polls"] == 512 and value["records"]["polls_capped"]
    assert value["records"]["outbound"] == 2 and value["records"]["outbound_capped"]
    assert value["records"]["outbound_native_id_present"] is None
    assert "PRIVATE" not in json.dumps(value)


@pytest.mark.parametrize("damage", ["unknown_state", "raw_field", "boolean_index",
    "unknown_initiator", "index_overflow", "poll_overflow", "cap_without_count", "impossible_transition"])
def test_malformed_projection_is_not_emitted(monkeypatch, damage):
    instance, _, _ = exchange_controller(monkeypatch, ["sending"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    value = instance.failure_exchange(caught.value)["receipt_exchange"]
    if damage == "unknown_state": value["delivery"]["first_state"] = "PRIVATE_STATE"
    elif damage == "raw_field": value["raw"] = "PRIVATE_RAW"
    elif damage == "boolean_index": value["index"] = True
    elif damage == "unknown_initiator": value["initiator"] = "PRIVATE_PEER"
    elif damage == "index_overflow": value["index"] = 20
    elif damage == "poll_overflow": value["delivery"]["polls"] = 513
    elif damage == "cap_without_count": value["delivery"]["polls_capped"] = True
    else: value["delivery"]["transitions"] = value["delivery"]["polls"]
    assert receipt_exchange_snapshot(value) is None


def test_global_deadline_remains_shorter_than_exchange_wait(monkeypatch):
    instance, clock, calls = exchange_controller(monkeypatch, ["sending"], False)
    instance.deadline = .5
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    assert clock.now == .5 and calls.count("message.query") == 2
    assert instance.failure_exchange(caught.value)["receipt_exchange"]["delivery"]["polls"] == 2


@pytest.mark.parametrize("matching", [True, False])
def test_main_serializes_only_exact_failure_and_runs_peer_cleanup(tmp_path, monkeypatch, capsys, matching):
    import connection_ci
    instance, _, _ = exchange_controller(monkeypatch, ["sending"], False)
    with pytest.raises(controller.PeerFailure) as caught:
        exchange(instance)
    error = caught.value if matching else controller.PeerFailure("scenario_deadline")
    def execute():
        raise error
    instance.run = execute
    cleaned = []
    peer = SimpleNamespace(process=object(), stop=lambda **_: cleaned.append("peer"))
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(
        start=lambda *args, **kwargs: None, close=lambda: cleaned.append("emulator")))
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "receipt_failure.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    record = json.loads(output.read_text())
    assert record["error_code"] == "scenario_deadline"
    assert ("receipt_exchange" in record) is matching
    assert cleaned == ["peer", "emulator"]
    assert "PRIVATE" not in output.read_text() + capsys.readouterr().out
