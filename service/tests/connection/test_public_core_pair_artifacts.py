"""Same-run transport and the real separate Node upload admission."""

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
import urllib.error
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_pair_artifacts as artifacts
import public_core_pair_rendezvous as pair


FIELDS = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
          "run_attempt": 1, "source_commit": "a" * 40}
CONTEXT = {**FIELDS, "pair_id": pair.pair_id_for(FIELDS)}


def environment(role):
    return {"GITHUB_REPOSITORY": "example/mesh", "GITHUB_REPOSITORY_ID": "123",
            "GITHUB_RUN_ID": "456", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
            "GITHUB_JOB": pair.JOBS[role], "GITHUB_TOKEN": "synthetic-test-token",
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"}


def archived(value, role, phase):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr("bundle.json", pair.canonical(value))
    data = stream.getvalue()
    metadata = {"id": 17, "name": pair.artifact_name(CONTEXT, role, phase), "expired": False,
                "size_in_bytes": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "workflow_run": {"id": 456, "head_sha": "a" * 40, "repository_id": 123}}
    return metadata, data


@pytest.mark.parametrize("field,bad", [
    ("GITHUB_JOB", "native_windows_peer"), ("GITHUB_RUN_ID", "999"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_SHA", "b" * 40),
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_ACTIONS", "false"),
])
def test_transport_refuses_other_job_or_run(tmp_path, field, bad):
    env = environment("windows")
    env[field] = bad
    with pytest.raises(artifacts.PublicPairUnavailable):
        artifacts.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=env)


def test_transport_accepts_only_one_rehashed_partner_bundle(tmp_path, monkeypatch):
    sender = pair.Rendezvous(CONTEXT, "windows")
    transport = artifacts.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"))
    try:
        metadata, blob = archived(sender.public_manifest(), "windows", "key")
        calls = []
        def request(path, *, archive=False, deadline):
            calls.append((path, archive))
            return blob if archive else {"total_count": 1, "artifacts": [metadata]}
        monkeypatch.setattr(transport, "_request", request)
        assert transport.wait("windows", "key", transport.clock() + 5) == sender.public_manifest()
        assert len(calls) == 2 and calls[1][1]
    finally:
        sender.close()
        transport.close()


@pytest.mark.parametrize("fault", ["duplicate", "wrong_digest", "wrong_job", "wrong_run", "oversized_inventory"])
def test_ambiguous_or_wrong_partner_artifact_fails_closed(tmp_path, monkeypatch, fault):
    sender = pair.Rendezvous(CONTEXT, "windows")
    transport = artifacts.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"))
    try:
        value = sender.public_manifest()
        if fault == "wrong_job": value["producer_job"] = "native_windows_peer"
        metadata, blob = archived(value, "windows", "key")
        if fault == "wrong_digest": metadata["digest"] = "sha256:" + "0" * 64
        if fault == "wrong_run": metadata["workflow_run"]["id"] = 999
        inventory = {"total_count": 1, "artifacts": [metadata]}
        if fault == "duplicate": inventory = {"total_count": 2, "artifacts": [metadata, metadata]}
        if fault == "oversized_inventory": inventory["total_count"] = 101
        monkeypatch.setattr(transport, "_request", lambda path, archive=False, deadline=None:
                            blob if archive else inventory)
        with pytest.raises((ValueError, artifacts.PublicPairUnavailable)):
            transport.wait("windows", "key", transport.clock() + 5)
    finally:
        sender.close()
        transport.close()


def test_signed_blob_redirect_never_receives_repository_token(tmp_path):
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _limit): return b"archive"
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            if len(seen) == 1:
                raise urllib.error.HTTPError(request.full_url, 302, "redirect",
                                             {"Location": "https://signed.example/blob"}, None)
            return Response()
    transport = artifacts.GithubArtifacts(CONTEXT, "android", tmp_path,
                                         environment=environment("android"), opener=Opener())
    try:
        assert transport._request("/repos/example/mesh/actions/artifacts/17/zip",
                                  archive=True, deadline=transport.clock() + 5) == b"archive"
        assert seen[0].get_header("Authorization") == "Bearer synthetic-test-token"
        assert seen[1].get_header("Authorization") is None
    finally:
        transport.close()


