"""Exact installed opt-in private admission selector and report contracts."""

import copy
import json
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import check_windows_private_admission as producer
import check_windows_separate_process_consumer as child_runner


def fixture_bytes():
    return (json.dumps({"v": 1, "passed": True, "scope": producer.FIXTURE_SCOPE,
                        "checks": producer.FIXTURE_CHECKS, "duration_ms": 24},
                       separators=(",", ":")) + "\n").encode()


def test_private_fixture_success_requires_exact_fixed_inventory():
    assert producer.fixture_result(fixture_bytes())["checks"] == producer.FIXTURE_CHECKS
    for raw in (fixture_bytes() + b"extra\n", fixture_bytes().rstrip(b"\n"),
                fixture_bytes().replace(b'"v":1', b'"v":1,"v":1'),
                fixture_bytes().replace(b'"owner_death_retires_host":true',
                                        b'"owner_death_retires_host":false'),
                fixture_bytes().replace(b'"owner_usable":true', b'"owner_usable":1'),
                fixture_bytes().replace(b'"duration_ms":24', b'"duration_ms":150000'),
                b"PRIVATE_TOKEN\n", b"x" * (producer.MAX_STDOUT + 1)):
        with pytest.raises((ValueError, UnicodeError)):
            producer.fixture_result(raw)


def test_private_fixture_failure_projects_fixed_phase_only():
    failure = {"v": 1, "passed": False, "scope": producer.FIXTURE_SCOPE,
               "phase": "owner_death", "duration_ms": 60}
    raw = (json.dumps(failure, separators=(",", ":")) + "\n").encode()
    assert producer.fixture_failure(raw) == "owner_death"
    for value in ({**failure, "phase": "PRIVATE_PATH"}, {**failure, "token": "PRIVATE"},
                  {**failure, "duration_ms": True}, {**failure, "scope": "full R7"}):
        assert producer.fixture_failure((json.dumps(value) + "\n").encode()) is None


def test_shared_runner_has_only_a_fixed_private_selector(tmp_path):
    script = tmp_path / producer.FIXTURE
    script.write_text("import sys\nsys.stdout.buffer.write(b'{}\\n')\n", encoding="utf-8")
    assert child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe",
        tmp_path / "data", time.monotonic() + 5, fixture="private_admission") == b"{}\n"
    with pytest.raises(ValueError, match="fixture_selector"):
        child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe",
            tmp_path / "data", time.monotonic() + 5, fixture="../private-admission-check.mjs")
    failure = {"v": 1, "passed": False, "scope": producer.FIXTURE_SCOPE,
               "phase": "owner_death", "duration_ms": 12}
    script.write_text("import sys\nsys.stdout.buffer.write(" + repr(
        (json.dumps(failure) + "\n").encode()) + ")\nsys.exit(1)\n", encoding="utf-8")
    with pytest.raises(child_runner.FixtureExecutionFailure) as raised:
        child_runner.run_fixture(sys.executable, tmp_path, tmp_path / "host.exe",
            tmp_path / "data", time.monotonic() + 5, fixture="private_admission",
            failure_parser=producer.fixture_failure)
    assert raised.value.failure_detail == "owner_death"


