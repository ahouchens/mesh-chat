"""Sealed setup exchange for one installed public Core pair in one CI run.

Only the pairing code and fixed control acknowledgments cross this channel.
Product messages, receipts, private keys and raw profiles stay with the peers.
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


JOBS = {"windows": "windows_public", "android": "android_public"}
SENDERS = {"offer_code": {"windows"}, "invitation_accepted": {"android"},
           "approved": {"windows"}, "ready": set(JOBS), "done": set(JOBS),
           "owner_stopped": {"windows"}, "android_continuous": {"android"},
           "owner_reopened": {"windows"}, "restart_ready": set(JOBS), "restart_done": set(JOBS)}
PHASES = frozenset(SENDERS)
DOMAIN = b"public-core-pair:v1:"
KEY_TTL = 1800
MESSAGE_TTL = 600
MAX_BLOB = 32 * 1024
MAX_ARCHIVE = 64 * 1024
MAX_CODE = 2048


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def pair_id_for(fields):
    return hashlib.sha256(DOMAIN + canonical(fields)).hexdigest()[:32]


def checked_context(value):
    fields = {"repository", "repository_id", "run_id", "run_attempt", "source_commit", "pair_id"}
    if (type(value) is not dict or set(value) != fields
            or type(value["repository"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]) is None
            or any(part in {".", ".."} for part in value["repository"].split("/"))
            or any(type(value[key]) is not int or value[key] <= 0
                   for key in ("repository_id", "run_id", "run_attempt"))
            or type(value["source_commit"]) is not str
            or re.fullmatch(r"[a-f0-9]{40}", value["source_commit"]) is None
            or type(value["pair_id"]) is not str
            or value["pair_id"] != pair_id_for({key: value[key] for key in fields - {"pair_id"}})):
        raise ValueError("Invalid same-run public pair context")
    return dict(value)


def context_from_environment(environment=os.environ):
    try:
        fields = {"repository": environment["GITHUB_REPOSITORY"],
                  "repository_id": int(environment["GITHUB_REPOSITORY_ID"]),
                  "run_id": int(environment["GITHUB_RUN_ID"]),
                  "run_attempt": int(environment["GITHUB_RUN_ATTEMPT"]),
                  "source_commit": environment["GITHUB_SHA"]}
        return checked_context({**fields, "pair_id": pair_id_for(fields)})
    except (KeyError, ValueError) as error:
        raise ValueError("Authenticated public pair run context is unavailable") from error


def partner(role):
    if role not in JOBS:
        raise ValueError("Invalid public pair role")
    return "android" if role == "windows" else "windows"


def artifact_name(context, role, phase):
    checked_context(context)
    if role not in JOBS or phase not in PHASES | {"key"} or (phase != "key" and role not in SENDERS[phase]):
        raise ValueError("Invalid public pair role or phase")
    return (f"public-core-pair-v1-{context['run_id']}-{context['run_attempt']}-"
            f"{context['source_commit'][:12]}-{context['pair_id']}-{role}-{phase}")


def checked_payload(phase, value):
    if type(value) is not dict:
        raise ValueError("Public pair control payload must be an object")
    if phase == "offer_code":
        code = value.get("pairing_code")
        valid = (set(value) == {"pairing_code"} and type(code) is str
                 and 10 < len(code.encode("utf-8")) <= MAX_CODE
                 and re.fullmatch(r"MESHPAIR2\.[A-Za-z0-9_-]+", code) is not None)
    elif phase in PHASES - {"offer_code"}:
        valid = value == {}
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid public pair setup payload")
    return dict(value)


def encoded(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decoded(value, length=None):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("Invalid public pair encoding")
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if encoded(result) != value or (length is not None and len(result) != length):
        raise ValueError("Invalid public pair key or nonce length")
    return result


def validate_upload(context, role, phase, value):
    artifact_name(context, role, phase)
    common = {"v", "context", "producer_job", "created_at", "expires_at"}
    fields = common | ({"role", "public_key"} if phase == "key"
                       else {"phase", "sender", "recipient", "nonce", "ciphertext"})
    if (type(value) is not dict or set(value) != fields or len(canonical(value)) > MAX_BLOB
            or type(value["v"]) is not int or value["v"] != 1 or value["context"] != context
            or value["producer_job"] != JOBS[role]
            or type(value["created_at"]) is not int or type(value["expires_at"]) is not int
            or value["expires_at"] != value["created_at"] + (KEY_TTL if phase == "key" else MESSAGE_TTL)):
        raise ValueError("Only exact public keys and sealed setup may be uploaded")
    if phase == "key":
        if value["role"] != role:
            raise ValueError("Public pair key has wrong role")
        decoded(value["public_key"], 32)
    else:
        if value["phase"] != phase or value["sender"] != role or value["recipient"] != partner(role):
            raise ValueError("Public pair setup has wrong phase or role")
        decoded(value["nonce"], 12)
        if not 16 <= len(decoded(value["ciphertext"])) <= MAX_CODE + 1024:
            raise ValueError("Public pair ciphertext exceeds its budget")
    return value


def validated_artifact_metadata(metadata, context, role, phase):
    expected = artifact_name(context, role, phase)
    workflow = metadata.get("workflow_run") if type(metadata) is dict else None
    if (type(metadata) is not dict or metadata.get("name") != expected
            or metadata.get("expired") is not False or type(workflow) is not dict
            or type(workflow.get("id")) is not int or workflow["id"] != context["run_id"]
            or workflow.get("head_sha") != context["source_commit"]
            or type(workflow.get("repository_id")) is not int
            or workflow["repository_id"] != context["repository_id"]
            or type(metadata.get("id")) is not int or metadata["id"] <= 0
            or type(metadata.get("size_in_bytes")) is not int
            or not 0 < metadata["size_in_bytes"] <= MAX_ARCHIVE
            or type(metadata.get("digest")) is not str
            or re.fullmatch(r"sha256:[a-f0-9]{64}", metadata["digest"]) is None):
        raise ValueError("Public pair artifact provenance is invalid")
    return (metadata["id"], metadata["name"], metadata["size_in_bytes"], metadata["digest"])


def verify_artifact(metadata, archive, context, role, phase):
    validated_artifact_metadata(metadata, context, role, phase)
    if (type(archive) is not bytes or not 0 < len(archive) <= MAX_ARCHIVE
            or len(archive) != metadata["size_in_bytes"]
            or not hmac.compare_digest(metadata["digest"], "sha256:" + hashlib.sha256(archive).hexdigest())):
        raise ValueError("Public pair artifact digest is invalid")
    with zipfile.ZipFile(BytesIO(archive)) as zipped:
        entries = zipped.infolist()
        if (len(entries) != 1 or entries[0].filename != "bundle.json" or entries[0].is_dir()
                or not 0 < entries[0].file_size <= MAX_BLOB or entries[0].flag_bits & 1):
            raise ValueError("Public pair archive is not one bounded bundle")
        body = zipped.read(entries[0])
    if len(body) > MAX_BLOB:
        raise ValueError("Public pair bundle exceeds its budget")
    value = json.loads(body)
    validate_upload(context, role, phase, value)
    return value


class Rendezvous:
    def __init__(self, context, role, *, clock=time.time):
        self.context = checked_context(context)
        self.partner_role = partner(role)
        self.role, self.clock = role, clock
        self._private = X25519PrivateKey.generate()
        self._public = self._private.public_key().public_bytes_raw()
        self._created = int(clock())
        self._partner = None
        self._sent, self._received = set(), set()

    def _live(self):
        if self._private is None or not self._created <= self.clock() < self._created + KEY_TTL:
            raise ValueError("Public pair rendezvous is closed or expired")

    def public_manifest(self):
        self._live()
        return {"v": 1, "context": dict(self.context), "role": self.role,
                "producer_job": JOBS[self.role], "public_key": encoded(self._public),
                "created_at": self._created, "expires_at": self._created + KEY_TTL}

    def bind_partner(self, value):
        self._live()
        if (type(value) is not dict or set(value) != {"v", "context", "role", "producer_job",
                                                   "public_key", "created_at", "expires_at"}
                or type(value["v"]) is not int or value["v"] != 1
                or value["context"] != self.context or value["role"] != self.partner_role
                or value["producer_job"] != JOBS[self.partner_role]
                or type(value["created_at"]) is not int or type(value["expires_at"]) is not int
                or value["expires_at"] != value["created_at"] + KEY_TTL
                or value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock()):
            raise ValueError("Partner public key has wrong context or expiry")
        decoded(value["public_key"], 32)
        if self._partner is not None and self._partner != value:
            raise ValueError("Authenticated partner key cannot change")
        self._partner = dict(value)

    def _key(self, phase, sender):
        self._live()
        if self._partner is None or self._partner["expires_at"] <= self.clock():
            raise ValueError("Live partner public key is required")
        shared = self._private.exchange(X25519PublicKey.from_public_bytes(decoded(self._partner["public_key"], 32)))
        keys = {self.role: encoded(self._public), self.partner_role: self._partner["public_key"]}
        info = DOMAIN + canonical({"context": self.context, "phase": phase,
                                   "sender": sender, "public_keys": keys})
        return HKDF(algorithm=hashes.SHA256(), length=32,
                    salt=hashlib.sha256(DOMAIN + canonical(self.context)).digest(), info=info).derive(shared)

    def seal(self, phase, payload):
        if phase not in PHASES or self.role not in SENDERS[phase] or phase in self._sent:
            raise ValueError("Public pair setup phase cannot be sent")
        checked_payload(phase, payload)
        created = int(self.clock())
        header = {"v": 1, "context": dict(self.context), "phase": phase, "sender": self.role,
                  "producer_job": JOBS[self.role], "recipient": self.partner_role,
                  "created_at": created, "expires_at": created + MESSAGE_TTL,
                  "nonce": encoded(os.urandom(12))}
        ciphertext = AESGCM(self._key(phase, self.role)).encrypt(
            decoded(header["nonce"], 12), canonical(payload), DOMAIN + canonical(header))
        value = {**header, "ciphertext": encoded(ciphertext)}
        validate_upload(self.context, self.role, phase, value)
        self._sent.add(phase)
        return value

    def open(self, phase, value):
        self._live()
        if phase not in PHASES or self.partner_role not in SENDERS[phase] or phase in self._received:
            raise ValueError("Public pair setup phase cannot be received")
        validate_upload(self.context, self.partner_role, phase, value)
        if value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock():
            raise ValueError("Public pair setup has expired")
        header = {key: item for key, item in value.items() if key != "ciphertext"}
        plaintext = AESGCM(self._key(phase, self.partner_role)).decrypt(
            decoded(value["nonce"], 12), decoded(value["ciphertext"]), DOMAIN + canonical(header))
        payload = checked_payload(phase, json.loads(plaintext))
        self._received.add(phase)
        return payload

    def close(self):
        self._private = self._partner = None
        self._sent.clear()
        self._received.clear()
