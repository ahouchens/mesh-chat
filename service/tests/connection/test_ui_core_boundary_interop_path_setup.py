"""Fixed-site native path diagnostics; synthetic inputs are never native CI evidence."""

from pathlib import Path
import ipaddress
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


def kernel_boundary(*, point=None, ambiguous=False, tcp_rows=None, fd_links=None, dns_addresses=None):
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
            if args[1:3] == ("sh", "-c"):
                return fd_links if fd_links is not None else "socket:[1234]" + (" socket:[5678]" if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp"):
                if point == "kernel_socket_correlation": return "header\n"
                if tcp_rows is not None: return "header\n" + tcp_rows
                row = ROW.replace("0F02000A:C350", "PRIVATE_INVALID_HEX:C350") if point == "kernel_socket_parse" else ROW
                return "header\n" + row + (ROW.replace("1234", "5678") if ambiguous else "")
            if args[-2:] == ("cat", "/proc/123/net/tcp6"): return "header\n"
            if args[-2:] == ("cat", "/proc/123/status"):
                return "Name: app\n" if point == "kernel_process_uid" else "Uid:\t10053\t10053\t10053\t10053\n"
            if args[1:5] == ("pm", "list", "packages", "-U"):
                return "package:OTHER uid:10053\n" if point == "kernel_scope_exclusivity" else "package:PRIVATE_APP uid:10053\n"
            if args[1:5] == ("ps", "-A", "-o", "UID,PID"):
                return "UID PID\n10053 123\n" + ("10053 456\n" if point == "extra_uid_process" else "")
            if args[1:4] == ("ip", "route", "get"):
                return "PRIVATE_ROUTE_WITHOUT_DEVICE" if point == "kernel_socket_route" else "198.51.100.2 dev wlan0 src 10.0.2.15"
            raise AssertionError("Unexpected private command shape")
    def resolver(*args):
        events.append(("resolver", len(args)))
        if point == "kernel_turn_resolution": raise ValueError("PRIVATE_RESOLVER_OUTPUT")
        return [(None, None, None, None, (address, args[1]))
                for address in (dns_addresses or ("198.51.100.2",))]
    return Peer(), resolver, events


@pytest.mark.parametrize("point,observation,url,stage", [
    ("kernel_relay_evidence", {"pair": {"relay_protocol": "tcp", "local": {"type": "host"}}}, TURN, "kernel_relay_evidence"),
    ("kernel_emulator_identity", OBSERVATION, TURN, "kernel_emulator_identity"),
    ("kernel_turn_url", OBSERVATION, "PRIVATE_INVALID_URL", "kernel_turn_resolution"),
    ("kernel_turn_resolution", OBSERVATION, TURN, "kernel_turn_resolution"),
    ("kernel_process_identity", OBSERVATION, TURN, "kernel_process_identity"),
    ("kernel_socket_inventory", OBSERVATION, TURN, "kernel_socket_inventory"),
    ("kernel_socket_parse", OBSERVATION, TURN, "kernel_socket_parse"),
    ("kernel_socket_correlation", OBSERVATION, TURN, "kernel_socket_correlation"),
    ("kernel_process_uid", OBSERVATION, TURN, "kernel_process_uid"),
    ("kernel_scope_exclusivity", OBSERVATION, TURN, "kernel_scope_exclusivity"),
])
def test_actual_kernel_constructor_labels_exact_failing_check_without_values(point, observation, url, stage):
    peer, resolver, _ = kernel_boundary(point=point)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises((ValueError, RuntimeError)) as caught:
        faults.AndroidKernelPath(peer, observation, url, resolver=resolver, path_diagnostics=diagnostic,
                                resource_check=lambda: True)
    selected = diagnostic.failure_observation(caught.value)
    expected = {"scenario": "turn_tcp", "stage": stage}
    if stage == "kernel_socket_correlation": expected["reason"] = "no_owned_match"
    assert selected == expected
    assert diagnostic.failure_observation(ValueError("PRIVATE_FOREIGN")) == {}
    assert "PRIVATE" not in repr(selected)


def test_multiple_owned_tcp_sockets_are_one_covered_turn_endpoint_scope():
    peer, resolver, _ = kernel_boundary(ambiguous=True)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert path.endpoint_mode and len(path.matches) == 2 and path.socket is None
    assert path.target_kind == "uid_tcp_turn_destination_set" and path.rule_count == 1


@pytest.mark.parametrize("states,inodes,summary,relation", [
    (("01", "08"), ("1234", "5678"), "one_established_plus_other", "distinct"),
    (("01", "01"), ("1234", "5678"), "multiple_established", "distinct"),
    (("08", "02"), ("1234", "5678"), "no_established", "distinct"),
    (("01", "PRIVATE"), ("1234", "5678"), "unclassifiable", "distinct"),
    (("01", "01"), ("1234", "1234"), "multiple_established", "same"),
])
def test_tcp_endpoint_aggregate_requires_at_least_one_established_owned_match(states, inodes, summary, relation):
    rows = "".join(ROW.replace(" 01 ", f" {state} ").replace("1234", inode)
                   for state, inode in zip(states, inodes))
    peer, resolver, _ = kernel_boundary(tcp_rows=rows, fd_links=" ".join(f"socket:[{inode}]" for inode in inodes))
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    if summary == "no_established":
        with pytest.raises(ValueError) as caught:
            faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                path_diagnostics=diagnostic, resource_check=lambda: True)
        assert diagnostic.failure_observation(caught.value) == {
            "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match"}
    else:
        path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
        assert path.matches and diagnostic.failure_observation(ValueError("PRIVATE_FOREIGN")) == {}


