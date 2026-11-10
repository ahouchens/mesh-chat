"""Bounded workflow rendezvous authenticates source/run/attempt/producer context."""

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import urllib.error
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_artifacts as backend
from native_interop_rendezvous import Rendezvous, artifact_name, canonical, encoded

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


def scripted_receive(tmp_path, monkeypatch, fault="inventory_http", *, status=403, role="windows", phase="key"):
    """Actual request/wait with inert stdlib opener boundaries, no network."""
    state = SimpleNamespace(fault=fault, status=status, calls=[], sleeps=[], now=0.0, original_http=None)
    state.bundle = {"producer_job": backend.PRODUCER_JOBS[role], "PRIVATE_BODY": "PRIVATE_PAYLOAD"}
    state.metadata, state.blob = archive(state.bundle)
    state.metadata["name"] = artifact_name(CONTEXT, role, phase)
    state.transport = backend.GithubArtifacts(CONTEXT, "android" if role == "windows" else "windows", tmp_path,
        environment=environment("android" if role == "windows" else "windows"), clock=lambda: state.now,
        sleep=lambda seconds: (state.sleeps.append(seconds), setattr(state, "now", state.now + seconds)))
    state.role, state.phase = role, phase
    class Response(BytesIO):
        @property
        def status(self): raise AssertionError("Normal response status must not be inspected")
        def getcode(self): raise AssertionError("Normal response getcode must not be inspected")
        def __enter__(self):
            if state.fault == "context_enter": raise OSError("PRIVATE_CONTEXT_ERROR")
            return super().__enter__()
        def __exit__(self, *args):
            result = super().__exit__(*args)
            if state.fault == "context_exit": raise OSError("PRIVATE_CONTEXT_ERROR")
            return result
        def read(self, limit):
            if state.fault == "read_timeout": raise TimeoutError("PRIVATE_TIMEOUT")
            if state.fault == "read_http": raise urllib.error.HTTPError("PRIVATE_URL", 409, "PRIVATE_READ_ERROR", {}, None)
            return super().read(limit)
    class ForgedFailure(OSError):
        @property
        def code(self): raise AssertionError("Non-HTTP code must not be inspected")
    class Opener:
        def open(self, request, timeout):
            stage = ("inventory_request" if request.full_url.endswith("/artifacts?per_page=100")
                     else "blob_request" if request.full_url.startswith("https://synthetic.invalid/") else "archive_request")
            state.calls.append({"stage": stage, "timeout": timeout, "bearer": request.get_header("Authorization") is not None})
            if state.fault == "inventory_http" and stage == "inventory_request" or state.fault == "archive_http" and stage == "archive_request":
                state.original_http = urllib.error.HTTPError(request.full_url, state.status, "PRIVATE_HTTP_MESSAGE", {}, None)
                raise state.original_http
            if state.fault == "open_timeout": raise TimeoutError("PRIVATE_TIMEOUT deadline_exhausted")
            if state.fault == "url_timeout": raise urllib.error.URLError(TimeoutError("PRIVATE_TIMEOUT"))
            if state.fault == "forged_code": raise ForgedFailure("PRIVATE_ERROR_ARGS")
            if stage == "inventory_request":
                inventory = {"total_count": 1, "artifacts": [state.metadata]}
                if state.fault == "inventory_shape": inventory["artifacts"] = "PRIVATE_ROWS"
                if state.fault == "inventory_count": inventory["total_count"] = True
                if state.fault == "inventory_bound": inventory["total_count"] = 101
                if state.fault == "duplicate": inventory = {"total_count": 2, "artifacts": [state.metadata, state.metadata]}
                if state.fault == "missing_id": inventory["artifacts"] = [{**state.metadata, "id": True}]
                if state.fault == "deadline": inventory = {"total_count": 0, "artifacts": []}
                data = json.dumps(inventory).encode()
                if state.fault == "empty": data = b""
                if state.fault == "oversized": data = b"X" * (backend.MAX_API_RESPONSE + 1)
                if state.fault == "json_invalid": data = b"PRIVATE_NOT_JSON"
                if state.fault == "json_encoding": data = b"\xff"
                if state.fault == "json_recursion":
                    depth = max(10000, sys.getrecursionlimit() + 100)
                    data = b"[" * depth + b"0" + b"]" * depth
                return Response(data)
            if stage == "archive_request" and state.fault in {"blob_http", "blob_timeout", "blob_empty", "blob_oversized", "redirect_invalid", "redirect_parse"}:
                location = ("http://synthetic.invalid/PRIVATE_SIGNED" if state.fault == "redirect_invalid" else
                            "https://[PRIVATE_INVALID" if state.fault == "redirect_parse" else "https://synthetic.invalid/PRIVATE_SIGNED")
                raise urllib.error.HTTPError(request.full_url, 302, "PRIVATE_REDIRECT", {"Location": location}, None)
            if stage == "blob_request" and state.fault == "blob_http":
                state.original_http = urllib.error.HTTPError(request.full_url, state.status, "PRIVATE_BLOB_ERROR", {}, None)
                raise state.original_http
            if stage == "blob_request" and state.fault == "blob_timeout": raise TimeoutError("PRIVATE_BLOB_TIMEOUT")
            return Response(b"" if state.fault == "blob_empty" else
                            b"X" * (backend.MAX_ARCHIVE + 1) if state.fault == "blob_oversized" else state.blob)
    monkeypatch.setattr(backend.urllib.request, "build_opener", lambda *_: Opener())
    return state


