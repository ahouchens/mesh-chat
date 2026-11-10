"""Same-run setup exchange never promotes plaintext/artifact control into delivery."""

import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_rendezvous as exchange

CONTEXT = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
           "run_attempt": 1, "source_commit": "a" * 40}


@pytest.fixture
def pair():
    clock = [1000]
    windows = exchange.Rendezvous(CONTEXT, "windows", clock=lambda: clock[0])
    android = exchange.Rendezvous(CONTEXT, "android", clock=lambda: clock[0])
    windows.bind_partner(android.public_manifest())
    android.bind_partner(windows.public_manifest())
    try:
        yield windows, android, clock
    finally:
        windows.close()
        android.close()


def artifact(value, filename="bundle.json"):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(filename, json.dumps(value))
    archive = buffer.getvalue()
    metadata = {"name": exchange.artifact_name(CONTEXT, "windows", "key"), "expired": False,
                "size_in_bytes": len(archive), "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                "workflow_run": {"id": 456, "head_sha": "a" * 40, "repository_id": 123}}
    return metadata, archive


def test_authenticated_ephemeral_pair_round_trip_contains_no_shareable_in_uploaded_bundle(pair):
    windows, android, _ = pair
    private_shareable = "synthetic signed offer with bearer and SDP; must remain encrypted"
    sealed = windows.seal("offer", {"shareable": private_shareable})
    serialized = json.dumps(sealed)
    assert private_shareable not in serialized
    assert "private_key" not in serialized
    assert android.open("offer", sealed) == {"shareable": private_shareable}
    assert set(windows.public_manifest()) == {"v", "context", "role", "producer_job", "public_key", "created_at", "expires_at"}


@pytest.mark.parametrize("field", ["context", "phase", "sender", "recipient", "created_at", "expires_at", "nonce", "ciphertext"])
def test_encrypted_setup_rejects_tampered_binding_or_ciphertext(pair, field):
    windows, android, _ = pair
    sealed = deepcopy(windows.seal("offer", {"shareable": "private synthetic offer"}))
    if field == "context": sealed["context"]["run_attempt"] = 2
    elif field == "phase": sealed[field] = "answer"
    elif field == "sender": sealed[field] = "android"
    elif field == "recipient": sealed[field] = "windows"
    elif field in {"created_at", "expires_at"}: sealed[field] += 1
    elif field == "nonce": sealed[field] = exchange.encoded(b"n" * 12)
    else:
        ciphertext = bytearray(exchange.decode_bytes(sealed[field]))
        ciphertext[-1] ^= 1
        sealed[field] = exchange.encoded(bytes(ciphertext))
    with pytest.raises((ValueError, InvalidTag)):
        android.open("offer", sealed)


@pytest.mark.parametrize("field", ["source_commit", "run_id", "run_attempt", "repository_id"])
def test_partner_key_is_bound_to_exact_source_repository_run_and_attempt(pair, field):
    windows, android, _ = pair
    partner = deepcopy(android.public_manifest())
    partner["context"][field] = "b" * 40 if field == "source_commit" else partner["context"][field] + 1
    with pytest.raises(ValueError):
        windows.bind_partner(partner)


def test_replayed_or_expired_setup_phase_cannot_reexecute_control(pair):
    windows, android, clock = pair
    sealed = windows.seal("approved", {"approved": True})
    assert android.open("approved", sealed) == {"approved": True}
    with pytest.raises(ValueError): android.open("approved", sealed)
    with pytest.raises(ValueError): windows.seal("approved", {"approved": True})
    answer = android.seal("answer", {"shareable": "private answer"})
    clock[0] += exchange.MESSAGE_TTL
    with pytest.raises(ValueError): windows.open("answer", answer)


def test_partner_key_replacement_and_closed_context_are_fenced(pair):
    windows, _, _ = pair
    alternate = exchange.Rendezvous(CONTEXT, "android", clock=lambda: 1000)
    try:
        with pytest.raises(ValueError): windows.bind_partner(alternate.public_manifest())
    finally:
        alternate.close()
    windows.close()
    with pytest.raises(ValueError): windows.public_manifest()
    with pytest.raises(ValueError): windows.seal("approved", {"approved": True})


@pytest.mark.parametrize("payload", [{"message": "not an artifact data plane"}, {"receipt": "not an artifact receipt path"},
                                     {"shareable": "x", "private_key": "forbidden"}, {"shareable": "x" * (48 * 1024 + 1)}])
def test_only_bounded_setup_payloads_can_be_sealed(pair, payload):
    windows, _, _ = pair
    with pytest.raises(ValueError): windows.seal("offer", payload)


@pytest.mark.parametrize("fault", ["name", "expired", "run", "source", "repository", "digest", "size", "zip_path", "zip_bomb"])
def test_downloaded_archive_requires_authenticated_run_provenance_digest_and_bounded_member(fault):
    metadata, archive = artifact({"public_key": "synthetic"})
    if fault == "name": metadata["name"] += "-other"
    elif fault == "expired": metadata["expired"] = True
    elif fault == "run": metadata["workflow_run"]["id"] += 1
    elif fault == "source": metadata["workflow_run"]["head_sha"] = "b" * 40
    elif fault == "repository": metadata["workflow_run"]["repository_id"] += 1
    elif fault == "digest": metadata["digest"] = "sha256:" + "f" * 64
    elif fault == "size": metadata["size_in_bytes"] = exchange.MAX_ARCHIVE + 1
    elif fault == "zip_path": metadata, archive = artifact({}, "../bundle.json")
    else: metadata, archive = artifact({"data": "x" * (exchange.MAX_BLOB + 1)})
    with pytest.raises(ValueError): exchange.verify_artifact(metadata, archive, CONTEXT, "windows", "key")


def test_valid_archive_is_read_without_extracting_paths(pair):
    windows, _, _ = pair
    metadata, archive = artifact(windows.public_manifest())
    assert exchange.verify_artifact(metadata, archive, CONTEXT, "windows", "key") == windows.public_manifest()


@pytest.mark.parametrize("role", ["windows", "android"])
def test_cold_capabilities_use_distinct_sealed_single_use_phase_with_existing_limits(pair, role):
    from mesh_chat.reconnect import MAX_CAPABILITY_BYTES
    sender, recipient = pair[:2] if role == "windows" else pair[1::-1]
    assert exchange.MAX_CAPABILITY_BYTES == MAX_CAPABILITY_BYTES == 16384
    payload = {"capabilities": "PRIVATE_SIGNED_CAPABILITY_CREDENTIAL"}
    sealed = sender.seal("reconnect_capabilities", payload)
    assert b"PRIVATE_SIGNED_CAPABILITY_CREDENTIAL" not in exchange.canonical(sealed)
    assert exchange.validate_upload(CONTEXT, role, "reconnect_capabilities", sealed) == sealed
    assert recipient.open("reconnect_capabilities", sealed) == payload
    with pytest.raises(ValueError): recipient.open("reconnect_capabilities", sealed)
    with pytest.raises(ValueError): sender.seal("reconnect_capabilities", payload)
    assert exchange.MESSAGE_TTL == 600 and exchange.KEY_TTL == 7200
    assert exchange.MAX_BLOB == 96 * 1024 and exchange.MAX_ARCHIVE == 128 * 1024


@pytest.mark.parametrize("payload", [None, [], {}, {"capabilities": ""}, {"capabilities": 1},
    {"capabilities": True}, {"capabilities": b"x"}, {"capabilities": "x", "approved": True},
    {"document": "x"}, {"shareable": "x"}, {"capabilities": "x" * 16385},
    {"capabilities": "\u00e9" * 8193}, {"capabilities": "\x00" * 16384},
    {"capabilities": "\u00e9" * 8192}, {"capabilities": "\ud800"}])
def test_cold_capability_plaintext_is_exact_utf8_and_canonical_bounded(pair, payload):
    windows, _, _ = pair
    with pytest.raises(ValueError): windows.seal("reconnect_capabilities", payload)
    assert "reconnect_capabilities" not in windows._sent


@pytest.mark.parametrize("kind", ["utf8_max", "canonical_max"])
def test_cold_capability_accepts_exact_limits_but_rejects_one_more_byte(pair, kind):
    windows, android, _ = pair
    if kind == "utf8_max": text = "x" * 16384
    else:
        available = exchange.MAX_SHAREABLE - len(exchange.canonical({"capabilities": ""}))
        text = "\x00" * (available // 6) + "x" * (available % 6)
        assert len(exchange.canonical({"capabilities": text})) == exchange.MAX_SHAREABLE
    with pytest.raises(ValueError): windows.seal("reconnect_capabilities", {"capabilities": text + "x"})
    sealed = windows.seal("reconnect_capabilities", {"capabilities": text})
    exchange.validate_upload(CONTEXT, "windows", "reconnect_capabilities", sealed)
    assert android.open("reconnect_capabilities", sealed) == {"capabilities": text}


@pytest.mark.parametrize("fault", ["phase", "sender", "recipient", "source", "run", "attempt", "expired", "ciphertext"])
def test_cold_capability_phase_retains_all_existing_cryptographic_bindings(pair, fault):
    windows, android, clock = pair
    sealed = deepcopy(windows.seal("reconnect_capabilities", {"capabilities": "PRIVATE_SIGNED_DOCUMENT"}))
    if fault == "phase": sealed["phase"] = "control"
    elif fault in {"sender", "recipient"}: sealed[fault] = "android" if fault == "sender" else "windows"
    elif fault == "source": sealed["context"]["source_commit"] = "b" * 40
    elif fault == "run": sealed["context"]["run_id"] += 1
    elif fault == "attempt": sealed["context"]["run_attempt"] += 1
    elif fault == "expired": clock[0] += exchange.MESSAGE_TTL
    else:
        raw = bytearray(exchange.decode_bytes(sealed["ciphertext"])); raw[-1] ^= 1
        sealed["ciphertext"] = exchange.encoded(raw)
    with pytest.raises((ValueError, InvalidTag)): android.open("reconnect_capabilities", sealed)
    assert "reconnect_capabilities" not in android._received


def test_cold_capabilities_cannot_overload_existing_control_or_offer_schema(pair):
    windows, android, _ = pair
    plan = {"scenarios": ["direct"], "iterations": 100, "cold_start_every": 10}
    assert android.open("control", windows.seal("control", plan)) == plan
    for phase in ("control", "offer", "answer", "result", "approved"):
        with pytest.raises(ValueError): exchange.checked_payload(phase, {"capabilities": "signed"})
    with pytest.raises(ValueError): exchange.checked_payload("control", {**plan, "capabilities": "signed"})
