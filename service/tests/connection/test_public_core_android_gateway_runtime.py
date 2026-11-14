"""Gateway custody tests; these never boot an emulator or change host rules."""

import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_android_gateway_runtime as gateway  # noqa: E402


class RuleKernel:
    def __init__(self):
        self.rules = {}
        self.packets = {}
        self.calls = []

    def run(self, *argv):
        self.calls.append(argv)
        family, op = argv[:2]
        if family not in ("iptables", "ip6tables"):
            raise AssertionError("unexpected guest command")
        if op == "-S":
            chain = argv[2]
            rows = [f"-A {chain} " + " ".join(rule[2])
                    for rule in self.rules.values() if rule[0] == family and rule[1] == chain]
            return 0, "\n".join([f"-P {chain} ACCEPT", *rows])
        if op == "-nvx":
            chain = argv[argv.index("-L") + 1]
            rows = [f"1 {self.packets.get(rule[3], 0)} 100 DROP all -- * * 0/0 0/0 {rule[3]}"
                    for rule in self.rules.values() if rule[0] == family and rule[1] == chain]
            return 0, "\n".join(rows)
        if op == "-I":
            rule = (family, argv[2], tuple(argv[4:]), argv[argv.index("--comment") + 1])
            self.rules[rule[3]] = rule
            return 0, ""
        if op in ("-C", "-D"):
            rule = (family, argv[2], tuple(argv[3:]), argv[argv.index("--comment") + 1])
            if op == "-C":
                return (0 if self.rules.get(rule[3]) == rule else 1), ""
            if self.rules.get(rule[3]) != rule:
                return 1, ""
            del self.rules[rule[3]]
            return 0, ""
        raise AssertionError("unexpected iptables operation")


def prepared_fault():
    emulator = SimpleNamespace(adb=Path("/sdk/platform-tools/adb"), env={})
    fault = gateway.PublicUidFault(emulator, lambda: {"host": {"packets": 1},
                                                          "guest": {"packets": 1}}, "a" * 40)
    peer = SimpleNamespace(opened=True, admitted=True, owned=True, serial=gateway.SERIAL,
                           identity={"source_commit": "a" * 40},
                           artifacts={gateway.APK_ROLE: "b" * 64})
    fault._apk_sha = lambda: "b" * 64
    fault._process = lambda: {"pid": 123, "uid": 10123, "start": "456"}
    fault.bind(peer)
    kernel = RuleKernel()
    fault._run = kernel.run
    return fault, kernel


def test_fault_covers_both_ip_families_all_protocols_and_preserves_local_control():
    fault, kernel = prepared_fault()
    liveness = []
    fault._control_live = lambda: liveness.append(True)
    fault.block()
    assert len(kernel.rules) == 4
    assert {rule[0] for rule in kernel.rules.values()} == {"iptables", "ip6tables"}
    assert {rule[1] for rule in kernel.rules.values()} == {"INPUT", "OUTPUT"}
    for rule in kernel.rules.values():
        assert "-p" not in rule[2]  # TCP, UDP and any other app IP protocol.
        assert rule[2][:3] == (("!", "-o", "lo") if rule[1] == "OUTPUT" else ("!", "-i", "lo"))
        if rule[1] == "OUTPUT":
            assert ("--uid-owner", "10123") == rule[2][rule[2].index("--uid-owner"):][:2]
    for comment, rule in kernel.rules.items():
        if rule[1] == "OUTPUT":
            kernel.packets[comment] = 3
    assert fault.dropped() == 6
    witness = fault.unblock()
    assert witness == {"app_uid_bound": True, "process_bound": True,
                       "owned_route": True, "profile_restored": True, "dropped_packets": 6}
    assert kernel.rules == {}
    assert len(liveness) >= 3  # after install, while blocked, and before restore.
    assert fault.close() is True


def test_preexisting_rule_or_lost_adb_liveness_cannot_pass():
    fault, kernel = prepared_fault()
    preexisting = next(iter(fault._rules()))
    kernel.rules[preexisting[3]] = preexisting
    with pytest.raises(gateway.PublicGatewayFailure, match="guest_rule_preexisting"):
        fault.block()
    assert kernel.rules == {preexisting[3]: preexisting}
    kernel.rules.clear()
    fault._control_live = lambda: (_ for _ in ()).throw(
        gateway.PublicGatewayFailure("adb_control_liveness_lost"))
    with pytest.raises(gateway.PublicGatewayFailure, match="adb_control_liveness_lost"):
        fault.block()
    assert kernel.rules == {}
    assert fault.close() is True


def test_ambiguous_predecessor_is_rejected_before_install():
    fault, kernel = prepared_fault()
    fault._chains = lambda: {("iptables", "OUTPUT"):
        "-P OUTPUT ACCEPT\n-A OUTPUT -m owner --uid-owner 10123 -j DROP",
        ("iptables", "INPUT"): "-P INPUT ACCEPT"}
    with pytest.raises(gateway.PublicGatewayFailure, match="guest_rule_ambiguous_predecessor"):
        fault.block()
    assert kernel.rules == {}


