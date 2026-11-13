"""Runner probes reveal only availability, never transient credentials or path claims."""

from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_preflight as probe
from native_interop_diagnostics import PreflightDiagnostics


@pytest.fixture
def services(monkeypatch):
    credentials = [{"urls": ["turn:relay.invalid:3478?transport=udp", "turn:relay.invalid:3478?transport=tcp",
                             "turns:relay.invalid:5349?transport=tcp"],
                    "username": "synthetic-secret-username", "credential": "synthetic-secret-password"}]
    health = {"protocol": 2, "writes_enabled": True}
    calls = []
    def fetch(url, timeout):
        calls.append(("production_broker", url, timeout))
        return credentials
    def mailbox(request):
        calls.append(("production_mailbox_health", request.full_url))
        response = BytesIO(json.dumps(health).encode())
        response.status = 200
        return response
    monkeypatch.setattr(probe, "fetch_ice_servers", fetch)
    monkeypatch.setattr(probe, "mailbox_open", mailbox)
    return credentials, health, calls


def test_production_fetch_paths_return_only_redacted_availability(services):
    _, _, calls = services
    result = probe.outbound_services()
    assert result["turn_advertised_transports"] == ["tcp", "tls", "udp"]
    assert result["mailbox_protocol"] == 2 and result["mailbox_writes_enabled"] is True
    assert "synthetic-secret" not in json.dumps(result)
    assert "no allocation or selected path" in result["scope"]
    assert len(calls) == 2 and calls[0][0] == "production_broker" and calls[1][0] == "production_mailbox_health"


@pytest.mark.parametrize("fault", ["no_username", "no_credential", "no_tcp", "no_tls", "plaintext_mailbox", "writes_disabled"])
def test_missing_required_existing_services_fail_instead_of_downgrade_or_skip(services, fault):
    credentials, health, _ = services
    if fault == "no_username": credentials[0].pop("username")
    elif fault == "no_credential": credentials[0].pop("credential")
    elif fault == "no_tcp": credentials[0]["urls"] = [url for url in credentials[0]["urls"] if "transport=tcp" not in url or url.startswith("turns:")]
    elif fault == "no_tls": credentials[0]["urls"] = [url for url in credentials[0]["urls"] if not url.startswith("turns:")]
    elif fault == "plaintext_mailbox": health["protocol"] = 1
    else: health["writes_enabled"] = False
    with pytest.raises(RuntimeError): probe.outbound_services()


def test_wrong_android_runner_cannot_be_a_passing_environment(monkeypatch):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(RuntimeError, match="KVM"):
        probe.android_environment()


def test_preflight_failure_overwrites_stale_success_without_raw_error_details(tmp_path, monkeypatch):
    output = tmp_path / "preflight.json"
    output.write_text(json.dumps({"passed": True}))
    monkeypatch.setattr(probe, "source_identity", lambda expected: (expected, "b" * 40))
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(sys, "argv", ["preflight", "--role", "windows", "--expected-source", "a" * 40, "--output", str(output)])
    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert record["passed"] is False and "skipped" not in record
    assert record["phase"] == "source_environment" and "failure_type" in record


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_android_environment_preserves_exact_checked_probe_failure_and_short_circuit(monkeypatch, failed_index):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(probe, "os", SimpleNamespace(access=lambda *_: True, R_OK=4, W_OK=2))
    expected = [("android_device_state", ["PRIVATE_ADB", "get-state"], "device"),
        ("android_emulator_property", ["PRIVATE_ADB", "shell", "getprop", "ro.kernel.qemu"], "1"),
        ("android_abi", ["PRIVATE_ADB", "shell", "getprop", "ro.product.cpu.abi"], "x86_64")]
    calls = []
    error = probe.subprocess.CalledProcessError(1, "PRIVATE_COMMAND", output="PRIVATE_OUTPUT", stderr="PRIVATE_STDERR")
    def command(args, **kwargs):
        index = len(calls)
        calls.append(args)
        assert args == expected[index][1]
        assert kwargs == {"text": True, "stderr": probe.subprocess.DEVNULL, "timeout": 15}
        if index == failed_index: raise error
        return expected[index][2] + "\n"
    monkeypatch.setattr(probe.subprocess, "check_output", command)
    diagnostics = PreflightDiagnostics()
    with pytest.raises(probe.subprocess.CalledProcessError) as failure:
        probe.android_environment("PRIVATE_ADB", diagnostics=diagnostics)
    assert failure.value is error and diagnostics.failure_site(error) == expected[failed_index][0]
    assert calls == [item[1] for item in expected[:failed_index + 1]]


@pytest.mark.parametrize("responses,count", [(["offline"], 1), (["device", "0"], 2), (["device", "1", "arm64-v8a"], 3)])
def test_android_environment_value_guards_remain_fatal_without_command_failure_attribution(monkeypatch, responses, count):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(probe, "os", SimpleNamespace(access=lambda *_: True, R_OK=4, W_OK=2))
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        return responses[len(calls) - 1]
    monkeypatch.setattr(probe.subprocess, "check_output", command)
    diagnostics = PreflightDiagnostics()
    with pytest.raises(RuntimeError) as failure:
        probe.android_environment(diagnostics=diagnostics)
    assert len(calls) == count and diagnostics.failure_site(failure.value) is None
