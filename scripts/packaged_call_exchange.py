"""One-run sealed setup exchange for installed GUI and public SDK call peer.

Only a pairing code and fixed phase acknowledgments cross Actions artifacts.
Call SDP, media, message text, credentials and receipts remain on the runners.
"""

import base64
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


DOMAIN = b"packaged-call:v1:"
JOBS = {"gui": "call_gui", "peer": "call_peer"}
SENDERS = {
    "offer_code": {"peer"}, "invitation_accepted": {"gui"}, "approved": {"peer"},
    "ready": {"gui", "peer"}, "precall_gui_sent": {"gui"},
    "precall_peer_sent": {"peer"}, "call_started": {"gui"},
    "call_active": {"gui", "peer"}, "during_peer_sent": {"peer"},
    "call_hungup": {"gui"}, "postcall_gui_sent": {"gui"},
    "postcall_peer_sent": {"peer"}, "done": {"gui", "peer"},
}
MAX_BLOB = 32 * 1024
MAX_ARCHIVE = 64 * 1024
KEY_SECONDS = 1800
PHASE_SECONDS = 600
API = "https://api.github.com"
UPLOAD = Path(__file__).resolve().parent / "native-interop-artifact/packaged-call-upload.mjs"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def pair_id(fields):
    return hashlib.sha256(DOMAIN + canonical(fields)).hexdigest()[:32]


def context_from_environment(env=os.environ):
    fields = {"repository": env["GITHUB_REPOSITORY"],
              "repository_id": int(env["GITHUB_REPOSITORY_ID"]),
              "run_id": int(env["GITHUB_RUN_ID"]),
              "run_attempt": int(env["GITHUB_RUN_ATTEMPT"]),
              "source_commit": env["GITHUB_SHA"],
              "source_tree": env["PACKAGED_CALL_TREE"]}
    context = {**fields, "pair_id": pair_id(fields)}
    return checked_context(context)


def checked_context(value):
    keys = {"repository", "repository_id", "run_id", "run_attempt",
            "source_commit", "source_tree", "pair_id"}
    if (type(value) is not dict or set(value) != keys
            or type(value["repository"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]) is None
            or any(part in {".", ".."} for part in value["repository"].split("/"))
            or any(type(value[key]) is not int or value[key] <= 0
                   for key in ("repository_id", "run_id", "run_attempt"))
            or any(type(value[key]) is not str or re.fullmatch(r"[a-f0-9]{40}", value[key]) is None
                   for key in ("source_commit", "source_tree"))
            or value["pair_id"] != pair_id({key: value[key] for key in keys - {"pair_id"}})):
        raise ValueError("call_context_invalid")
    return value


def partner(role):
    if role not in JOBS: raise ValueError("call_role_invalid")
    return "peer" if role == "gui" else "gui"


def artifact_name(context, role, phase):
    checked_context(context)
    if role not in JOBS or (phase != "key" and (phase not in SENDERS or role not in SENDERS[phase])):
        raise ValueError("call_artifact_identity_invalid")
    return (f"packaged-call-v1-{context['run_id']}-{context['run_attempt']}-"
            f"{context['source_commit'][:12]}-{context['pair_id']}-{role}-{phase}")


