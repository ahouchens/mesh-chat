"""Admission tests for the exact-artifact Windows candidate pair fixture."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).resolve().parents[3] / "tests/core-sdk-upgrade"
sys.path.insert(0, str(FIXTURE))
import windows_candidate_pair as candidate


def staged_manifest(tmp_path):
    source, tree = "a" * 40, "b" * 40
    files = {}
    for name, filename in candidate.ARTIFACT_NAMES.items():
        parent = "runtime" if name == "runtime_build" else name
        path = tmp_path / parent / filename
        path.parent.mkdir(exist_ok=True)
        if name not in {"sdk_staging", "old_staging"}:
            path.write_bytes((name + " exact fixture bytes").encode())
        files[name] = path
    def sha(name):
        return hashlib.sha256(files[name].read_bytes()).hexdigest()
    files["sdk_staging"].write_text(json.dumps({
        "passed": True, "source_commit": source, "source_tree": tree,
        "evidence_level": "public_sdk_archive_and_isolated_import_staging",
        "artifacts": {"python": {"sha256": sha("python")},
                      "typescript": {"sha256": sha("typescript")}},
    }))
    files["old_staging"].write_text(json.dumps({
        "baseline_source": candidate.BASELINE["baseline_source"],
        "baseline_tree": candidate.BASELINE["baseline_tree"],
        "provenance": candidate.BASELINE["provenance"],
        "artifacts": {"typescript": {"sha256": sha("old_typescript")},
                      "python_service_carrier": {"sha256": sha("old_service")}},
    }))
    manifest = {
        "v": 1, "source_commit": source, "source_tree": tree,
        "baseline_source": candidate.BASELINE["baseline_source"],
        "baseline_tree": candidate.BASELINE["baseline_tree"],
        "versions": dict(candidate.VERSION_FIELDS),
        "platform": {"os": "Windows", "architecture": "AMD64"},
        "permissions": {"app_owned_normal_host": True, "dpapi_key": True, "efs_profile": True},
        "baseline_native_binary": None,
        "artifacts": {name: {"path": path.relative_to(tmp_path).as_posix(),
                              "sha256": sha(name), "size_bytes": path.stat().st_size}
                      for name, path in files.items()},
    }
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    return path, manifest, source, tree


def test_exact_candidate_and_baseline_artifact_manifest_is_admitted(tmp_path):
    path, value, source, tree = staged_manifest(tmp_path)
    accepted, files = candidate.validate_manifest(path, source, tree)
    assert accepted == value and set(files) == set(candidate.ARTIFACT_NAMES)
    assert all(file.is_file() for file in files.values())


@pytest.mark.parametrize("change", [
    lambda value: value.update(source_tree="wrong"),
    lambda value: value["versions"].update(public_api_minor=0),
    lambda value: value["versions"].update(public_api_major=True),
    lambda value: value["permissions"].update(efs_profile=False),
    lambda value: value["permissions"].update(dpapi_key=1),
    lambda value: value.update(baseline_native_binary="unverified-old.exe"),
    lambda value: value["artifacts"]["runtime"].update(sha256="0" * 64),
    lambda value: value["artifacts"]["old_typescript"].update(path="../old.tgz"),
])
def test_wrong_source_version_permission_native_upgrade_or_bytes_cannot_enter_pair(tmp_path, change):
    path, value, source, tree = staged_manifest(tmp_path)
    change(value)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        candidate.validate_manifest(path, source, tree)


def test_rebuilt_old_artifact_change_is_rejected_even_with_new_manifest_hash(tmp_path):
    path, value, source, tree = staged_manifest(tmp_path)
    old = tmp_path / value["artifacts"]["old_service"]["path"]
    old.write_bytes(b"changed baseline bytes")
    value["artifacts"]["old_service"].update(
        sha256=hashlib.sha256(old.read_bytes()).hexdigest(), size_bytes=old.stat().st_size)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Pinned component"):
        candidate.validate_manifest(path, source, tree)


def test_candidate_scripts_parse_as_node_modules_without_source_aliases():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to parse the embedded consumer scripts")
    for name, source in (("driver.mjs", candidate.DRIVER), ("old_client.mjs", candidate.OLD_TYPESCRIPT)):
        result = subprocess.run([node, "--input-type=module", "--check"], input=source,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, name + ": " + result.stderr
        assert "service/src" not in source and "sdk/typescript/src" not in source


@pytest.mark.parametrize("snapshot_destination,accepted", [("a" * 32, True), ("b" * 32, False)])
def test_old_client_checks_public_snapshot_destination_hash(tmp_path, snapshot_destination, accepted):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to run the embedded old client")
    major = int(subprocess.check_output([node, "--version"], text=True).strip().split(".")[0][1:])
    if major < 22:
        pytest.skip("The TypeScript package requires Node 22 or newer")
    package = tmp_path / "node_modules/@mesh-chat/core-client"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "name": "@mesh-chat/core-client", "type": "module", "exports": "./index.mjs"}))
    (package / "index.mjs").write_text('''export class CoreClient {
  static async open(transport) {
    return {capabilities:{api_major:1,api_minor:1,profiles:['profile']},
      async request(operation) {
        if (operation==='profile.query') return {destination:process.env.TEST_DESTINATION};
        if (operation==='application.snapshot')
          return {profile:{destination_hash:process.env.TEST_SNAPSHOT_DESTINATION}};
        throw new Error('unexpected_operation');
      }, close(){transport.close();}};
  }
}''')
    (tmp_path / "old_client.mjs").write_text(candidate.OLD_TYPESCRIPT)
    (tmp_path / "runner.mjs").write_text(r'''import {createServer} from 'node:net';
import {spawn} from 'node:child_process';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
const directory=process.argv[2];
const pipe=process.platform==='win32' ? `\\\\.\\pipe\\mesh-candidate-test-${randomUUID()}`
                                    : join(directory,'candidate.sock');
const server=createServer(socket=>socket.on('error',()=>{}));
await new Promise((yes,no)=>{server.once('error',no);server.listen(pipe,yes);});
const child=spawn(process.execPath,['old_client.mjs',pipe],
  {cwd:directory,env:{...process.env,TEST_DESTINATION:'a'.repeat(32),
    TEST_SNAPSHOT_DESTINATION:process.argv[3]},stdio:['pipe','pipe','ignore']});
let output='';child.stdout.on('data',part=>output+=part);
child.stdin.end('a'.repeat(32)+'\n');
const exit=await new Promise((yes,no)=>{child.once('close',yes);child.once('error',no);});
await new Promise(yes=>server.close(yes));
process.stdout.write(JSON.stringify({exit,output})+'\n');''')
    completed = subprocess.run([node, str(tmp_path / "runner.mjs"), str(tmp_path), snapshot_destination],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    assert (observed["exit"] == 0) is accepted
    if accepted:
        assert json.loads(observed["output"]) == {"passed": True}


def test_client_images_match_actual_normal_host_pipe_policy(monkeypatch):
    monkeypatch.syspath_prepend(str(FIXTURE.parents[1] / "service/src"))
    from mesh_chat.core_api.pipe_policy import allowed_images, image_allowed
    runtime = (FIXTURE.parents[1] / "examples/typescript-independent-consumer/runtime.mjs").read_text()
    assert "MESH_CHAT_CORE_API_CLIENT_IMAGE: process.execPath" in runtime
    assert "onOwned(runtime)" in runtime
    assert "child(process.execPath,['old_client.mjs'" in candidate.DRIVER
    assert "sys.executable" not in candidate.DRIVER and "python_client" not in candidate.DRIVER
    node = r"C:\Program Files\nodejs\node.exe"
    python = r"C:\Python313\python.exe"
    images = allowed_images((node,))
    assert image_allowed(node, images)
    assert not image_allowed(python, images)


def test_driver_timeout_kills_exact_driver_and_retains_workspace_gate(monkeypatch, tmp_path):
    calls = []
    class Driver:
        returncode = -9
        def communicate(self, *, timeout):
            calls.append(("communicate", timeout))
            if timeout == 180:
                raise subprocess.TimeoutExpired("node", timeout)
            return b"", None
        def kill(self):
            calls.append(("kill",))
    monkeypatch.setattr(candidate.subprocess, "Popen", lambda *a, **k: Driver())
    with pytest.raises(subprocess.TimeoutExpired):
        candidate._run_driver(["node", "driver.mjs"], cwd=tmp_path, env={})
    assert calls == [("communicate", 180), ("kill",), ("communicate", 15)]
    work = tmp_path / "mesh-windows-candidate-pair-retained"
    work.mkdir()
    (work / "profile.lock").write_text("owned")
    with pytest.raises(RuntimeError, match="retirement is unconfirmed"):
        candidate._remove_retired_workspace(work, tmp_path, owner_retired=False)
    assert (work / "profile.lock").exists()
    candidate._remove_retired_workspace(work, tmp_path, owner_retired=True)
    assert not work.exists()


@pytest.mark.parametrize("code,exit_count,passed", [
    (1, 2, True), (0, 1, True), (0, True, True), (0, 2, False),
])
def test_uncertain_host_exit_cannot_authorize_workspace_removal(code, exit_count, passed):
    checks = {name: True for name in candidate.CHECKS
              if name not in {"efs_profile_directory", "efs_vault_file", "clean_host_exits"}}
    checks["clean_host_exits"] = exit_count
    payload = json.dumps({"passed": passed, "checks": checks}).encode()
    with pytest.raises(ValueError, match="did not complete"):
        candidate._confirmed_driver_result(code, payload)
    checks["clean_host_exits"] = 2
    assert candidate._confirmed_driver_result(0,
        json.dumps({"passed": True, "checks": checks}).encode())["checks"] == checks


def test_failed_owner_report_keeps_workspace_path_and_no_success(tmp_path, monkeypatch):
    work = tmp_path / "mesh-windows-candidate-pair-retained"
    work.mkdir()
    cause = subprocess.TimeoutExpired("node", 180)
    monkeypatch.setattr(candidate, "execute", lambda *a: (_ for _ in ()).throw(
        candidate.RetainedWorkspaceError(cause, work, False)))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["candidate", "--manifest", "candidate.json",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert candidate.main() == 1
    report = json.loads(output.read_text())
    assert report == {"v": 1, "passed": False, "evidence_level": candidate.LEVEL,
        "failure_type": "TimeoutExpired", "owner_retirement_confirmed": False,
        "workspace_remaining": True, "retained_workspace": str(work)}


def test_failure_report_projects_only_fixed_driver_stage_and_phase(tmp_path, monkeypatch):
    work = tmp_path / "mesh-windows-candidate-pair-retained"
    work.mkdir()
    monkeypatch.setattr(candidate, "execute", lambda *a: (_ for _ in ()).throw(
        candidate.RetainedWorkspaceError(ValueError("private detail"), work, False,
                                         "driver_result", "installed_old_client")))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["candidate", "--manifest", "candidate.json",
        "--expected-source", "a" * 40, "--output", str(output)])
    assert candidate.main() == 1
    report = json.loads(output.read_text())
    assert report["failure_stage"] == "driver_result"
    assert report["driver_phase"] == "installed_old_client"
    assert "private detail" not in output.read_text()


def test_driver_failure_phase_drops_untrusted_or_unbounded_labels():
    assert candidate._driver_failure_phase(
        b'{"passed":false,"phase":"installed_old_client","message":"private"}') == "installed_old_client"
    for output in (b'{"passed":false,"phase":"private"}', b'{"passed":true,"phase":"reopen"}',
                   b'{"passed":false,"phase":[]}', b'not json'):
        assert candidate._driver_failure_phase(output) is None