def test_actual_owned_socket_ambiguity_keeps_unrelated_scenario_report_unchanged():
    rows = "header\n" + ROW + ROW.replace("1234", "5678")
    diagnostic = faults.NativePathDiagnostics("turn_udp")
    with pytest.raises(ValueError) as caught:
        faults.owned_socket(rows, {"1234", "5678"}, {"198.51.100.2"}, 3478,
                            path_diagnostics=diagnostic)
    assert diagnostic.failure_observation(caught.value) == {
        "scenario": "turn_udp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches"}


def test_actual_owned_socket_observer_fault_does_not_change_ambiguous_rejection(monkeypatch):
    rows = "header\n" + ROW + ROW.replace("1234", "5678")
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    def broken_observer(*_args, **_kwargs): raise RuntimeError("PRIVATE_OBSERVER")
    monkeypatch.setattr(diagnostic, "observe", broken_observer)
    with pytest.raises(ValueError, match="Selected TURN path lacks one unambiguous own-process kernel socket"):
        faults.owned_socket(rows, {"1234", "5678"}, {"198.51.100.2"}, 3478,
                            path_diagnostics=diagnostic)


def test_tls_multiple_rows_admit_the_established_covered_endpoint():
    rows = ROW + ROW.replace(" 01 ", " 08 ").replace("1234", "5678")
    peer, resolver, _ = kernel_boundary(tcp_rows=rows, fd_links="socket:[1234] socket:[5678]")
    diagnostic = faults.NativePathDiagnostics("turn_tls")
    instance = controller.Controller("android", SimpleNamespace(), None, None, {})
    instance.phase = "turn_tls_authenticated_receipts"
    instance._path_diagnostics = diagnostic
    observation = {"pair": {"relay_protocol": "tls", "local": {"type": "relay"}}}
    path = faults.AndroidKernelPath(peer, observation, "turns:turn.example:3478", resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert len(path.matches) == 1 and instance.failure_native_path(ValueError("PRIVATE_FOREIGN")) == {}


@pytest.mark.parametrize("value", [
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "no_owned_match",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "distinct"},
    {"scenario": "turn_udp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "receipt_enqueue", "tcp_state_summary": "multiple_established",
     "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "PRIVATE_STATE", "owned_inode_relation": "distinct"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established"},
    {"scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "ambiguous_owned_matches",
     "tcp_state_summary": "multiple_established", "owned_inode_relation": "PRIVATE_INODE"},
])
def test_tcp_socket_ambiguity_summary_allowlist_rejects_unrelated_or_private_fields(value):
    assert faults.path_failure_observation(value) == {}


