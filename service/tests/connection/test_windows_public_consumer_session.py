"""Bounded installed Windows public consumer session adapter controls."""

import io
import json
from pathlib import Path
import queue
import sys
import threading
import time

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import windows_public_consumer_session as session


def test_newline_frame_budget_and_public_reply_shape():
    with pytest.raises(ValueError, match="public_frame_budget"):
        session.frame({"params": {"text": "x" * session.MAX_FRAME}})
    assert session.frame({"id": "win:1"}).endswith(b"\n")
    assert session.reply({"id": "win:1", "ok": True, "result": {}}, "win:1") == {}
    for value in ({"id": "win:2", "ok": True, "result": {}},
                  {"id": "win:1", "ok": True, "result": {}, "extra": True},
                  {"id": "win:1", "ok": False, "error": {"code": "bad-code"}}):
        with pytest.raises(ValueError, match="public_reply"):
            session.reply(value, "win:1")


def test_typed_public_core_error_is_bounded():
    with pytest.raises(session.PublicCoreError) as failure:
        session.reply({"id": "win:1", "ok": False, "error": {"code": "locked"}}, "win:1")
    assert failure.value.code == "locked"


def test_admission_rejects_changed_retained_sdk_before_staging_or_launch(tmp_path, monkeypatch):
    binary = tmp_path / "sidecar.exe"
    binary.write_bytes(b"binary")
    report = tmp_path / "bootstrap.json"
    report.write_text("{}", encoding="utf-8")
    sdk = tmp_path / "sdk.tgz"
    sdk.write_bytes(b"altered")
    binding = {"source_commit": "a" * 40, "source_tree": "b" * 40,
               "sidecar_sha256": "c" * 64, "build_input_sha256": "d" * 64,
               "build_manifest_sha256": "e" * 64}
    prior = {**binding, "sdk_artifact": "sdk.tgz", "sdk_sha256": "0" * 64}
    calls = []
    monkeypatch.setattr(session, "artifact_binding", lambda expected: (binary, binding))
    monkeypatch.setattr(session.bootstrap, "verify_report", lambda value, source, tree: prior)
    monkeypatch.setattr(session, "outside_directory", lambda parent: calls.append("staged"))
    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: calls.append("launched"))
    peer = session.WindowsPublicConsumerSession("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    with pytest.raises(ValueError, match="sdk_binding"):
        peer.open()
    assert calls == [] and peer.process is None and peer.directory is None


def test_admission_rejects_mismatched_runtime_report_before_launch(tmp_path, monkeypatch):
    binary = tmp_path / "sidecar.exe"
    binary.write_bytes(b"binary")
    report = tmp_path / "bootstrap.json"
    report.write_text("{}", encoding="utf-8")
    binding = {"source_commit": "a" * 40, "source_tree": "b" * 40,
               "sidecar_sha256": "c" * 64, "build_input_sha256": "d" * 64,
               "build_manifest_sha256": "e" * 64}
    monkeypatch.setattr(session, "artifact_binding", lambda expected: (binary, binding))
    monkeypatch.setattr(session.bootstrap, "verify_report", lambda value, source, tree:
                        {**binding, "sidecar_sha256": "f" * 64})
    launched = []
    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: launched.append(True))
    peer = session.WindowsPublicConsumerSession("a" * 40, bootstrap_report=report, temporary_root=tmp_path)
    with pytest.raises(ValueError, match="runtime_binding"):
        peer.open()
    assert launched == [] and peer.directory is None


def test_copied_application_byte_change_refuses_launch(tmp_path, monkeypatch):
    binary = tmp_path / "mesh-chat-service-x86_64-pc-windows-msvc.exe"
    binary.write_bytes(b"binary")
    sdk = tmp_path / "sdk.tgz"
    sdk.write_bytes(b"sdk")
    workspace = tmp_path / "outside"
    workspace.mkdir()
    (workspace / "consumer.mjs").write_bytes(b"wrong")
    binding = {"sidecar_sha256": "x"}
    monkeypatch.setattr(session, "verified_inputs", lambda expected, report: (binary, binding, sdk, "r"))
    monkeypatch.setattr(session, "tools", lambda: ("node", "npm"))
    monkeypatch.setattr(session, "outside_directory", lambda parent: workspace)
    monkeypatch.setattr(session, "install_typescript", lambda directory, source, node, npm:
                        {"application_files": {"consumer.mjs": "expected"}})
    monkeypatch.setattr(session.shutil, "copy2", lambda source, target: Path(target).write_bytes(b"binary"))
    monkeypatch.setattr(session, "digest", lambda path:
                        "actual" if Path(path).name == "consumer.mjs" else "s" if Path(path).name == "sdk.tgz" else "x")
    launched = []
    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: launched.append(True))
    peer = session.WindowsPublicConsumerSession("a" * 40, temporary_root=tmp_path)
    with pytest.raises(ValueError, match="installed_inputs_changed"):
        peer.open()
    assert launched == [] and peer.process is None and workspace.is_dir()