def encoded(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decoded(value, size=None):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("call_encoding_invalid")
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if encoded(raw) != value or (size is not None and len(raw) != size):
        raise ValueError("call_encoding_invalid")
    return raw


def checked_payload(phase, value):
    if type(value) is not dict: raise ValueError("call_payload_invalid")
    if phase == "offer_code":
        code = value.get("pairing_code")
        if (set(value) != {"pairing_code"} or type(code) is not str
                or not 10 < len(code.encode("utf-8")) <= 2048
                or re.fullmatch(r"MESHPAIR2\.[A-Za-z0-9_-]+", code) is None):
            raise ValueError("call_pairing_code_invalid")
    elif phase not in SENDERS or value != {}:
        raise ValueError("call_payload_invalid")
    return value


def checked_bundle(context, role, phase, value):
    artifact_name(context, role, phase)
    common = {"v", "context", "producer_job", "created_at", "expires_at"}
    fields = common | ({"role", "public_key"} if phase == "key"
                       else {"phase", "sender", "recipient", "nonce", "ciphertext"})
    if (type(value) is not dict or set(value) != fields or len(canonical(value)) > MAX_BLOB
            or value["v"] != 1 or value["context"] != context
            or value["producer_job"] != JOBS[role]
            or type(value["created_at"]) is not int or type(value["expires_at"]) is not int
            or value["expires_at"] != value["created_at"] + (KEY_SECONDS if phase == "key" else PHASE_SECONDS)):
        raise ValueError("call_bundle_invalid")
    if phase == "key":
        if value["role"] != role: raise ValueError("call_key_role_invalid")
        decoded(value["public_key"], 32)
    else:
        if value["phase"] != phase or value["sender"] != role or value["recipient"] != partner(role):
            raise ValueError("call_phase_role_invalid")
        decoded(value["nonce"], 12)
        if not 16 <= len(decoded(value["ciphertext"])) <= 3072:
            raise ValueError("call_ciphertext_invalid")
    return value


class SealedPhase:
    def __init__(self, context, role, clock=time.time):
        self.context = checked_context(context)
        self.role, self.other, self.clock = role, partner(role), clock
        self.private = X25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes_raw()
        self.created = int(clock())
        self.remote = None
        self.sent, self.received = set(), set()

    def live(self):
        if self.private is None or not self.created <= self.clock() < self.created + KEY_SECONDS:
            raise ValueError("call_key_expired")

    def manifest(self):
        self.live()
        return {"v": 1, "context": self.context, "producer_job": JOBS[self.role],
                "role": self.role, "public_key": encoded(self.public),
                "created_at": self.created, "expires_at": self.created + KEY_SECONDS}

    def bind(self, value):
        self.live()
        checked_bundle(self.context, self.other, "key", value)
        if (value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock()
                or self.remote is not None and self.remote != value):
            raise ValueError("call_partner_key_invalid")
        self.remote = value

    def key(self, phase, sender):
        self.live()
        if self.remote is None or self.remote["expires_at"] <= self.clock():
            raise ValueError("call_partner_key_missing")
        shared = self.private.exchange(X25519PublicKey.from_public_bytes(decoded(self.remote["public_key"], 32)))
        keys = {self.role: encoded(self.public), self.other: self.remote["public_key"]}
        info = DOMAIN + canonical({"context": self.context, "phase": phase, "sender": sender,
                                   "public_keys": keys})
        return HKDF(algorithm=hashes.SHA256(), length=32,
                    salt=hashlib.sha256(DOMAIN + canonical(self.context)).digest(), info=info).derive(shared)

    def seal(self, phase, payload):
        if phase not in SENDERS or self.role not in SENDERS[phase] or phase in self.sent:
            raise ValueError("call_phase_send_invalid")
        checked_payload(phase, payload)
        created = int(self.clock())
        header = {"v": 1, "context": self.context, "producer_job": JOBS[self.role],
                  "phase": phase, "sender": self.role, "recipient": self.other,
                  "created_at": created, "expires_at": created + PHASE_SECONDS,
                  "nonce": encoded(os.urandom(12))}
        value = {**header, "ciphertext": encoded(AESGCM(self.key(phase, self.role)).encrypt(
            decoded(header["nonce"], 12), canonical(payload), DOMAIN + canonical(header)))}
        checked_bundle(self.context, self.role, phase, value)
        self.sent.add(phase)
        return value

    def open(self, phase, value):
        if phase not in SENDERS or self.other not in SENDERS[phase] or phase in self.received:
            raise ValueError("call_phase_receive_invalid")
        checked_bundle(self.context, self.other, phase, value)
        if value["created_at"] > self.clock() + 30 or value["expires_at"] <= self.clock():
            raise ValueError("call_phase_expired")
        header = {key: item for key, item in value.items() if key != "ciphertext"}
        plain = AESGCM(self.key(phase, self.other)).decrypt(
            decoded(value["nonce"], 12), decoded(value["ciphertext"]),
            DOMAIN + canonical(header))
        result = checked_payload(phase, json.loads(plain))
        self.received.add(phase)
        return result

    def close(self):
        self.private = self.remote = None
        self.sent.clear()
        self.received.clear()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ArtifactUnavailable(ValueError):
    def __init__(self, status=None):
        super().__init__("call_artifact_unavailable")
        self.status = status


class Artifacts:
    def __init__(self, context, role, directory, node="node", env=os.environ, clock=time.monotonic):
        self.context = checked_context(context)
        if (role not in JOBS or env.get("GITHUB_JOB") != JOBS[role]
                or env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or context_from_environment(env) != context):
            raise ValueError("call_job_invalid")
        self.token = env.get("GITHUB_TOKEN")
        if not self.token: raise ValueError("call_token_missing")
        self.role, self.directory, self.node, self.clock = role, Path(directory), node, clock
        self.opener = urllib.request.build_opener(NoRedirect())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.published = set()

    def get(self, path, deadline, archive=False):
        if not path.startswith("/repos/" + self.context["repository"] + "/actions/"):
            raise ValueError("call_artifact_path")
        remaining = min(10, deadline - self.clock())
        if remaining <= 0: raise TimeoutError("call_artifact_deadline")
        request = urllib.request.Request(API + path, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "mesh-packaged-call/1"})
        try:
            try: response = self.opener.open(request, timeout=remaining)
            except urllib.error.HTTPError as error:
                if not archive or error.code != 302: raise ArtifactUnavailable(error.code) from None
                target = urllib.parse.urlsplit(error.headers.get("Location", ""))
                if target.scheme != "https" or not target.hostname or target.username or target.password or target.fragment:
                    raise ValueError("call_artifact_redirect") from None
                try: response = self.opener.open(urllib.request.Request(target.geturl()), timeout=remaining)
                except urllib.error.HTTPError as blob_error:
                    raise ArtifactUnavailable(blob_error.code) from None
            limit = MAX_ARCHIVE if archive else 512 * 1024
            result = queue.Queue(maxsize=1)
            def read_body():
                try:
                    with response: result.put_nowait((response.read(limit + 1), None))
                except Exception as error:
                    result.put_nowait((None, error))
            threading.Thread(target=read_body, daemon=True).start()
            try: data, error = result.get(timeout=max(0, deadline - self.clock()))
            except queue.Empty:
                threading.Thread(target=response.close, daemon=True).start()
                raise TimeoutError("call_artifact_body_deadline") from None
            if error is not None: raise error
            if self.clock() >= deadline or not 0 < len(data) <= limit: raise ValueError("call_artifact_body")
            return data if archive else json.loads(data)
        except ArtifactUnavailable:
            raise
        except Exception as error:
            raise ArtifactUnavailable() from error

    def publish(self, phase, value, deadline):
        name = artifact_name(self.context, self.role, phase)
        checked_bundle(self.context, self.role, phase, value)
        if phase in self.published or self.clock() >= deadline: raise ValueError("call_publish_invalid")
        with tempfile.TemporaryDirectory(prefix="packaged-call-upload-", dir=self.directory) as temporary:
            bundle = Path(temporary) / "bundle.json"
            identity = Path(temporary) / "identity.json"
            bundle.write_bytes(canonical(value))
            process = subprocess.run([self.node, str(UPLOAD), name, str(bundle), str(identity)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     timeout=min(60, deadline - self.clock()))
            if process.returncode or self.clock() >= deadline:
                raise ValueError("call_upload_failed")
            result = json.loads(identity.read_bytes())
            if (type(result) is not dict or result.get("passed") is not True
                    or type(result.get("id")) is not int or result["id"] <= 0
                    or type(result.get("size")) is not int or not 0 < result["size"] <= MAX_ARCHIVE):
                raise ValueError("call_upload_identity")
        self.published.add(phase)

    def wait(self, role, phase, deadline):
        name = artifact_name(self.context, role, phase)
        if role != partner(self.role): raise ValueError("call_partner_invalid")
        endpoint = f"/repos/{self.context['repository']}/actions/runs/{self.context['run_id']}"
        transient = 0
        pinned = None
        while self.clock() < deadline:
            try: inventory = self.get(endpoint + "/artifacts?per_page=100", deadline)
            except ArtifactUnavailable as error:
                if error.status != 503 or transient >= 2 or deadline - self.clock() <= 3:
                    raise
                transient += 1
                time.sleep(3)
                continue
            entries = inventory.get("artifacts") if type(inventory) is dict else None
            if (type(entries) is not list or len(entries) > 100
                    or type(inventory.get("total_count")) is not int
                    or inventory["total_count"] > 100):
                raise ValueError("call_artifact_inventory")
            matches = [row for row in entries if type(row) is dict and row.get("name") == name]
            if len(matches) > 1: raise ValueError("call_artifact_duplicate")
            if pinned is not None and not matches: raise ValueError("call_artifact_disappeared")
            if matches:
                row = matches[0]
                workflow = row.get("workflow_run")
                if (type(workflow) is not dict or workflow.get("id") != self.context["run_id"]
                        or workflow.get("head_sha") != self.context["source_commit"]
                        or workflow.get("repository_id") != self.context["repository_id"]
                        or row.get("expired") is not False or type(row.get("id")) is not int
                        or type(row.get("size_in_bytes")) is not int
                        or not 0 < row["size_in_bytes"] <= MAX_ARCHIVE
                        or type(row.get("digest")) is not str
                        or re.fullmatch(r"sha256:[a-f0-9]{64}", row["digest"]) is None):
                    raise ValueError("call_artifact_provenance")
                identity = (row["id"], row["name"], row["size_in_bytes"], row["digest"])
                if pinned is not None and identity != pinned:
                    raise ValueError("call_artifact_changed")
                try:
                    raw = self.get(f"/repos/{self.context['repository']}/actions/artifacts/{row['id']}/zip",
                                   deadline, archive=True)
                except ArtifactUnavailable as error:
                    if error.status not in {404, 503} or transient >= 2 or deadline - self.clock() <= 3:
                        raise
                    pinned = identity
                    transient += 1
                    time.sleep(3)
                    continue
                if (len(raw) != row["size_in_bytes"] or not hmac.compare_digest(
                        row["digest"], "sha256:" + hashlib.sha256(raw).hexdigest())):
                    raise ValueError("call_artifact_digest")
                with zipfile.ZipFile(BytesIO(raw)) as zipped:
                    members = zipped.infolist()
                    if (len(members) != 1 or members[0].filename != "bundle.json"
                            or members[0].is_dir() or not 0 < members[0].file_size <= MAX_BLOB
                            or members[0].flag_bits & 1):
                        raise ValueError("call_artifact_archive")
                    value = json.loads(zipped.read(members[0]))
                return checked_bundle(self.context, role, phase, value)
            time.sleep(min(3, max(0, deadline - self.clock())))
        raise TimeoutError("call_partner_deadline")

    def close(self):
        self.token = None


class Exchange:
    def __init__(self, context, role, directory):
        self.sealed = SealedPhase(context, role)
        self.artifacts = Artifacts(context, role, directory)
        self.connected = False

    def connect(self, deadline):
        if self.connected: raise ValueError("call_exchange_connected")
        self.artifacts.publish("key", self.sealed.manifest(), deadline)
        self.sealed.bind(self.artifacts.wait(self.sealed.other, "key", deadline))
        self.connected = True

    def publish(self, phase, payload, deadline):
        if not self.connected: raise ValueError("call_exchange_unbound")
        self.artifacts.publish(phase, self.sealed.seal(phase, payload), deadline)

    def receive(self, phase, deadline):
        if not self.connected: raise ValueError("call_exchange_unbound")
        return self.sealed.open(phase, self.artifacts.wait(self.sealed.other, phase, deadline))

    def close(self):
        self.sealed.close()
        self.artifacts.close()
        self.connected = False
