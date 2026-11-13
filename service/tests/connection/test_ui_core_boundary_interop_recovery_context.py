"""Terminal recovery diagnostics cannot change delivery or cleanup decisions."""

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_recovery_context as context
from test_ui_core_boundary_interop_recovery_observation import blocked_controller


PAIRING = "11111111-1111-4111-8111-111111111111"
BEFORE = {"logical_session": "PRIVATE_LOGICAL", "resource": "PRIVATE_PHYSICAL",
    "service_incarnation": "a" * 32, "profile_incarnation": "b" * 32}


def inventory():
    return {"service_incarnation": "a" * 32, "profile_incarnation": "b" * 32,
        "resources": [{"logical_session": "PRIVATE_LOGICAL", "physical_resource": "PRIVATE_PHYSICAL",
            "adopted": True, "owner_state": "authorized"}],
        "carrier_observation": {"availability": "selected", "owner_loss": None,
            "suspect_precursor": None, "native_close": "not_observed", "order": "not_observed"}}


def recovery(monkeypatch, *, role="android", states=("sending", "queued"), sample=None):
    instance, clock, calls = blocked_controller(monkeypatch, list(states), role=role)
    def sleep(seconds): clock.now = round(clock.now + seconds, 6)
    controller.time.sleep = sleep
    instance.pairing = PAIRING
    instance._begin_recovery_context(BEFORE, "impaired")
    reads = []
    def read(**kwargs):
        reads.append((clock.now, kwargs))
        if isinstance(sample, Exception): raise sample
        return inventory() if sample is None else sample
    instance.peer.inventory = read
    def delay(seconds): clock.now += seconds
    def publish(*_): delay(3)
    def receive(*_):
        delay(4)
        return {"approved": True}
    instance.publish, instance.receive = publish, receive
    fault = None
    if role == "android":
        def unblock():
            delay(2)
            return 7
        fault = SimpleNamespace(block=lambda: delay(1), unblock=unblock,
            protocol="udp", target_kind="app_uid_udp", target_material="PRIVATE_TARGET", rule_count=2)
    return instance, clock, calls, reads, fault


@pytest.mark.parametrize("role", ["android", "windows"])
def test_timeout_reads_exact_carrier_once_after_original_window(monkeypatch, role):
    instance, clock, calls, reads, fault = recovery(monkeypatch, role=role)
    with pytest.raises(controller.PeerFailure, match="scenario_deadline") as caught:
        instance.negative(fault, "impaired")
    assert len(reads) == 1 and reads[0][0] == clock.now
    assert clock.now == pytest.approx(102 if role == "android" else 99)
    assert reads[0][1]["carrier_observation"]["expected_physical"] == BEFORE["resource"]
    value = instance.failure_recovery_context(caught.value)["recovery_context"]
    assert value["carrier_read"] == "observed"
    assert value["carrier"]["matching_resources"] == 1
    assert value["carrier"]["owner_state"] == "authorized"
    if role == "android":
        assert value["kernel_block_window"] == {"fully_installed_ms": 9000,
            "operation_window_ms": 12000, "fully_installed_capped": False,
            "operation_window_capped": False, "dropped_packets": 7, "packets_capped": False}
    else:
        assert value["kernel_block_window"] is None
    assert "PRIVATE" not in json.dumps(value)
    assert sum(name == "message.enqueue" for name, _ in calls) == 1
    assert instance.failure_recovery_context(controller.PeerFailure("scenario_deadline")) == {}
    instance.pairing = "22222222-2222-4222-8222-222222222222"
    assert instance.failure_recovery_context(caught.value) == {}


def test_delivered_recovery_has_no_extra_read(monkeypatch):
    instance, _, _, reads, fault = recovery(monkeypatch, states=("delivered",))
    result, _ = instance.negative(fault, "impaired")
    assert result["delivered_after_restore"] and reads == []


@pytest.mark.parametrize("sample", [RuntimeError("PRIVATE_ERROR"), {}, {"resources": "PRIVATE"}])
def test_bad_or_failed_terminal_read_preserves_primary_timeout(monkeypatch, sample):
    instance, _, _, reads, fault = recovery(monkeypatch, sample=sample)
    with pytest.raises(controller.PeerFailure, match="scenario_deadline") as caught:
        instance.negative(fault, "impaired")
    value = instance.failure_recovery_context(caught.value)["recovery_context"]
    assert len(reads) == 1 and value["carrier_read"] == "unavailable" and value["carrier"] is None
    assert value["kernel_block_window"]["dropped_packets"] == 7


@pytest.mark.parametrize("global_deadline", [30, 221])
def test_terminal_read_is_skipped_when_global_budget_is_insufficient(monkeypatch, global_deadline):
    instance, clock, _, reads, fault = recovery(monkeypatch)
    instance.deadline = global_deadline
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(fault, "impaired")
    assert clock.now == pytest.approx(min(102, global_deadline)) and reads == []
    value = instance.failure_recovery_context(caught.value)["recovery_context"]
    assert value["carrier_read"] == "skipped_deadline" and value["carrier"] is None