def test_short_archive_404_retry_requires_same_artifact_identity(tmp_path, monkeypatch):
    sender = pair.Rendezvous(CONTEXT, "windows")
    now = [0.0]
    transport = artifacts.GithubArtifacts(CONTEXT, "android", tmp_path,
        environment=environment("android"), clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    try:
        metadata, blob = archived(sender.public_manifest(), "windows", "key")
        attempts = [0]
        def request(path, *, archive=False, deadline):
            if not archive:
                return {"total_count": 1, "artifacts": [metadata]}
            attempts[0] += 1
            if attempts[0] == 1:
                raise artifacts.PublicPairUnavailable("blob pending", status=404)
            return blob
        monkeypatch.setattr(transport, "_request", request)
        assert transport.wait("windows", "key", 10) == sender.public_manifest()
        assert attempts == [2] and now == [3.0]
    finally:
        sender.close()
        transport.close()


def test_upload_uses_remaining_deadline_and_rejects_late_completion(tmp_path, monkeypatch):
    sender = pair.Rendezvous(CONTEXT, "windows")
    now = [0.0]
    transport = artifacts.GithubArtifacts(CONTEXT, "windows", tmp_path,
        environment=environment("windows"), clock=lambda: now[0])
    calls = []
    def run(*args, **options):
        calls.append(options["timeout"])
        assert options["stdout"] == subprocess.DEVNULL and options["stderr"] == subprocess.DEVNULL
        Path(args[0][-1]).write_text('{"passed":true,"id":17,"size":123}\n')
        now[0] = 1.1
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(artifacts.subprocess, "run", run)
    try:
        with pytest.raises(artifacts.PublicPairUnavailable):
            transport.publish("key", sender.public_manifest(), 0.0)
        assert calls == []
        with pytest.raises(artifacts.PublicPairUnavailable):
            transport.publish("key", sender.public_manifest(), 1.0)
        assert calls == [1.0]
    finally:
        sender.close()
        transport.close()


def test_trickling_body_cannot_outlive_phase_deadline(tmp_path):
    release = threading.Event()
    class SlowResponse:
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
        def read(self, _limit):
            release.wait(5)
            return b"late"
        def close(self): release.set()
    class Opener:
        def open(self, request, timeout): return SlowResponse()
    transport = artifacts.GithubArtifacts(CONTEXT, "android", tmp_path,
                                         environment=environment("android"), opener=Opener())
    try:
        import time
        started = time.monotonic()
        with pytest.raises(artifacts.PublicPairUnavailable):
            transport._request("/repos/example/mesh/actions/runs/456/artifacts?per_page=100",
                               deadline=started + 0.05)
        assert time.monotonic() - started < 1 and release.wait(1)
    finally:
        transport.close()


def test_public_exchange_exposes_only_flow_setup_interface(tmp_path):
    android = pair.Rendezvous(CONTEXT, "android")
    class Transport:
        def __init__(self): self.bundles = {}
        def publish(self, phase, value, deadline):
            assert deadline > 0
            self.bundles[phase] = value
            if phase == "key": android.bind_partner(value)
        def wait(self, role, phase, deadline):
            assert role == "android"
            return android.public_manifest() if phase == "key" else self.bundles[phase]
        def close(self): pass
    transport = Transport()
    exchange = artifacts.PublicPairExchange(CONTEXT, "windows", tmp_path, transport=transport)
    try:
        import time
        deadline = time.monotonic() + 10
        exchange.connect(deadline)
        exchange.publish("offer_code", {"pairing_code": "MESHPAIR2.synthetic"}, deadline)
        assert android.open("offer_code", transport.bundles["offer_code"]) == {"pairing_code": "MESHPAIR2.synthetic"}
        transport.bundles["invitation_accepted"] = android.seal("invitation_accepted", {})
        assert exchange.receive("invitation_accepted", deadline) == {}
    finally:
        exchange.close()
        android.close()


@pytest.mark.parametrize("role,phase", [("windows", "key"), ("android", "key"),
    ("windows", "offer_code"), ("android", "invitation_accepted"),
    ("windows", "approved"), ("windows", "ready"), ("android", "ready"),
    ("windows", "done"), ("android", "done")])
def test_real_node_helper_admits_every_public_phase_with_fake_sdk(tmp_path, role, phase):
    node = os.environ.get("MESH_NODE") or shutil.which("node")
    assert node
    original = Path(__file__).resolve().parents[3] / "scripts/native-interop-artifact/public-pair-upload.mjs"
    script = tmp_path / "public-pair-upload.mjs"
    script.write_bytes(original.read_bytes())
    package = tmp_path / "node_modules/@actions/artifact"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"type": "module", "exports": "./index.mjs"}))
    (package / "index.mjs").write_text('''
import { readFile, writeFile } from "node:fs/promises";
export class DefaultArtifactClient {
  async uploadArtifact(name, files, root, options) {
    const body = JSON.parse(await readFile(files[0], "utf8"));
    await writeFile(process.env.MESH_UPLOAD_OBSERVATION, JSON.stringify({name, files, root, options, body}));
    return {id: 17, size: 123};
  }
}
''')
    sender = pair.Rendezvous(CONTEXT, role)
    receiver = pair.Rendezvous(CONTEXT, pair.partner(role))
    sender.bind_partner(receiver.public_manifest())
    try:
        payload = {"pairing_code": "MESHPAIR2.synthetic-code"} if phase == "offer_code" else {}
        value = sender.public_manifest() if phase == "key" else sender.seal(phase, payload)
        bundle = tmp_path / "bundle.json"
        bundle.write_bytes(pair.canonical(value))
        identity = tmp_path / "identity.json"
        env = {**os.environ, **environment(role), "ACTIONS_RUNTIME_TOKEN": "synthetic-runtime-token",
               "MESH_UPLOAD_OBSERVATION": str(tmp_path / "observed.json")}
        result = subprocess.run([node, str(script), pair.artifact_name(CONTEXT, role, phase),
                                 str(bundle), str(identity)],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and result.stderr == ""
        assert result.stdout == ""
        assert json.loads(identity.read_text()) == {"passed": True, "id": 17, "size": 123}
        observed = json.loads((tmp_path / "observed.json").read_text())
        assert observed["body"] == value
        assert observed["options"] == {"retentionDays": 1, "compressionLevel": 0}
        assert "synthetic-code" not in json.dumps(observed)
    finally:
        sender.close()
        receiver.close()


@pytest.mark.parametrize("fault", ["native_job", "wrong_source", "extra_plaintext", "unknown_phase", "wrong_pair"])
def test_real_node_helper_rejects_native_or_plaintext_admission(tmp_path, fault):
    node = os.environ.get("MESH_NODE") or shutil.which("node")
    assert node
    original = Path(__file__).resolve().parents[3] / "scripts/native-interop-artifact/public-pair-upload.mjs"
    script = tmp_path / "public-pair-upload.mjs"
    script.write_bytes(original.read_bytes())
    sender, receiver = pair.Rendezvous(CONTEXT, "windows"), pair.Rendezvous(CONTEXT, "android")
    sender.bind_partner(receiver.public_manifest())
    try:
        value = sender.seal("offer_code", {"pairing_code": "MESHPAIR2.synthetic-code"})
        env = {**os.environ, **environment("windows"), "ACTIONS_RUNTIME_TOKEN": "synthetic-runtime-token"}
        if fault == "native_job": env["GITHUB_JOB"] = "native_windows_peer"
        if fault == "wrong_source": value["context"]["source_commit"] = "b" * 40
        if fault == "extra_plaintext": value["pairing_code"] = "MESHPAIR2.private"
        if fault == "unknown_phase": value["phase"] = "cold_complete_1"
        if fault == "wrong_pair": value["context"]["pair_id"] = "0" * 32
        bundle = tmp_path / "bundle.json"
        bundle.write_bytes(pair.canonical(value))
        identity = tmp_path / "identity.json"
        result = subprocess.run([node, str(script), pair.artifact_name(CONTEXT, "windows", "offer_code"),
                                 str(bundle), str(identity)],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 1 and result.stdout == result.stderr == ""
        assert not identity.exists()
    finally:
        sender.close()
        receiver.close()