RECEIVE_ORIGINS = [
    ("inventory_http", "inventory_request", "http_rejected", 1),
    ("archive_http", "archive_request", "http_rejected", 2),
    ("blob_http", "blob_request", "http_rejected", 3),
    ("redirect_invalid", "archive_request", "redirect_invalid", 2),
    ("redirect_parse", "archive_request", "redirect_invalid", 2),
    ("open_timeout", "inventory_request", "transport_failed", 1),
    ("url_timeout", "inventory_request", "transport_failed", 1),
    ("forged_code", "inventory_request", "transport_failed", 1),
    ("blob_timeout", "blob_request", "transport_failed", 3),
    ("read_timeout", "inventory_request", "read_failed", 1),
    ("read_http", "inventory_request", "read_failed", 1),
    ("context_enter", "inventory_request", "read_failed", 1),
    ("context_exit", "inventory_request", "read_failed", 1),
    ("empty", "inventory_request", "response_empty", 1),
    ("oversized", "inventory_request", "response_oversized", 1),
    ("blob_empty", "blob_request", "response_empty", 3),
    ("blob_oversized", "blob_request", "response_oversized", 3),
    ("json_invalid", "inventory_request", "json_invalid", 1),
    ("json_encoding", "inventory_request", "json_invalid", 1),
    ("json_recursion", "inventory_request", "transport_failed", 1),
    ("inventory_shape", "inventory_check", "inventory_invalid", 1),
    ("inventory_count", "inventory_check", "inventory_invalid", 1),
    ("inventory_bound", "inventory_check", "inventory_invalid", 1),
    ("duplicate", "inventory_check", "duplicate_identity", 1),
    ("missing_id", "inventory_check", "missing_identity", 1),
    ("deadline", "partner_wait", "deadline_exhausted", 60),
]


