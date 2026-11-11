"""Fixed-site native path diagnostics; synthetic inputs are never native CI evidence."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_controller as controller
import native_interop_faults as faults
from check_core_ui_boundary import PYTHON_SELECTION


ROW = " 0: 0F02000A:C350 026433C6:0D96 01 00000000:00000000 00:00000000 00000000 10053 0 1234 2 0\n"
OBSERVATION = {"pair": {"relay_protocol": "tcp", "local": {"type": "relay"}}}
TURN = "turn:turn.example:3478?transport=tcp"


def test_native_path_diagnostic_cases_are_in_the_fast_boundary_gate():
    assert "service/tests/connection/test_ui_core_boundary_interop_path_setup.py" in PYTHON_SELECTION


def kernel_boundary(*, point=None, ambiguous=False):
    events = []
    class Peer:
        APP = "PRIVATE_APP"
        def _adb(self, *args):
            events.append(args)
            if point == "kernel_emulator_identity" and args[-2:] == ("id", "-u"):
                return "2000"
            if point == "kernel_socket_inventory" and args[-2:] == ("cat", "/proc/123/net/tcp"):
                raise RuntimeError("PRIVATE_COMMAND_AND_ENDPOINT")
            if args[-2:] == ("id", "-u"): return "0"
            if args[-2:] == ("getprop", "ro.kernel.qemu"): return "1"
            if args[-2:] == ("pidof", self.APP): return "123 456" if point == "kernel_process_identity" else "123"
            if args[1:3] == ("sh", "-c"): return "socket:[1234]" + (" socket:[5678]" if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp"):
                if point == "kernel_socket_correlation": return "header\n"
                row = ROW.replace("0F02000A:C350", "PRIVATE_INVALID_HEX:C350") if point == "kernel_socket_parse" else ROW
                return "header\n" + row + (ROW.replace("1234", "5678") if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp6"): return "header\n"
            if args[-2:] == ("cat", "/proc/123/status"):
                return "Name: app\n" if point == "kernel_process_uid" else "Uid:\t10053\t10053\t10053\t10053\n"
            if args[1:4] == ("ip", "route", "get"):
                return "PRIVATE_ROUTE_WITHOUT_DEVICE" if point == "kernel_socket_route" else "198.51.100.2 dev wlan0 src 10.0.2.15"
            raise AssertionError("Unexpected private command shape")
    def resolver(*args):
        events.append(("resolver", len(args)))
        if point == "kernel_turn_resolution": raise ValueError("PRIVATE_RESOLVER_OUTPUT")
        return [(None, None, None, None, ("198.51.100.2", 3478))]
    return Peer(), resolver, events


@pytest.mark.parametrize("point,observation,url,stage", [
    ("kernel_relay_evidence", {"pair": {"relay_protocol": "tcp", "local": {"type": "host"}}}, TURN, "kernel_relay_evidence"),
    ("kernel_emulator_identity", OBSERVATION, TURN, "kernel_emulator_identity"),
    ("kernel_turn_url", OBSERVATION, "PRIVATE_INVALID_URL", "kernel_turn_url"),
    ("kernel_turn_resolution", OBSERVATION, TURN, "kernel_turn_resolution"),
    ("kernel_process_identity", OBSERVATION, TURN, "kernel_process_identity"),
    ("kernel_socket_inventory", OBSERVATION, TURN, "kernel_socket_inventory"),
    ("kernel_socket_parse", OBSERVATION, TURN, "kernel_socket_parse"),
    ("kernel_socket_correlation", OBSERVATION, TURN, "kernel_socket_correlation"),
    ("kernel_process_uid", OBSERVATION, TURN, "kernel_process_uid"),
    ("kernel_socket_route", OBSERVATION, TURN, "kernel_socket_route"),
])
def test_actual_kernel_constructor_labels_exact_failing_check_without_values(point, observation, url, stage):
    peer, resolver, _ = kernel_boundary(point=point)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises((ValueError, RuntimeError)) as caught:
        faults.AndroidKernelPath(peer, observation, url, resolver=resolver, path_diagnostics=diagnostic)
    selected = diagnostic.failure_observation(caught.value)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if stage == "kernel_socket_correlation": expected["reason"] = "no_owned_match"
    assert selected == expected
    assert diagnostic.failure_observation(ValueError("PRIVATE_FOREIGN")) == {}
    assert "PRIVATE" not in repr(selected)


def test_exact_own_process_socket_remains_unique_and_reports_ambiguous_reason():
    peer, resolver, _ = kernel_boundary(ambiguous=True)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises(ValueError) as caught:
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver, path_diagnostics=diagnostic)
    assert diagnostic.failure_observation(caught.value) == {"scenario": "turn_tcp",
        "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches"}
    assert "PRIVATE" not in repr(diagnostic.failure_observation(caught.value))


def test_exact_own_process_socket_success_retains_kernel_tuple_and_no_failure_label():
    peer, resolver, events = kernel_boundary()
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver, path_diagnostics=diagnostic)
    assert path.socket == {"local": "10.0.2.15", "local_port": 50000,
        "remote": "198.51.100.2", "remote_port": 3478, "inode": "1234"}
    assert path.protocol == "tcp" and path.uid == "10053" and path.device == "wlan0"
    assert diagnostic.failure_observation(ValueError("PRIVATE_UNRELATED")) == {}
    assert events.count(("resolver", 4)) == 1


@pytest.mark.parametrize("value", [
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "PRIVATE_SOCKET"},
    {"scenario": "turn_tcp", "stage": "kernel_turn_url", "reason": "no_owned_match"},
    {"scenario": "turn_tcp", "stage": "PRIVATE_STAGE"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "address": "PRIVATE_ADDRESS"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "reason": None},
])
def test_native_path_diagnostic_allowlist_rejects_private_or_inapplicable_fields(value):
    assert faults.path_failure_observation(value) == {}


def test_controller_omits_forged_or_malformed_path_observer_projection(monkeypatch):
    instance = controller.Controller("android", SimpleNamespace(), None, None, {})
    instance.phase = "turn_tcp_authenticated_receipts"
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    error = ValueError("PRIVATE_ENDPOINT")
    diagnostic.observe(error, "kernel_socket_correlation", "no_owned_match")
    monkeypatch.setattr(diagnostic, "failure_observation", lambda _: {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches"})
    assert instance.failure_native_path(error) == {}
    monkeypatch.setattr(diagnostic, "failure_observation", lambda _: {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match",
        "endpoint": "PRIVATE_ENDPOINT"})
    assert instance.failure_native_path(error) == {}


def receipt_boundary(monkeypatch, point=None):
    instance = controller.Controller("android", SimpleNamespace(), None, None,
        {"run_id": 123, "run_attempt": 1})
    instance.partner = "windows"
    state = SimpleNamespace(events=[], error=ValueError("PRIVATE_MESSAGE_AND_CREDENTIAL"))
    instance.text = lambda scenario, index=0, *, sender=None, padded=False: "other" if sender else "own"
    def enqueue(text):
        state.events.append(("enqueue", text))
        if point == "receipt_enqueue": raise state.error
        return "PRIVATE_HANDLE"
    def delivered(handle):
        state.events.append(("delivered", handle))
        return True
    def records(text, direction):
        state.events.append(("records", direction))
        if point == "receipt_outbound_records" and direction == "outbound": raise state.error
        if point == "receipt_record_validation" and direction == "outbound": return []
        return [{"id": "PRIVATE_ID", "native_message_id": "PRIVATE_NATIVE_ID"}]
    def wait(action, *, timeout=90, interval=0.25):
        state.events.append(("wait", timeout))
        index = sum(event[0] == "wait" for event in state.events)
        if point == "receipt_delivery_wait" and index == 1: raise state.error
        if point == "receipt_inbound_wait" and index == 2: raise state.error
        return action()
    instance.enqueue, instance.delivered, instance.records, instance.wait = enqueue, delivered, records, wait
    return instance, state


@pytest.mark.parametrize("point", ["receipt_enqueue", "receipt_delivery_wait", "receipt_inbound_wait",
    "receipt_outbound_records", "receipt_record_validation"])
def test_actual_receipt_exchange_reports_only_escaping_fixed_stage(monkeypatch, point):
    instance, state = receipt_boundary(monkeypatch, point)
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    instance.phase = "turn_tcp_authenticated_receipts"
    with pytest.raises(ValueError) as caught:
        instance.exchange("turn_tcp:windows", path_diagnostics=diagnostic)
    if point != "receipt_record_validation": assert caught.value is state.error
    expected = {"native_path_failure": {"scenario": "turn_tcp", "stage": point}}
    assert instance.failure_native_path(caught.value) == expected
    assert instance.failure_native_path(ValueError("PRIVATE_REPLACEMENT")) == {}
    assert "PRIVATE" not in repr(expected)


def test_receipt_exchange_success_preserves_one_enqueue_two_90_second_waits_and_no_label(monkeypatch):
    instance, state = receipt_boundary(monkeypatch)
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    instance.phase = "turn_tcp_authenticated_receipts"
    result, handle = instance.exchange("turn_tcp:windows", path_diagnostics=diagnostic)
    assert result["authenticated_receipt"] is True and handle == "PRIVATE_HANDLE"
    assert state.events.count(("wait", 90)) == 2
    assert [event[0] for event in state.events].count("enqueue") == 1
    assert instance.failure_native_path(ValueError("PRIVATE_LATER")) == {}
    instance.phase = "turn_tcp_kernel_block_negative_control"
    error = ValueError("PRIVATE_LATER")
    diagnostic.observe(error, "receipt_enqueue")
    assert instance.failure_native_path(error) == {}


@pytest.mark.parametrize("matching", [True, False])
def test_actual_controller_main_projects_only_same_escaping_native_path_error(
        tmp_path, monkeypatch, capsys, matching):
    import connection_ci
    peer = SimpleNamespace(process=None)
    instance = controller.Controller("android", peer, None, None, {"source_commit": "a" * 40})
    instance.phase = "turn_tcp_authenticated_receipts"
    diagnostic = instance._path_diagnostics = faults.NativePathDiagnostics("turn_tcp")
    observed = ValueError("PRIVATE_SOCKET_ENDPOINT")
    escaping = observed if matching else ValueError("PRIVATE_REPLACEMENT_EXCEPTION")
    diagnostic.observe(observed, "kernel_socket_correlation", "no_owned_match")
    def execute(): raise escaping
    instance.run = execute
    monkeypatch.setattr(controller, "Controller", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(controller, "source_identity", lambda _: ("a" * 40, "b" * 40))
    monkeypatch.setattr(connection_ci, "current_plan", lambda: {"native_workload": "full"})
    monkeypatch.setattr(controller, "context_from_environment", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(controller, "binding", lambda *_: (None, {}))
    monkeypatch.setattr(controller, "outbound_services", lambda: {})
    monkeypatch.setattr(controller, "android_environment", lambda **_: {})
    monkeypatch.setattr(controller, "AndroidEmulator", lambda: SimpleNamespace(
        start=lambda *args, **kwargs: None, close=lambda: None))
    monkeypatch.setattr(controller, "AndroidPeer", lambda *_: peer)
    monkeypatch.setattr(controller, "GithubArtifacts", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(controller, "Rendezvous", lambda *_: SimpleNamespace(close=lambda: None))
    output = tmp_path / "path_failure.json"
    monkeypatch.setattr(sys, "argv", ["controller", "--role", "android", "--workload", "full",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert controller.main() == 1
    record = json.loads(output.read_text())
    assert record["failure_type"] == "ValueError" and record["phase"] == "turn_tcp_authenticated_receipts"
    assert record.get("native_path_failure") == ({"scenario": "turn_tcp", "stage": "kernel_socket_correlation",
        "reason": "no_owned_match"} if matching else None)
    assert "PRIVATE" not in output.read_text() + capsys.readouterr().out
