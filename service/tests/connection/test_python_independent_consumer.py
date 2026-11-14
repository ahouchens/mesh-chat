"""Fail-closed provenance and host-status checks for the installed Python app."""

import copy
import importlib.util
import io
import json
from pathlib import Path
from queue import Queue
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_python_independent_consumer as check


def application_module():
    path = ROOT / "examples/python-independent-consumer/consumer.py"
    spec = importlib.util.spec_from_file_location("python_independent_application", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(value):
    body = json.dumps(value, separators=(",", ":")).encode()
    return len(body).to_bytes(4, "big") + body


def test_app_owned_status_requires_bounded_strict_frame():
    application = application_module()
    assert application.read_status(io.BytesIO(frame({"v": 1, "type": "runtime_started", "pipe": "pipe"}))) == {
        "v": 1, "type": "runtime_started", "pipe": "pipe"}
    for raw in (b"\0\0\0\1x", (4097).to_bytes(4, "big"), b"\0\0\0\4oops",
                frame({"v": True, "type": "runtime_started"}), b"\0\0\0\2\xff\xff"):
        with pytest.raises((ValueError, UnicodeError)):
            application.read_status(io.BytesIO(raw))


@pytest.mark.parametrize("tail,accepted", [(b"", True), (frame({"v": 1, "type": "runtime_retiring"}), False),
                                            (b"\0\0\0\4oops", False)])
def test_owner_shutdown_requires_exact_status_eof(tail, accepted):
    application = application_module()
    script = ("import json,sys;sys.stdin.buffer.read();"
              "b=json.dumps({'v':1,'type':'runtime_stopped'}).encode();"
              "sys.stdout.buffer.write(len(b).to_bytes(4,'big')+b+bytes.fromhex(sys.argv[1]));"
              "sys.stdout.buffer.flush()")
    process = subprocess.Popen([sys.executable, "-B", "-c", script, tail.hex()],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    runtime = application.Runtime.__new__(application.Runtime)
    runtime.process, runtime.statuses = process, Queue(maxsize=4)
    runtime.reader = Thread(target=runtime._read, daemon=True)
    runtime.reader.start()
    if accepted:
        runtime.stop()
    else:
        with pytest.raises(ValueError):
            runtime.stop()
    assert process.poll() is not None


def test_failure_output_preserves_api_phase_and_separate_retirement(monkeypatch, capsys):
    application = application_module()
    def fail(*_args):
        application.phase = "profile_create"
        application.retirement_outcome = "confirmed"
        raise ValueError("private detail")
    monkeypatch.setattr(application, "check", fail)
    monkeypatch.setattr(sys, "argv", ["consumer.py", "--runtime", "host.exe",
                                      "--data-directory", "data", "--site", "site"])
    assert application.main() == 1
    assert json.loads(capsys.readouterr().out) == {"passed": False, "phase": "profile_create",
                                                  "error_code": "unavailable", "retirement_outcome": "confirmed"}


def test_failed_public_call_keeps_its_phase_after_clean_host_retirement(tmp_path, monkeypatch):
    application = application_module()
    site = tmp_path / "site"
    site.mkdir()
    package = types.ModuleType("mesh_chat_core_client")
    package.__file__ = str(site / "mesh_chat_core_client/__init__.py")
    class CoreClientError(Exception):
        def __init__(self, code):
            self.code = code
    class Client:
        capabilities = {"profiles": ["local"], "operations": ["profile.create"]}
        def application_snapshot(self):
            return {"profile": None, "contacts": [], "messages": []}
        def profile(self, _handle):
            raise CoreClientError("locked")
        def create_profile(self, *_args):
            raise CoreClientError("unavailable")
        def close(self):
            pass
    package.CoreClient = SimpleNamespace(open=lambda *_args: Client())
    package.CoreClientError = CoreClientError
    windows = types.ModuleType("mesh_chat_core_client.windows")
    windows.connect = lambda _pipe: SimpleNamespace(readline=None, write=None, close=None)
    monkeypatch.setitem(sys.modules, "mesh_chat_core_client", package)
    monkeypatch.setitem(sys.modules, "mesh_chat_core_client.windows", windows)
    stopped = []
    class Runtime:
        pipe = "pipe"
        def __init__(self, *_args):
            pass
        def stop(self):
            stopped.append(True)
    monkeypatch.setattr(application, "Runtime", Runtime)
    try:
        with pytest.raises(CoreClientError):
            application.check(tmp_path / "host.exe", tmp_path / "data", site)
    finally:
        sys.path.remove(str(site))
    assert stopped == [True]
    assert application.phase == "profile_create"
    assert application.retirement_outcome == "confirmed"


def report():
    return {"v": 1, "passed": True, "source_commit": "a" * 40, "source_tree": "b" * 40,
            "evidence_level": check.LEVEL, "scope": check.SCOPE,
            "sdk_artifact": check.SDK_ARTIFACT, "runtime_installed_outside_checkout": True,
            "cleanup": "passed", "checks": dict(check.CHECKS),
            "application_files": {name: "c" * 64 for name in check.FILES},
            "duration_seconds": 1.25, "run_id": "d" * 32,
            "sidecar_sha256": "e" * 64, "build_input_sha256": "f" * 64,
            "build_manifest_sha256": "1" * 64, "sdk_sha256": "2" * 64,
            "sdk_staging_report_sha256": "3" * 64,
            "owner_retirement_confirmed": True, "workspace_retained": False}


@pytest.mark.parametrize("change", [
    lambda value: value["checks"].update(reopen_same_public_identity=False),
    lambda value: value["checks"].update(fresh_without_profile=1),
    lambda value: value["checks"].update(clean_host_exits=True),
    lambda value: value.update(scope="SC21"),
    lambda value: value.update(sdk_sha256="0" * 63),
    lambda value: value.update(cleanup="pending"),
    lambda value: value.update(source_commit="c" * 40),
    lambda value: value.update(unexpected_private_data="secret"),
])
def test_report_rejects_scope_provenance_or_cleanup_substitution(change):
    valid = report()
    assert check.verify_report(valid, "a" * 40, "b" * 40) is valid
    invalid = copy.deepcopy(valid)
    change(invalid)
    with pytest.raises(ValueError):
        check.verify_report(invalid, "a" * 40, "b" * 40)


def test_staged_wheel_rejects_wrong_source_and_changed_bytes(tmp_path, monkeypatch):
    directory = tmp_path / "sdk"
    wheel = directory / "python" / check.WHEEL
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"installed-wheel")
    distribution = wheel.parent / "distribution-report.json"
    distribution.write_text("{}")
    item = {"artifact": "python/" + check.WHEEL, "sha256": check.digest(wheel),
            "size_bytes": wheel.stat().st_size, "report_sha256": check.digest(distribution)}
    staging = tmp_path / "staging.json"
    staging.write_text(json.dumps({"v": 1, "passed": True, "source_commit": "a" * 40,
                                   "source_tree": "b" * 40,
                                   "evidence_level": "public_sdk_archive_and_isolated_import_staging",
                                   "artifacts": {"python": item}}))
    import check_python_distribution
    monkeypatch.setattr(check_python_distribution, "verify", lambda path: {"artifact": path.name})
    assert check.staged_wheel(directory, staging, "a" * 40, "b" * 40) == wheel
    with pytest.raises(ValueError):
        check.staged_wheel(directory, staging, "c" * 40, "b" * 40)
    wheel.write_bytes(b"substituted-wheel")
    with pytest.raises(ValueError):
        check.staged_wheel(directory, staging, "a" * 40, "b" * 40)


@pytest.mark.parametrize("scenario", ["pip_timeout", "consumer_timeout", "consumer_nonzero",
                                      "malformed_count", "malformed_boolean", "confirmed"])
def test_checker_retains_uncertain_workspace_and_removes_confirmed_one(tmp_path, monkeypatch, scenario):
    import native_windows_evidence
    binary, wheel, staging = (tmp_path / name for name in ("host.exe", "sdk.whl", "staging.json"))
    binary.write_bytes(b"host")
    wheel.write_bytes(b"wheel")
    staging.write_text("{}")
    binding = {"source_commit": "a" * 40, "source_tree": "b" * 40,
               "sidecar_sha256": check.digest(binary), "build_input_sha256": "f" * 64,
               "build_manifest_sha256": "e" * 64}
    monkeypatch.setattr(native_windows_evidence, "artifact_binding", lambda _source: (binary, binding))
    monkeypatch.setattr(native_windows_evidence, "require_unchanged", lambda *_args: None)
    monkeypatch.setattr(check, "staged_wheel", lambda *_args: wheel)
    monkeypatch.setattr(check, "protected_profile", lambda _data: {
        "efs_profile_directory": True, "efs_vault_file": True})
    work = tmp_path / "mesh-independent-application-test"
    def make_work(_parent):
        work.mkdir()
        return work
    monkeypatch.setattr(check, "outside_directory", make_work)
    calls = []
    def run(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            if scenario == "pip_timeout":
                raise subprocess.TimeoutExpired(command, 1)
            return SimpleNamespace(returncode=0, stdout=b"")
        if scenario == "consumer_timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if scenario == "consumer_nonzero":
            return SimpleNamespace(returncode=1, stdout=json.dumps({"passed": False,
                "phase": "profile_create", "error_code": "unavailable",
                "retirement_outcome": "unconfirmed"}).encode())
        application_checks = {name: value for name, value in check.CHECKS.items()
                              if not name.startswith("efs_")}
        if scenario == "malformed_count":
            application_checks["clean_host_exits"] = True
        elif scenario == "malformed_boolean":
            application_checks["fresh_without_profile"] = 1
        return SimpleNamespace(returncode=0, stdout=json.dumps(application_checks).encode())
    monkeypatch.setattr(check.subprocess, "run", run)
    output = tmp_path / "result.json"
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["check.py", "--expected-source", "a" * 40,
                                      "--sdk-report", str(staging), "--output", str(output)])
    confirmed = scenario == "confirmed"
    assert check.main() == (0 if confirmed else 1)
    result = json.loads(output.read_text())
    assert result["owner_retirement_confirmed"] is confirmed
    assert result["workspace_retained"] is not confirmed
    assert work.exists() is not confirmed
    if not confirmed:
        assert result["retained_workspace"] == work.name
        assert result["failure_type"] == ("TimeoutExpired" if scenario.endswith("timeout") else "ValueError")
        if scenario == "consumer_nonzero":
            assert result["application_phase"] == "profile_create"
            assert result["application_retirement_outcome"] == "unconfirmed"
    else:
        assert result["passed"] is True and result["cleanup"] == "passed"