def test_one_established_turn_endpoint_retains_only_private_aggregate_and_no_failure_label():
    peer, resolver, events = kernel_boundary()
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
                                    path_diagnostics=diagnostic, resource_check=lambda: True)
    assert path.matches == frozenset({("1234", "10.0.2.15", 50000, "198.51.100.2", 3478)})
    assert path.protocol == "tcp" and path.uid == "10053" and path.socket is None
    assert diagnostic.failure_observation(ValueError("PRIVATE_UNRELATED")) == {}
    assert events.count(("resolver", 4)) == 1


def test_host_dns_candidate_set_must_cover_observed_guest_owned_turn_endpoint():
    peer, resolver, _ = kernel_boundary(dns_addresses=("203.0.113.7",))
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises(ValueError, match="outside the scoped TURN") as caught:
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
    assert diagnostic.failure_observation(caught.value) == {
        "scenario": "turn_tcp", "stage": "kernel_socket_correlation", "reason": "uncovered_endpoint"}


def test_external_owned_tcp_on_different_port_is_not_silently_ignored():
    row = ROW.replace("026433C6:0D96", "097100CB:01BB")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW + row)
    diagnostic = faults.NativePathDiagnostics("turn_tcp")
    with pytest.raises(ValueError, match="outside the scoped TURN") as caught:
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            path_diagnostics=diagnostic, resource_check=lambda: True)
    assert diagnostic.failure_observation(caught.value)["reason"] == "uncovered_endpoint"


def test_exact_known_mailbox_endpoint_and_guest_loopback_do_not_widen_turn_rule():
    mailbox = ROW.replace("026433C6:0D96", "026433C6:01BB").replace("1234", "5678")
    loopback = ROW.replace("026433C6:0D96", "0100007F:4E20").replace("1234", "9012")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW + mailbox + loopback,
        fd_links="socket:[1234] socket:[5678] socket:[9012]")
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True, control_urls=("https://mail.example",))
    assert len(path.matches) == 1 and path.addresses == ("198.51.100.2",)
    assert path.control_endpoints == frozenset({("198.51.100.2", 443)})


@pytest.mark.parametrize("url,dns", [
    ("turn:turn.example:0?transport=tcp", ("198.51.100.2",)),
    ("turn:turn.example:3478?transport=udp", ("198.51.100.2",)),
    (TURN, ("fe80::1%eth0",)),
    (TURN, ("0.0.0.0",)),
])
def test_turn_endpoint_admission_rejects_invalid_port_protocol_or_address(url, dns):
    peer, resolver, _ = kernel_boundary(dns_addresses=dns)
    with pytest.raises(ValueError):
        faults.AndroidKernelPath(peer, OBSERVATION, url, resolver=resolver,
            resource_check=lambda: True)


def test_multiple_a_aaaa_answers_and_two_owned_sockets_are_one_endpoint_scope():
    address = ipaddress.ip_address("2001:db8::2")
    encoded = b"".join(address.packed[index:index + 4][::-1] for index in range(0, 16, 4)).hex().upper()
    row6 = ROW.replace("026433C6", encoded).replace("1234", "5678")
    peer, resolver, _ = kernel_boundary(tcp_rows=ROW, fd_links="socket:[1234] socket:[5678]",
        dns_addresses=("198.51.100.2", "2001:db8::2", "198.51.100.2"))
    original = peer._adb
    def adb(*args):
        if args[-2:] == ("cat", "/proc/123/net/tcp6"): return "header\n" + row6
        return original(*args)
    peer._adb = adb
    path = faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
        resource_check=lambda: True)
    assert path.addresses == ("198.51.100.2", "2001:db8::2")
    assert len(path.matches) == 2 and path.rule_count == 2


def test_tls_mailbox_overlap_and_extra_same_uid_process_reject_scope():
    peer, resolver, _ = kernel_boundary()
    observation = {"pair": {"relay_protocol": "tls", "local": {"type": "relay"}}}
    with pytest.raises(ValueError, match="overlap"):
        faults.AndroidKernelPath(peer, observation, "turns:turn.example:443", resolver=resolver,
            resource_check=lambda: True, control_urls=("https://mail.example",))
    peer, resolver, _ = kernel_boundary(point="extra_uid_process")
    with pytest.raises(ValueError, match="process-exclusive"):
        faults.AndroidKernelPath(peer, OBSERVATION, TURN, resolver=resolver,
            resource_check=lambda: True)


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