def test_apk_mismatch_refuses_binding_before_any_rule():
    emulator = SimpleNamespace(adb=Path("/sdk/adb"), env={})
    fault = gateway.PublicUidFault(emulator, lambda: {}, "a" * 40)
    fault._apk_sha = lambda: "c" * 64
    peer = SimpleNamespace(opened=True, admitted=True, owned=True, serial=gateway.SERIAL,
                           identity={"source_commit": "a" * 40},
                           artifacts={gateway.APK_ROLE: "b" * 64})
    with pytest.raises(gateway.PublicGatewayFailure, match="installed_apk_not_source_bound"):
        fault.bind(peer)
    assert fault.rules == []


def test_parent_writes_gateway_witness_only_after_positive_cleanup(tmp_path, monkeypatch):
    output = tmp_path / "role.json"
    temporary = tmp_path / "owned"
    temporary.mkdir()
    class FakeProfile:
        def close(self): pass
    class FakeGateway:
        fail_close = False
        def __init__(self, commands): pass
        def create(self, temporary): pass
        def close(self):
            if self.fail_close:
                raise RuntimeError("cleanup")
    class FakeChild:
        def __init__(self, host, args):
            self.arguments = args
            self.ready = True
            self.result = {"code": 0}
            self.operation_failed = False
            self.impairment = {"kind": "android_emulator_host_gateway_tc_netem"}
            self.emulator_identity = {"pid": 1}
            self.adb_identity = {"pid": 2}
            self.failed_operation = None
            self.profile = FakeProfile()
        def begin(self): pass
        def receive_until_closed(self, deadline):
            report_path = Path(self.arguments[self.arguments.index("--output") + 1])
            replacement = report_path.with_suffix(".tmp")
            replacement.write_text(json.dumps({"passed": True, "role": "android", "gateway": None}))
            os.replace(replacement, report_path)
        def close(self): pass
        def retire_helpers(self, host): pass
    monkeypatch.setattr(gateway, "Gateway", FakeGateway)
    monkeypatch.setattr(gateway, "PublicChild", FakeChild)
    monkeypatch.setattr(gateway, "_source", lambda source: None)
    monkeypatch.setattr(gateway.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    arguments = ["--role", "android", "--expected-source", "a" * 40,
                 "--disposable-emulator-serial", gateway.SERIAL, "--output", str(output)]
    with patch.object(gateway.sys, "platform", "linux"), patch.dict(os.environ,
            {"GITHUB_ACTIONS": "true", "RUNNER_TEMP": str(tmp_path)}):
        assert gateway.run_parent(arguments, output) == 0
    report = json.loads(output.read_text())
    assert report["gateway"]["namespace"] == "owned_linux_network_namespace"
    assert report["gateway"]["cleanup"] == "passed"
    temporary.mkdir()
    FakeGateway.fail_close = True
    with patch.object(gateway.sys, "platform", "linux"), patch.dict(os.environ,
            {"GITHUB_ACTIONS": "true", "RUNNER_TEMP": str(tmp_path)}):
        assert gateway.run_parent(arguments, output) == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert "gateway" not in report or report["gateway"] is None


def test_parent_sigterm_enters_owned_cleanup_and_restores_handler(tmp_path, monkeypatch):
    output = tmp_path / "role.json"
    temporary = tmp_path / "owned"
    temporary.mkdir()
    cleaned = []
    previous = signal.getsignal(signal.SIGTERM)

    class FakeGateway:
        def __init__(self, commands): pass
        def create(self, path): pass
        def close(self): cleaned.append("namespace")

    class FakeChild:
        def __init__(self, host, args):
            self.failed_operation = None
            self.profile = SimpleNamespace(close=lambda: cleaned.append("profile"))
        def begin(self): pass
        def receive_until_closed(self, deadline):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        def close(self): cleaned.append("child")
        def retire_helpers(self, host): cleaned.append("helpers")

    monkeypatch.setattr(gateway, "Gateway", FakeGateway)
    monkeypatch.setattr(gateway, "PublicChild", FakeChild)
    monkeypatch.setattr(gateway, "_source", lambda source: None)
    monkeypatch.setattr(gateway.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    arguments = ["--role", "android", "--expected-source", "a" * 40,
                 "--disposable-emulator-serial", gateway.SERIAL, "--output", str(output)]
    with patch.object(gateway.sys, "platform", "linux"), patch.dict(os.environ,
            {"GITHUB_ACTIONS": "true", "RUNNER_TEMP": str(tmp_path)}):
        assert gateway.run_parent(arguments, output) == 1
    assert signal.getsignal(signal.SIGTERM) is previous
    assert cleaned == ["child", "helpers", "profile", "namespace"]
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert report["host_gateway_failure"]["controller_failed"] is True