def test_partial_startup_thread_failure_kills_process_and_retains_workspace(tmp_path, monkeypatch):
    binary = tmp_path / "mesh-chat-service-x86_64-pc-windows-msvc.exe"
    binary.write_bytes(b"binary")
    sdk = tmp_path / "sdk.tgz"
    sdk.write_bytes(b"sdk")
    workspace = tmp_path / "outside"
    workspace.mkdir()
    events = []

    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        def poll(self): return None
        def kill(self): events.append("kill")
        def wait(self, timeout): events.append("wait"); return -9

    binding = {"sidecar_sha256": "x"}
    monkeypatch.setattr(session, "verified_inputs", lambda expected, report: (binary, binding, sdk, "r"))
    monkeypatch.setattr(session, "tools", lambda: ("node", "npm"))
    monkeypatch.setattr(session, "outside_directory", lambda parent: workspace)
    monkeypatch.setattr(session, "install_typescript", lambda directory, source, node, npm:
                        {"application_files": {}})
    monkeypatch.setattr(session.shutil, "copy2", lambda source, target: Path(target).write_bytes(b"binary"))
    monkeypatch.setattr(session, "digest", lambda path: "x" if Path(path).name != "sdk.tgz" else "s")
    monkeypatch.setattr(session, "require_unchanged", lambda binary, binding: None)
    monkeypatch.setattr(session.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(session.threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("thread_start")))
    peer = session.WindowsPublicConsumerSession("a" * 40, temporary_root=tmp_path)
    with pytest.raises(RuntimeError, match="thread_start"):
        peer.open()
    assert events == ["kill", "wait"] and workspace.is_dir()
    assert peer.retired is False and peer.workspace_cleaned is False


def ready_peer(tmp_path):
    peer = session.WindowsPublicConsumerSession("a" * 40, temporary_root=tmp_path)
    peer.deadline = time.monotonic() + 5
    peer.directory = tmp_path / "owned"
    peer.directory.mkdir()
    peer.runtime = peer.directory / "sidecar.exe"
    peer.sdk = peer.directory / "sdk.tgz"
    peer.bootstrap_report = peer.directory / "bootstrap.json"
    for path in (peer.runtime, peer.sdk, peer.bootstrap_report): path.write_bytes(b"same")
    peer.binding = {"sidecar_sha256": "same"}
    peer.sdk_hash = peer.report_hash = "same"
    peer.installed = {"application_files": {}}
    return peer


def test_request_frames_are_numbered_and_typed_errors_keep_session(tmp_path):
    peer = ready_peer(tmp_path)
    peer.process = type("Process", (), {"stdin": io.BytesIO()})()
    peer.responses.put(session.frame({"id": "win:1", "ok": False, "error": {"code": "locked"}}))
    with pytest.raises(session.PublicCoreError) as failure:
        peer.request("profile.query", {"profile": "p"})
    assert failure.value.code == "locked" and peer.faulted is False
    peer.responses.put(session.frame({"id": "win:2", "ok": True, "result": {"profiles": ["p"]}}))
    assert peer.request("runtime.capabilities") == {"profiles": ["p"]}
    written = peer.process.stdin.getvalue().splitlines()
    assert [json.loads(line)["id"] for line in written] == ["win:1", "win:2"]
    with pytest.raises(ValueError, match="public_request"):
        peer.request("native.command")


