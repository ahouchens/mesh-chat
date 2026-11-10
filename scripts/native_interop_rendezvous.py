"""Test-controller bootstrap only: bounded encrypted artifacts within one CI run.

Product signaling stays in the production encrypted mailbox. Chat messages and
authenticated receipts never travel through this rendezvous. Private ephemeral
keys are process-local; only public keys and sealed setup/control are uploadable.
"""

import base64
import hashlib
import hmac
from io import BytesIO
import json
import os
import re
import time
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROLES = {"windows", "android"}
PRODUCER_JOBS = {"windows": "native_windows_peer", "android": "native_android_peer"}
OFFER_PHASES = {"offer", "offer_turn_udp", "offer_turn_tcp", "offer_turn_tls", "offer_impaired"}
NEGATIVE_CASES = {"turn_tcp", "turn_tls", "impaired"}
APPROVAL_PHASES = {"approved", "impaired_ready"} | {
    prefix + scenario for prefix in ("negative_ready_", "negative_checked_") for scenario in NEGATIVE_CASES}
PHASES = OFFER_PHASES | APPROVAL_PHASES | {"answer", "control", "result", "reconnect_capabilities"}
KEY_TTL = 7200
MESSAGE_TTL = 600
MAX_BLOB = 96 * 1024
MAX_ARCHIVE = 128 * 1024
MAX_SHAREABLE = 48 * 1024
MAX_CAPABILITY_BYTES = 16 * 1024
DOMAIN = b"mesh-native-ci-bootstrap:v1:"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def checked_context(value):
    fields = {"repository", "repository_id", "run_id", "run_attempt", "source_commit"}
    if (not isinstance(value, dict) or set(value) != fields
            or not isinstance(value["repository"], str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]) is None
            or any(part in {".", ".."} for part in value["repository"].split("/"))
            or any(type(value[key]) is not int or value[key] <= 0 for key in ("repository_id", "run_id", "run_attempt"))
            or not isinstance(value["source_commit"], str) or re.fullmatch(r"[a-f0-9]{40}", value["source_commit"]) is None):
        raise ValueError("Invalid source/run-bound rendezvous context")
    return dict(value)


def artifact_name(context, role, phase):
    checked_context(context)
    if role not in ROLES or phase not in PHASES | {"key"}:
        raise ValueError("Invalid rendezvous role or phase")
    return f"mesh-native-v1-{context['run_id']}-{context['run_attempt']}-{context['source_commit'][:12]}-{role}-{phase}"


def checked_payload(phase, value):
    if not isinstance(value, dict):
        raise ValueError("Bootstrap payload must be a bounded object")
    if phase in OFFER_PHASES | {"answer"}:
        valid = (set(value) == {"shareable"} and isinstance(value["shareable"], str)
                 and 0 < len(value["shareable"].encode("utf-8")) <= MAX_SHAREABLE)
    elif phase in APPROVAL_PHASES:
        valid = set(value) == {"approved"} and type(value["approved"]) is bool
    elif phase == "reconnect_capabilities":
        valid = (set(value) == {"capabilities"} and type(value["capabilities"]) is str
                 and 0 < len(value["capabilities"].encode("utf-8")) <= MAX_CAPABILITY_BYTES
                 and len(canonical(value)) <= MAX_SHAREABLE)
    elif phase == "control":
        valid = (set(value) == {"scenarios", "iterations", "cold_start_every"}
                 and isinstance(value["scenarios"], list) and 0 < len(value["scenarios"]) <= 8
                 and all(item in {"direct", "turn_udp", "turn_tcp", "turn_tls", "impaired", "cold_start_receipts"}
                         for item in value["scenarios"])
                 and type(value["iterations"]) is int and value["iterations"] == 100
                 and type(value["cold_start_every"]) is int and value["cold_start_every"] == 10)
    elif phase == "result":
        valid = (set(value) == {"report_sha256", "passed"} and type(value["passed"]) is bool
                 and isinstance(value["report_sha256"], str)
                 and re.fullmatch(r"[a-f0-9]{64}", value["report_sha256"]) is not None)
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid setup/control payload; product traffic is not a rendezvous phase")
    return value


