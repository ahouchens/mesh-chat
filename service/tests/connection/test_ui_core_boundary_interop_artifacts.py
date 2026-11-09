"""Bounded workflow rendezvous authenticates source/run/attempt/producer context."""

import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_artifacts as backend
from native_interop_rendezvous import Rendezvous, artifact_name, canonical

CONTEXT = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
           "run_attempt": 1, "source_commit": "a" * 40}


def environment(role):
    return {"GITHUB_REPOSITORY": "example/mesh", "GITHUB_REPOSITORY_ID": "123", "GITHUB_RUN_ID": "456",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
            "GITHUB_JOB": backend.PRODUCER_JOBS[role], "GITHUB_TOKEN": "synthetic-test-token"}


def archive(value):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr("bundle.json", canonical(value))
    result = stream.getvalue()
    metadata = {"id": 10, "name": artifact_name(CONTEXT, "windows", "key"), "expired": False,
                "size_in_bytes": len(result), "digest": "sha256:" + hashlib.sha256(result).hexdigest(),
                "workflow_run": {"id": 456, "head_sha": "a" * 40, "repository_id": 123}}
    return metadata, result


@pytest.mark.parametrize("field", ["GITHUB_JOB", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_REPOSITORY_ID"])
def test_publisher_refuses_other_producer_source_repository_run_or_attempt(tmp_path, field):
    env = environment("windows")
    env[field] = {"GITHUB_JOB": "other_job", "GITHUB_SHA": "b" * 40}.get(field, "999")
    with pytest.raises(backend.RendezvousUnavailable):
        backend.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=env)


def test_download_accepts_only_rehashed_same_run_bundle(tmp_path, monkeypatch):
    peer = Rendezvous(CONTEXT, "windows")
    transport = backend.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"))
    try:
        metadata, blob = archive(peer.public_manifest())
        calls = []
        def request(path, *, binary=False):
            calls.append((path, binary))
            return blob if binary else {"total_count": 1, "artifacts": [metadata]}
        monkeypatch.setattr(transport, "_request", request)
        assert transport.wait("windows", "key") == peer.public_manifest()
        assert len(calls) == 2 and calls[1][1]
    finally:
        peer.close()
        transport.close()


@pytest.mark.parametrize("fault", ["duplicates", "unbounded_inventory", "wrong_digest", "wrong_job", "invalid_id"])
def test_wrong_or_ambiguous_partner_artifact_never_becomes_setup(tmp_path, monkeypatch, fault):
    peer = Rendezvous(CONTEXT, "windows")
    transport = backend.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"))
    try:
        value = peer.public_manifest()
        if fault == "wrong_job": value["producer_job"] = "other_job"
        metadata, blob = archive(value)
        if fault == "wrong_digest": metadata["digest"] = "sha256:" + "f" * 64
        elif fault == "invalid_id": metadata["id"] = True
        inventory = {"total_count": 1, "artifacts": [metadata]}
        if fault == "duplicates": inventory = {"total_count": 2, "artifacts": [metadata, metadata]}
        elif fault == "unbounded_inventory": inventory["total_count"] = 101
        monkeypatch.setattr(transport, "_request", lambda path, binary=False: blob if binary else inventory)
        with pytest.raises((ValueError, backend.RendezvousUnavailable)):
            transport.wait("windows", "key")
    finally:
        peer.close()
        transport.close()


def test_missing_partner_uses_finite_deadline_and_cannot_mix_old_attempt(tmp_path, monkeypatch):
    now = [0.0]
    transport = backend.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"),
                                      clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    peer = Rendezvous({**CONTEXT, "run_attempt": 2}, "windows")
    metadata, _ = archive(peer.public_manifest())
    metadata["name"] = artifact_name(peer.context, "windows", "key")
    calls = []
    monkeypatch.setattr(transport, "_request", lambda *args, **kwargs: calls.append(1) or {"total_count": 1, "artifacts": [metadata]})
    with pytest.raises(backend.RendezvousUnavailable, match="deadline"):
        transport.wait("windows", "key", timeout=10)
    assert now[0] == 10 and len(calls) == 4
    peer.close()
    transport.close()


def test_repository_bearer_is_not_forwarded_to_artifact_blob_redirect(tmp_path, monkeypatch):
    transport = backend.GithubArtifacts(CONTEXT, "android", tmp_path, environment=environment("android"))
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 302, "redirect",
                                             {"Location": "https://synthetic.invalid/blob?signed=private"}, None)
            return BytesIO(b"archive bytes")
    monkeypatch.setattr(backend.urllib.request, "build_opener", lambda *_: Opener())
    assert transport._request("/synthetic", binary=True) == b"archive bytes"
    assert requests[0].get_header("Authorization") == "Bearer synthetic-test-token"
    assert requests[1].get_header("Authorization") is None
    transport.close()