@pytest.mark.parametrize("fault,stage,reason,count", RECEIVE_ORIGINS)
def test_exact_receive_origin_preserves_failure_identity_budget_and_redaction(tmp_path, monkeypatch, fault, stage, reason, count):
    state = scripted_receive(tmp_path, monkeypatch, fault)
    created = []
    unavailable = state.transport._unavailable
    def create(*args):
        error = unavailable(*args)
        created.append(error)
        return error
    monkeypatch.setattr(state.transport, "_unavailable", create)
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase, timeout=180)
    assert type(caught.value) is backend.RendezvousUnavailable and created == [caught.value]
    expected = {"rendezvous_stage": stage, "rendezvous_reason": reason}
    if fault.endswith("http") and fault != "read_http": expected["rendezvous_http_status"] = 403
    selected = state.transport.failure_observation(caught.value)
    assert selected == expected
    assert state.transport.failure_observation(state.original_http) == {}
    assert state.transport.failure_observation(backend.RendezvousUnavailable("PRIVATE_FOREIGN")) == {}
    selected["rendezvous_stage"] = "PRIVATE_MUTATION"
    assert state.transport.failure_observation(caught.value) == expected
    assert len(state.calls) == count and all(call["timeout"] == 10 for call in state.calls)
    assert all(call["bearer"] is (call["stage"] != "blob_request") for call in state.calls)
    assert state.sleeps == ([3] * 60 if fault == "deadline" else [])
    assert "PRIVATE" not in json.dumps(expected) + str(caught.value)


class StatusInt(int):
    pass


@pytest.mark.parametrize("status", [100, 302, 599, True, StatusInt(403), 403.0, "403", None, 99, 600])
def test_http_status_is_observed_exact_integer_only_at_open(tmp_path, monkeypatch, status):
    state = scripted_receive(tmp_path, monkeypatch, status=status)
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    observed = state.transport.failure_observation(caught.value)
    if type(status) is int and 100 <= status <= 599: assert observed["rendezvous_http_status"] == status
    else: assert "rendezvous_http_status" not in observed
    assert len(state.calls) == 1 and observed["rendezvous_reason"] == "http_rejected"


@pytest.mark.parametrize("status", [302, 409, 500, 599])
def test_redirected_open_status_is_not_replaced_by_initial_302(tmp_path, monkeypatch, status):
    state = scripted_receive(tmp_path, monkeypatch, "blob_http", status=status)
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    state.original_http.code = 100  # Capture occurred at the actual failing open.
    assert state.transport.failure_observation(caught.value) == {
        "rendezvous_stage": "blob_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": status}
    assert [call["bearer"] for call in state.calls] == [True, True, False]
    assert str(caught.value) == "GitHub artifact transport is unavailable"