def decode_bytes(value, length=None):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("Invalid bootstrap encoding")
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if length is not None and len(decoded) != length:
        raise ValueError("Invalid bootstrap key or nonce length")
    return decoded


def encoded(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def validate_upload(context, role, phase, value):
    """Fail before writing any file if plaintext crosses the upload boundary."""
    artifact_name(context, role, phase)
    common = {"v", "context", "producer_job", "created_at", "expires_at"}
    fields = common | ({"role", "public_key"} if phase == "key"
                       else {"phase", "sender", "recipient", "nonce", "ciphertext"})
    if (not isinstance(value, dict) or set(value) != fields or len(canonical(value)) > MAX_BLOB
            or type(value.get("v")) is not int or value["v"] != 1 or value.get("context") != context
            or value.get("producer_job") != PRODUCER_JOBS[role]
            or type(value.get("created_at")) is not int or type(value.get("expires_at")) is not int
            or value["expires_at"] != value["created_at"] + (KEY_TTL if phase == "key" else MESSAGE_TTL)):
        raise ValueError("Only exact public-key manifests and sealed setup envelopes may be uploaded")
    if phase == "key":
        if value["role"] != role:
            raise ValueError("Public-key publishing role is inconsistent")
        decode_bytes(value["public_key"], 32)
    else:
        if value["phase"] != phase or value["sender"] != role or value["recipient"] != next(iter(ROLES - {role})):
            raise ValueError("Sealed publishing phase or role is inconsistent")
        decode_bytes(value["nonce"], 12)
        ciphertext = decode_bytes(value["ciphertext"])
        if not 16 <= len(ciphertext) <= MAX_SHAREABLE + 1024:
            raise ValueError("Sealed bootstrap ciphertext exceeds its budget")
    return value


def verify_artifact(metadata, archive, context, role, phase):
    """Metadata comes from authenticated REST scoped to the SAME repository/run."""
    expected = artifact_name(context, role, phase)
    workflow = metadata.get("workflow_run", {}) if isinstance(metadata, dict) else {}
    if (not isinstance(metadata, dict) or metadata.get("name") != expected or metadata.get("expired") is not False
            or not isinstance(workflow, dict)
            or workflow.get("id") != context["run_id"] or workflow.get("head_sha") != context["source_commit"]
            or workflow.get("repository_id") != context["repository_id"]
            or type(metadata.get("size_in_bytes")) is not int or not 0 < metadata["size_in_bytes"] <= MAX_ARCHIVE
            or not isinstance(archive, bytes) or not 0 < len(archive) <= MAX_ARCHIVE
            or not isinstance(metadata.get("digest"), str)
            or not hmac.compare_digest(metadata["digest"], "sha256:" + hashlib.sha256(archive).hexdigest())):
        raise ValueError("Bootstrap artifact has wrong provenance, identity, size or digest")
    with zipfile.ZipFile(BytesIO(archive)) as zipped:
        entries = zipped.infolist()
        if (len(entries) != 1 or entries[0].filename != "bundle.json" or entries[0].is_dir()
                or not 0 < entries[0].file_size <= MAX_BLOB or entries[0].flag_bits & 1):
            raise ValueError("Bootstrap archive is not one bounded bundle")
        body = zipped.read(entries[0])
    if len(body) > MAX_BLOB:
        raise ValueError("Bootstrap bundle exceeds its budget")
    value = json.loads(body)
    if not isinstance(value, dict) or value.get("producer_job") != PRODUCER_JOBS[role]:
        raise ValueError("Bootstrap bundle has an unexpected producer job")
    return value


class Rendezvous:
    def __init__(self, context, role, *, clock=time.time):
        self.context = checked_context(context)
        if role not in ROLES:
            raise ValueError("Invalid rendezvous role")
        self.role, self.partner_role = role, next(iter(ROLES - {role}))
        self.clock = clock
        self._private = X25519PrivateKey.generate()
        self._public = self._private.public_key().public_bytes_raw()
        self._created = int(clock())
        self._partner = None
        self._sent, self._received = set(), set()

    def __repr__(self):
        return f"<Rendezvous role={self.role} closed={self._private is None}>"

    def _live(self):
        if self._private is None or not self._created <= self.clock() < self._created + KEY_TTL:
            raise ValueError("Bootstrap context is closed or expired")

    def public_manifest(self):
        self._live()
        return {"v": 1, "context": dict(self.context), "role": self.role, "producer_job": PRODUCER_JOBS[self.role],
                "public_key": encoded(self._public),
                "created_at": self._created, "expires_at": self._created + KEY_TTL}

    def bind_partner(self, value):
        """Call only after verify_artifact authenticates the partner key artifact."""
        self._live()
        if (not isinstance(value, dict) or set(value) != {"v", "context", "role", "producer_job", "public_key", "created_at", "expires_at"}
                or type(value.get("v")) is not int or value["v"] != 1 or value.get("context") != self.context
                or value.get("role") != self.partner_role or type(value.get("created_at")) is not int
                or value.get("producer_job") != PRODUCER_JOBS[self.partner_role]
                or type(value.get("expires_at")) is not int or value["expires_at"] != value["created_at"] + KEY_TTL
                or value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock()):
            raise ValueError("Partner key has wrong source/run/role or expiry")
        decode_bytes(value["public_key"], 32)
        if self._partner is not None and self._partner != value:
            raise ValueError("An authenticated partner key cannot be replaced")
        self._partner = dict(value)

    def _key(self, phase, sender):
        self._live()
        if self._partner is None or self._partner["expires_at"] <= self.clock():
            raise ValueError("A live authenticated partner key is required")
        shared = self._private.exchange(X25519PublicKey.from_public_bytes(decode_bytes(self._partner["public_key"], 32)))
        keys = {self.role: encoded(self._public), self.partner_role: self._partner["public_key"]}
        info = DOMAIN + canonical({"context": self.context, "phase": phase, "sender": sender, "public_keys": keys})
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=hashlib.sha256(DOMAIN + canonical(self.context)).digest(),
                    info=info).derive(shared)

    def seal(self, phase, payload):
        if phase not in PHASES or phase in self._sent:
            raise ValueError("Each bounded setup phase can be published once")
        checked_payload(phase, payload)
        created = int(self.clock())
        header = {"v": 1, "context": self.context, "phase": phase, "sender": self.role,
                  "producer_job": PRODUCER_JOBS[self.role],
                  "recipient": self.partner_role, "created_at": created, "expires_at": created + MESSAGE_TTL,
                  "nonce": encoded(os.urandom(12))}
        ciphertext = AESGCM(self._key(phase, self.role)).encrypt(decode_bytes(header["nonce"], 12), canonical(payload), DOMAIN + canonical(header))
        result = {**header, "ciphertext": encoded(ciphertext)}
        if len(canonical(result)) > MAX_BLOB:
            raise ValueError("Sealed setup bundle exceeds its budget")
        self._sent.add(phase)
        return result

    def open(self, phase, value):
        self._live()
        if phase not in PHASES or phase in self._received:
            raise ValueError("Each bounded setup phase can be consumed once")
        if (not isinstance(value, dict) or len(canonical(value)) > MAX_BLOB
                or set(value) != {"v", "context", "phase", "sender", "recipient", "producer_job", "created_at", "expires_at", "nonce", "ciphertext"}
                or type(value.get("v")) is not int or value["v"] != 1 or value.get("context") != self.context
                or value.get("phase") != phase or value.get("sender") != self.partner_role
                or value.get("recipient") != self.role or type(value.get("created_at")) is not int
                or value.get("producer_job") != PRODUCER_JOBS[self.partner_role]
                or type(value.get("expires_at")) is not int or value["expires_at"] != value["created_at"] + MESSAGE_TTL
                or value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock()):
            raise ValueError("Setup bundle has wrong source/run/phase/role or expiry")
        header = {key: item for key, item in value.items() if key != "ciphertext"}
        plaintext = AESGCM(self._key(phase, self.partner_role)).decrypt(decode_bytes(value["nonce"], 12), decode_bytes(value["ciphertext"]),
                                                     DOMAIN + canonical(header))
        result = checked_payload(phase, json.loads(plaintext))
        self._received.add(phase)
        return result

    def close(self):
        self._private = self._partner = None
        self._sent.clear()
        self._received.clear()
