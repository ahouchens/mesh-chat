"""Public pair setup has its own bounded roles, phases and crypto domain."""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import public_core_pair_rendezvous as pair


FIELDS = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
          "run_attempt": 1, "source_commit": "a" * 40}
CONTEXT = {**FIELDS, "pair_id": pair.pair_id_for(FIELDS)}


def peers():
    windows, android = pair.Rendezvous(CONTEXT, "windows"), pair.Rendezvous(CONTEXT, "android")
    windows.bind_partner(android.public_manifest())
    android.bind_partner(windows.public_manifest())
    return windows, android


@pytest.mark.parametrize("role,phase,payload", [
    ("windows", "offer_code", {"pairing_code": "MESHPAIR2.synthetic-code"}),
    ("android", "invitation_accepted", {}),
    ("windows", "approved", {}),
    ("windows", "ready", {}), ("android", "ready", {}),
    ("windows", "done", {}), ("android", "done", {}),
])
def test_each_allowed_sealed_setup_phase_round_trips(role, phase, payload):
    windows, android = peers()
    try:
        sender, receiver = (windows, android) if role == "windows" else (android, windows)
        value = sender.seal(phase, payload)
        assert set(value) == {"v", "context", "phase", "sender", "recipient", "producer_job",
                              "created_at", "expires_at", "nonce", "ciphertext"}
        assert "pairing_code" not in json.dumps(value)
        assert receiver.open(phase, value) == payload
        with pytest.raises(ValueError):
            sender.seal(phase, payload)
        with pytest.raises(ValueError):
            receiver.open(phase, value)
    finally:
        windows.close()
        android.close()


@pytest.mark.parametrize("field,value", [
    ("repository", "other/mesh"), ("repository_id", 999), ("run_id", 999),
    ("run_attempt", 2), ("source_commit", "b" * 40), ("pair_id", "0" * 32),
])
def test_context_is_exactly_run_and_pair_bound(field, value):
    altered = {**CONTEXT, field: value}
    with pytest.raises(ValueError):
        pair.Rendezvous(altered, "windows")


def test_caller_cannot_publish_product_or_other_role_phase():
    windows, android = peers()
    try:
        with pytest.raises(ValueError):
            windows.seal("invitation_accepted", {})
        with pytest.raises(ValueError):
            windows.seal("message", {"text": "private"})
        with pytest.raises(ValueError):
            windows.seal("offer_code", {"pairing_code": "MESHPAIR2.synthetic", "text": "private"})
        with pytest.raises(ValueError):
            android.open("approved", {"text": "private"})
    finally:
        windows.close()
        android.close()


def test_authenticated_header_and_ciphertext_cannot_change():
    windows, android = peers()
    try:
        value = windows.seal("offer_code", {"pairing_code": "MESHPAIR2.synthetic"})
        tampered = {**value, "ciphertext": pair.encoded(b"x" * 32)}
        with pytest.raises(Exception):
            android.open("offer_code", tampered)
        assert android.open("offer_code", value) == {"pairing_code": "MESHPAIR2.synthetic"}
    finally:
        windows.close()
        android.close()


def test_expired_partner_key_and_replaced_key_fail_closed():
    now = [1000]
    windows = pair.Rendezvous(CONTEXT, "windows", clock=lambda: now[0])
    android = pair.Rendezvous(CONTEXT, "android", clock=lambda: now[0])
    replacement = pair.Rendezvous(CONTEXT, "android", clock=lambda: now[0])
    try:
        windows.bind_partner(android.public_manifest())
        with pytest.raises(ValueError):
            windows.bind_partner(replacement.public_manifest())
        now[0] += pair.KEY_TTL
        with pytest.raises(ValueError):
            windows.seal("offer_code", {"pairing_code": "MESHPAIR2.synthetic"})
    finally:
        windows.close()
        android.close()
        replacement.close()


def test_one_bounded_same_run_zip_entry_is_required():
    windows = pair.Rendezvous(CONTEXT, "windows")
    try:
        value = windows.public_manifest()
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as zipped:
            zipped.writestr("bundle.json", pair.canonical(value))
        archive = stream.getvalue()
        metadata = {"id": 17, "name": pair.artifact_name(CONTEXT, "windows", "key"),
                    "expired": False, "size_in_bytes": len(archive),
                    "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                    "workflow_run": {"id": 456, "head_sha": "a" * 40, "repository_id": 123}}
        assert pair.verify_artifact(metadata, archive, CONTEXT, "windows", "key") == value
        for field, bad in (("digest", "sha256:" + "0" * 64), ("size_in_bytes", 1),
                           ("name", "other")):
            changed = {**metadata, field: bad}
            with pytest.raises(ValueError):
                pair.verify_artifact(changed, archive, CONTEXT, "windows", "key")
    finally:
        windows.close()