def test_overall_deadline_rejects_write_before_sending(tmp_path):
    peer = ready_peer(tmp_path)
    peer.process = type("Process", (), {"stdin": io.BytesIO()})()
    peer.deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="public_session_deadline"):
        peer.request("runtime.capabilities")
    assert peer.process.stdin.getvalue() == b"" and peer.faulted is True


def test_duplicate_reply_fields_fault_session(tmp_path):
    peer = ready_peer(tmp_path)
    peer.process = type("Process", (), {"stdin": io.BytesIO()})()
    peer.responses.put(b'{"id":"win:1","id":"win:1","ok":true,"result":{}}\n')
    with pytest.raises(ValueError, match="public_reply"):
        peer.request("runtime.capabilities")
    assert peer.faulted is True


def test_stdout_overflow_is_rejected_without_retaining_payload(tmp_path):
    peer = ready_peer(tmp_path)
    peer.process = type("Process", (), {"stdout": io.BytesIO(b"x" * (session.MAX_FRAME + 1) + b"\n")})()
    peer._read_stdout()
    assert peer.output_failure.is_set()
    assert peer.responses.get_nowait() is None


@pytest.mark.parametrize("exit_code", [0, 1])
def test_finish_requires_positive_exit_and_preserves_failed_workspace(tmp_path, monkeypatch, exit_code):
    peer = ready_peer(tmp_path)
    class Process:
        stdin = io.BytesIO()
        def wait(self, timeout): return exit_code
        def poll(self): return exit_code
    class Reader:
        def join(self, timeout): pass
        def is_alive(self): return False
    peer.process = Process()
    peer.stdout_reader = peer.stderr_reader = Reader()
    peer.responses.put(None)
    monkeypatch.setattr(session, "digest", lambda path: "same")
    monkeypatch.setattr(session, "require_unchanged", lambda binary, binding: None)
    if exit_code == 0:
        assert peer.close() is True and peer.retired is True
    else:
        with pytest.raises(RuntimeError, match="consumer_exit"):
            peer.finish()
        assert peer.retired is False and peer.directory.is_dir() and peer.workspace_cleaned is False


def test_faulted_request_cannot_claim_retirement(tmp_path):
    peer = ready_peer(tmp_path)
    events = []
    class Process:
        stdin = io.BytesIO()
        def poll(self): return None
        def kill(self): events.append("kill")
        def wait(self, timeout): events.append("wait"); return -9
    peer.process = Process()
    peer.faulted = True
    with pytest.raises(RuntimeError, match="public_session_faulted"):
        peer.finish()
    assert events == ["kill", "wait"] and peer.retired is False and peer.directory.is_dir()


def test_post_exit_app_change_prevents_retirement_claim(tmp_path, monkeypatch):
    peer = ready_peer(tmp_path)
    app = peer.directory / "consumer.mjs"
    app.write_bytes(b"altered")
    peer.installed = {"application_files": {"consumer.mjs": "expected"}}
    class Process:
        stdin = io.BytesIO()
        def wait(self, timeout): return 0
        def poll(self): return 0
    class Reader:
        def join(self, timeout): pass
        def is_alive(self): return False
    peer.process = Process()
    peer.stdout_reader = peer.stderr_reader = Reader()
    monkeypatch.setattr(session, "digest", lambda path: "altered" if Path(path).name == "consumer.mjs" else "same")
    monkeypatch.setattr(session, "require_unchanged", lambda binary, binding: None)
    with pytest.raises(ValueError, match="installed_inputs_changed"):
        peer.finish()
    assert peer.retired is False and peer.directory.is_dir()


def test_smoke_profile_requires_stable_public_handle():
    calls = []
    class Peer:
        def request(self, operation, params=None, key=None):
            calls.append((operation, params, key))
            if operation == "runtime.capabilities": return {"profiles": ["p"], "operations": ["profile.create"]}
            if operation == "application.snapshot": return {"profile": None if len(calls) == 2 else
                {"display_name": "Independent Windows"}, "contacts": [], "messages": []}
            if operation == "profile.query": return {"destination": "public-destination"}
            return {"created": True}
    assert session.smoke_profile(Peer()) == "p"
    assert [item[0] for item in calls] == ["runtime.capabilities", "application.snapshot",
                                        "profile.create", "runtime.capabilities", "profile.query",
                                        "application.snapshot"]
    assert len(calls[2][2]) >= 16