def test_http_error_subclass_cannot_supply_status_properties(tmp_path, monkeypatch):
    state = scripted_receive(tmp_path, monkeypatch)
    class NonstandardHTTPError(urllib.error.HTTPError):
        @property
        def code(self): raise AssertionError("Subclass code must not be inspected for diagnostics")
        @code.setter
        def code(self, value): pass
    class Opener:
        def open(self, request, timeout):
            raise NonstandardHTTPError(request.full_url, 403, "PRIVATE_HTTP_ERROR", {}, None)
    monkeypatch.setattr(backend.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    assert state.transport.failure_observation(caught.value) == {
        "rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected"}


@pytest.mark.parametrize("fault", ["digest", "producer", "archive"])
def test_verification_failure_retains_original_type_without_transport_provenance(tmp_path, monkeypatch, fault):
    state = scripted_receive(tmp_path, monkeypatch, "success")
    if fault == "digest": state.metadata["digest"] = "sha256:" + "0" * 64
    elif fault == "producer":
        state.bundle["producer_job"] = "PRIVATE_JOB"
        state.metadata, state.blob = archive(state.bundle)
    else:
        state.blob = b"PRIVATE_NOT_AN_ARCHIVE"
        state.metadata["size_in_bytes"] = len(state.blob)
        state.metadata["digest"] = "sha256:" + hashlib.sha256(state.blob).hexdigest()
    with pytest.raises(zipfile.BadZipFile if fault == "archive" else ValueError) as caught:
        state.transport.wait(state.role, state.phase)
    assert state.transport.failure_observation(caught.value) == {} and len(state.calls) == 2


@pytest.mark.parametrize("activity", ["wait_success", "request_success", "request_failure", "publish", "close", "invalid_wait"])
def test_new_transport_activity_cannot_resurrect_previous_receive_failure(tmp_path, monkeypatch, activity):
    state = scripted_receive(tmp_path, monkeypatch)
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    error = caught.value
    assert state.transport.failure_observation(error)
    state.fault = "success"
    if activity == "wait_success":
        assert state.transport.wait(state.role, state.phase) == state.bundle
    elif activity == "request_success":
        state.transport._request("/artifacts?per_page=100")
    elif activity == "request_failure":
        state.fault = "inventory_http"
        with pytest.raises(backend.RendezvousUnavailable) as later:
            state.transport._request("/artifacts?per_page=100")
        assert state.transport.failure_observation(later.value) == {}  # Not a receive operation.
    elif activity == "publish":
        with pytest.raises(ValueError): state.transport.publish("key", {"PRIVATE_BODY": "PRIVATE_PAYLOAD"})
    elif activity == "invalid_wait":
        with pytest.raises(ValueError): state.transport.wait(state.role, state.phase, timeout=0)
    else: state.transport.close()
    assert state.transport.failure_observation(error) == {}


def test_closed_wait_origin_and_replaced_nested_error_do_not_mix(tmp_path, monkeypatch):
    state = scripted_receive(tmp_path, monkeypatch)
    original_wait = state.transport._wait
    original_errors = []
    def replaced(*args):
        try: return original_wait(*args)
        except backend.RendezvousUnavailable as error:
            original_errors.append(error)
            raise ValueError("PRIVATE_CLEANUP_SUBSTITUTION") from None
    monkeypatch.setattr(state.transport, "_wait", replaced)
    with pytest.raises(ValueError): state.transport.wait(state.role, state.phase)
    assert state.transport.failure_observation(original_errors[0]) == {}
    monkeypatch.setattr(state.transport, "_wait", original_wait)
    state.transport.close()
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    assert state.transport.failure_observation(caught.value) == {
        "rendezvous_stage": "transport_state", "rendezvous_reason": "closed"}
    assert len(state.calls) == 1


class SelectedString(str):
    pass


@pytest.mark.parametrize("projection", [
    pytest.param(value, id=label) for label, value in (
        ("non-object", []), ("missing", {"rendezvous_stage": "inventory_request"}),
        ("stage", {"rendezvous_stage": "PRIVATE_STAGE", "rendezvous_reason": "http_rejected"}),
        ("stage-type", {"rendezvous_stage": [], "rendezvous_reason": "http_rejected"}),
        ("stage-subclass", {"rendezvous_stage": SelectedString("inventory_request"), "rendezvous_reason": "http_rejected"}),
        ("reason", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "PRIVATE_REASON"}),
        ("reason-type", {"rendezvous_stage": "inventory_request", "rendezvous_reason": []}),
        ("combination", {"rendezvous_stage": "partner_wait", "rendezvous_reason": "http_rejected"}),
        ("extra", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "url": "PRIVATE_URL"}),
        ("status-bool", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": True}),
        ("status-subclass", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": StatusInt(403)}),
        ("status-float", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": 403.0}),
        ("status-string", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": "403"}),
        ("status-small", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": 99}),
        ("status-large", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "http_rejected", "rendezvous_http_status": 600}),
        ("status-provenance", {"rendezvous_stage": "inventory_request", "rendezvous_reason": "read_failed", "rendezvous_http_status": 403}),
    )
])
def test_receive_projection_validation_omits_unknown_extra_or_wrong_type_fields(projection):
    from native_interop_diagnostics import rendezvous_observation
    assert rendezvous_observation(projection) == {}


def test_fixed_receive_projection_has_only_literal_stages_and_reasons():
    from native_interop_diagnostics import RENDEZVOUS_REASONS, rendezvous_observation
    assert set(RENDEZVOUS_REASONS) == {"inventory_request", "archive_request", "blob_request", "inventory_check", "partner_wait", "transport_state"}
    assert set().union(*RENDEZVOUS_REASONS.values()) == {
        "http_rejected", "redirect_invalid", "response_empty", "response_oversized", "json_invalid", "read_failed",
        "transport_failed", "inventory_invalid", "duplicate_identity", "missing_identity", "deadline_exhausted", "closed"}
    for stage, reasons in RENDEZVOUS_REASONS.items():
        for reason in reasons:
            value = {"rendezvous_stage": stage, "rendezvous_reason": reason}
            selected = rendezvous_observation(value)
            assert selected == value and selected is not value


def test_decoder_value_error_cannot_inherit_completed_response_read_origin(tmp_path, monkeypatch):
    state = scripted_receive(tmp_path, monkeypatch, "json_invalid")
    decode = backend.json.loads
    def limited_decoder(data, *args, **kwargs):
        if data == b"PRIVATE_NOT_JSON": raise ValueError("PRIVATE_DECODER_LIMIT")
        return decode(data, *args, **kwargs)
    monkeypatch.setattr(backend.json, "loads", limited_decoder)
    with pytest.raises(backend.RendezvousUnavailable) as caught:
        state.transport.wait(state.role, state.phase)
    assert str(caught.value) == "GitHub artifact transport is unavailable"
    assert state.transport.failure_observation(caught.value) == {
        "rendezvous_stage": "inventory_request", "rendezvous_reason": "transport_failed"}
    assert len(state.calls) == 1


@pytest.mark.parametrize("role", ["windows", "android"])
@pytest.mark.parametrize("fault", [None, "unknown_phase", "plaintext", "extra_field", "wrong_job", "wrong_source", "nonce", "ciphertext"])
def test_actual_node_upload_accepts_only_sealed_cold_phase_without_sdk_or_network(tmp_path, role, fault):
    """Execute the real upload validator with a local inert ArtifactClient module."""
    node = os.environ.get("MESH_NODE") or shutil.which("node")
    assert node, "Node is required for the upload validator control"
    source = Path(__file__).resolve().parents[3] / "scripts/native-interop-artifact/upload.mjs"
    script = tmp_path / "upload.mjs"
    script.write_bytes(source.read_bytes())
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
    sender = Rendezvous(CONTEXT, role)
    partner = Rendezvous(CONTEXT, "android" if role == "windows" else "windows")
    sender.bind_partner(partner.public_manifest())
    try:
        phase = "reconnect_capabilities"
        sealed = sender.seal(phase, {"capabilities": "PRIVATE_SIGNED_CREDENTIALS"})
        env = {**os.environ, **environment(role), "ACTIONS_RUNTIME_TOKEN": "PRIVATE_TEST_RUNTIME_TOKEN",
               "MESH_UPLOAD_OBSERVATION": str(tmp_path / "observed.json")}
        if fault == "unknown_phase": sealed["phase"] = "reconnect_documents"
        elif fault == "plaintext": sealed = {"capabilities": "PRIVATE_SIGNED_CREDENTIALS"}
        elif fault == "extra_field": sealed["capabilities"] = "PRIVATE_SIGNED_CREDENTIALS"
        elif fault == "wrong_job": env["GITHUB_JOB"] = "untrusted"
        elif fault == "wrong_source": sealed["context"]["source_commit"] = "b" * 40
        elif fault == "nonce": sealed["nonce"] = "short"
        elif fault == "ciphertext": sealed["ciphertext"] = encoded(b"x" * (48 * 1024 + 1025))
        bundle = tmp_path / "bundle.json"
        bundle.write_bytes(canonical(sealed))
        result = subprocess.run([node, str(script), artifact_name(CONTEXT, role, phase), str(bundle)],
            env=env, capture_output=True, text=True, check=False, timeout=10)
        assert result.stderr == "" and "PRIVATE" not in result.stdout
        if fault is None:
            assert result.returncode == 0 and json.loads(result.stdout) == {"passed": True, "id": 17, "size": 123}
            observed = json.loads((tmp_path / "observed.json").read_text())
            assert observed["body"] == sealed
            assert observed["options"] == {"retentionDays": 1, "compressionLevel": 0}
            assert observed["files"] == [str(bundle)]
            assert "PRIVATE" not in json.dumps(observed)
        else:
            assert result.returncode == 1 and json.loads(result.stdout) == {"passed": False}
            assert not (tmp_path / "observed.json").exists()
    finally:
        sender.close()
        partner.close()