def test_missing_exact_resource_retains_selected_owner_loss_without_identifiers(monkeypatch):
    sample = inventory()
    sample["resources"] = []
    sample["carrier_observation"].update(owner_loss={"phase": "inspect", "event": "tick",
        "reason": "carrier_lost", "prior_health": "suspect"}, native_close="local_request", order="owner_first")
    instance, _, _, reads, fault = recovery(monkeypatch, sample=sample)
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(fault, "impaired")
    value = instance.failure_recovery_context(caught.value)["recovery_context"]["carrier"]
    assert len(reads) == 1 and value["matching_resources"] == 0
    assert value["expected_physical"] is None and value["owner_state"] == "unknown"
    assert value["carrier_observation"]["availability"] == "selected"
    assert value["carrier_observation"]["owner_loss"]["reason"] == "carrier_lost"
    assert "PRIVATE" not in json.dumps(value)


def test_foreign_incarnation_cannot_claim_selected_loss(monkeypatch):
    sample = inventory()
    sample["service_incarnation"] = "c" * 32
    sample["carrier_observation"].update(owner_loss={"phase": "inspect", "event": "tick",
        "reason": "carrier_lost", "prior_health": "suspect"}, order="unknown")
    instance, _, _, _, fault = recovery(monkeypatch, sample=sample)
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(fault, "impaired")
    value = instance.failure_recovery_context(caught.value)["recovery_context"]["carrier"]
    assert not value["same_service"]
    assert value["carrier_observation"]["availability"] == "unavailable"


def test_projection_rejects_raw_fields_and_invalid_block_bounds(monkeypatch):
    instance, _, _, _, fault = recovery(monkeypatch)
    with pytest.raises(controller.PeerFailure) as caught:
        instance.negative(fault, "impaired")
    value = instance.failure_recovery_context(caught.value)["recovery_context"]
    raw = copy.deepcopy(value)
    raw["private"] = "PRIVATE"
    assert context.recovery_context_snapshot(raw) is None
    value["kernel_block_window"]["fully_installed_ms"] = 12001
    assert context.recovery_context_snapshot(value) is None


@pytest.mark.parametrize("fault", ["foreign_pairing", "blocked_receipt", "observer_failure"])
def test_unrelated_or_unattributable_failure_never_reads_inventory(monkeypatch, fault):
    instance, _, _, reads, kernel = recovery(monkeypatch)
    if fault == "foreign_pairing":
        instance.pairing = "22222222-2222-4222-8222-222222222222"
    elif fault == "blocked_receipt":
        instance.delivered = lambda _: True
    else:
        monkeypatch.setattr(controller.RecoveryDeliveryDiagnostics, "observe",
            lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    with pytest.raises((controller.PeerFailure, ValueError)) as caught:
        instance.negative(kernel, "impaired")
    assert reads == [] and instance.failure_recovery_context(caught.value) == {}


def test_block_clock_caps_and_invalid_clock_cannot_escape():
    window = context.KernelBlockWindow()
    for stage, now, packets in [("block_call", 0, None), ("block_return", 1, None),
            ("unblock_call", 1000, None), ("unblock_return", 1001, context.PACKET_CAP + 1)]:
        window = context.mark_window(window, stage, lambda: now, packets)
    value = window.snapshot()
    assert value["fully_installed_ms"] == value["operation_window_ms"] == context.TIME_CAP_MS
    assert value["fully_installed_capped"] and value["operation_window_capped"] and value["packets_capped"]
    bad = context.KernelBlockWindow()
    bad = context.mark_window(bad, "block_call", lambda: 2)
    assert context.mark_window(bad, "block_return", lambda: 1) is None
    assert context.mark_window(context.KernelBlockWindow(), "block_call", lambda: float("nan")) is None


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_main_retains_terminal_snapshot_and_original_error_through_cleanup(tmp_path, monkeypatch, cleanup_failed):
    import connection_ci
    instance, _, _, reads, kernel = recovery(monkeypatch)
    events = []
    original_read = instance.peer.inventory
    def read(**kwargs):
        events.append("inventory")
        return original_read(**kwargs)
    instance.peer.inventory = read
    instance.peer.process = SimpleNamespace()
    def stop(**_):
        events.append("peer_stop")
        if cleanup_failed: raise RuntimeError("PRIVATE_CLEANUP")
    instance.peer.stop = stop
    def run():
        try: instance.negative(kernel, "impaired")
        finally: events.append("fault_cleanup")
    instance.run = run
    emulator = SimpleNamespace(start=lambda *args, **kwargs: None,
        close=lambda: events.append("emulator_close"))
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: emulator)
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: instance.peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "recovery.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    value = json.loads(output.read_text())
    assert value["passed"] is False and value["error_code"] == "scenario_deadline"
    assert value["recovery_context"]["carrier_read"] == "observed" and len(reads) == 1
    assert value.get("cleanup_failed", False) is cleanup_failed
    assert events == ["inventory", "fault_cleanup", "peer_stop", "emulator_close"]
    assert "PRIVATE" not in json.dumps(value)