def test_failed_upload_removes_bundle_and_does_not_log_raw_sdk_error(tmp_path, monkeypatch):
    transport = backend.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=environment("windows"))
    peer = Rendezvous(CONTEXT, "windows")
    marker = "synthetic credential that must never be echoed"
    monkeypatch.setattr(backend.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="", stderr=marker))
    with pytest.raises(backend.RendezvousUnavailable) as failure:
        transport.publish("key", peer.public_manifest())
    assert marker not in str(failure.value)
    assert list(tmp_path.iterdir()) == []
    peer.close()
    transport.close()


def test_each_publisher_phase_is_single_use_and_cleans_temporary_bundle(tmp_path, monkeypatch):
    transport = backend.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=environment("windows"))
    peer = Rendezvous(CONTEXT, "windows")
    monkeypatch.setattr(backend.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps({"passed": True, "id": 5, "size": 100}), stderr=""))
    assert transport.publish("key", peer.public_manifest())["id"] == 5
    with pytest.raises(ValueError): transport.publish("key", peer.public_manifest())
    assert list(tmp_path.iterdir()) == []
    transport.close()
    assert transport._token is None
    peer.close()


@pytest.mark.parametrize("fault", ["raw_shareable", "credential", "extra_field", "phase", "role", "nonce", "ciphertext"])
def test_upload_boundary_rejects_plaintext_or_wrong_envelope_before_writing_or_spawning(tmp_path, monkeypatch, fault):
    transport = backend.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=environment("windows"))
    windows = Rendezvous(CONTEXT, "windows")
    android = Rendezvous(CONTEXT, "android")
    windows.bind_partner(android.public_manifest())
    bundle = windows.seal("offer", {"shareable": "private synthetic invitation"})
    if fault == "raw_shareable":
        bundle = {"context": CONTEXT, "producer_job": "native_windows_peer", "shareable": "private synthetic invitation"}
    elif fault == "credential": bundle["turn_credential"] = "must never be published"
    elif fault == "extra_field": bundle["debug"] = {"plaintext": "private invitation"}
    elif fault == "phase": bundle["phase"] = "answer"
    elif fault == "role": bundle["sender"] = "android"
    elif fault == "nonce": bundle["nonce"] = "short"
    else: bundle["ciphertext"] = "not-encrypted"
    calls = []
    monkeypatch.setattr(backend.subprocess, "run", lambda *args, **kwargs: calls.append(1))
    try:
        with pytest.raises(ValueError): transport.publish("offer", bundle)
        assert calls == [] and list(tmp_path.iterdir()) == []
    finally:
        windows.close()
        android.close()
        transport.close()


def test_closing_artifact_transport_fences_later_publish_and_wait(tmp_path):
    transport = backend.GithubArtifacts(CONTEXT, "windows", tmp_path, environment=environment("windows"))
    peer = Rendezvous(CONTEXT, "windows")
    transport.close()
    try:
        with pytest.raises(backend.RendezvousUnavailable, match="closed"):
            transport.publish("key", peer.public_manifest())
        with pytest.raises(backend.RendezvousUnavailable, match="closed"):
            transport.wait("android", "key")
    finally:
        peer.close()