def prepared_run(tmp_path, monkeypatch, *, staged=True, execution=None, protected=True,
                 cleanup_fails=False):
    binary = tmp_path / "sidecar.exe"
    binary.write_bytes(b"host")
    sdk = tmp_path / "sdk.tgz"
    sdk.write_bytes(b"sdk")
    prior = tmp_path / "bootstrap.json"
    prior.write_text("{}", encoding="utf-8")
    binding = {"source_commit": "a" * 40, "source_tree": "b" * 40,
               "sidecar_sha256": producer.digest(binary), "build_input_sha256": "c" * 64,
               "build_manifest_sha256": "d" * 64}
    directory = tmp_path / "outside"
    events = []
    monkeypatch.setattr(producer, "verified_inputs", lambda source, report:
                        (binary, binding, sdk, producer.digest(prior)))
    monkeypatch.setattr(producer, "tools", lambda: ("node", "npm"))
    def outside(_):
        directory.mkdir()
        events.append("outside")
        return directory
    monkeypatch.setattr(producer, "outside_directory", outside)
    def install(location, artifact, node, npm):
        names = ["consumer.mjs", "runtime.mjs", producer.FIXTURE]
        if staged:
            names.append(producer.EVIDENCE)
        monkeypatch.setattr(producer.bootstrap, "FILES", tuple(names))
        for name in names:
            (location / name).write_bytes(name.encode())
        events.append("installed")
        return {"application_files": {name: producer.digest(location / name) for name in names},
                "installed_sdk_entry": "node_modules/@mesh-chat/core-client/dist/index.js",
                "installed_outside_checkout": True, "imports_public_package": True}
    monkeypatch.setattr(producer, "install_typescript", install)
    monkeypatch.setattr(producer, "require_unchanged", lambda *_: events.append("binding"))
    def protection(_):
        events.append("efs")
        if not protected:
            raise ValueError("PRIVATE_VAULT")
        return {"efs_profile_directory": True, "efs_vault_file": True}
    monkeypatch.setattr(producer.bootstrap, "protected_profile", protection)
    def exercise(node, location, runtime, data, deadline, *, fixture, failure_parser):
        assert fixture == "private_admission" and failure_parser is producer.fixture_failure
        events.append("child_retired")
        return execution(runtime) if execution else fixture_bytes()
    monkeypatch.setattr(producer, "run_fixture", exercise)
    def cleanup(location, parent):
        events.append("cleanup")
        if cleanup_fails:
            raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(producer, "cleanup", cleanup)
    return prior, directory, events


def test_private_producer_requires_positive_child_efs_binding_and_cleanup(tmp_path, monkeypatch):
    prior, directory, events = prepared_run(tmp_path, monkeypatch)
    result = producer.run("a" * 40, bootstrap_report=prior, temporary_root=tmp_path)
    assert result["passed"] is True and result["checks"] == producer.CHECKS
    assert events == ["outside", "installed", "binding", "child_retired", "efs", "binding", "cleanup"]
    assert producer.verify_report(result, "a" * 40, "b" * 40) is result


@pytest.mark.parametrize("fault,phase", [
    ("unstaged", "outside_checkout_installation"),
    ("invalid_child", "private_admission_execution"),
    ("unprotected", "protected_profile"),
    ("cleanup", "owned_workspace_cleanup"),
])
def test_private_producer_failures_retain_workspace_and_no_private_output(
        tmp_path, monkeypatch, fault, phase):
    prior, directory, events = prepared_run(tmp_path, monkeypatch,
        staged=fault != "unstaged", protected=fault != "unprotected",
        cleanup_fails=fault == "cleanup",
        execution=(lambda _: b'{"v":1,"passed":false,"scope":"PRIVATE_TOKEN"}\n')
                  if fault == "invalid_child" else None)
    result = producer.run("a" * 40, bootstrap_report=prior, temporary_root=tmp_path)
    assert result["passed"] is False and result["phase"] == phase
    assert result["workspace_retained"] is True and directory.is_dir()
    assert "PRIVATE_" not in json.dumps(result)


@pytest.mark.parametrize("field,value", [
    ("scope", "full R7 acceptance"), ("fixture_duration_ms", True),
    ("checks", {**producer.CHECKS, "extra": True}),
    ("bootstrap_report_sha256", "PRIVATE_HASH"),
    ("application", {"application_files": {},
                     "installed_sdk_entry": "node_modules/@mesh-chat/core-client/x",
                     "installed_outside_checkout": True, "imports_public_package": True}),
])
def test_private_report_refuses_overclaim_and_missing_staged_inputs(tmp_path, monkeypatch, field, value):
    prior, _, _ = prepared_run(tmp_path, monkeypatch)
    report = producer.run("a" * 40, bootstrap_report=prior, temporary_root=tmp_path)
    changed = copy.deepcopy(report)
    changed[field] = value
    with pytest.raises(ValueError):
        producer.verify_report(changed, "a" * 40, "b" * 40)
