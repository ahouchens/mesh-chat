"""Crypto-real, HTTP-mocked qualification control; no production rooms are used."""

import io
import json
from pathlib import Path
import sys
import time
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from mesh_chat import signal_mailbox as mailbox
from mesh_chat.signal_crypto import decode, encode, seal
from native_interop_negative_control import NegativeControlMailbox, new_capability
from native_interop_rendezvous import Rendezvous, checked_payload


BASE = "https://signal.example.workers.dev"
CONTEXT = {"repository": "example/mesh", "repository_id": 123, "run_id": 456,
           "run_attempt": 2, "source_commit": "a" * 40}


class Response:
    def __init__(self, body=b"", status=200):
        self.body, self.status = body, status

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Host:
    def __init__(self):
        self.documents = {}
        self.requests = []
        self.failure = None
        self.advance = None

    def open(self, request):
        self.requests.append(request)
        if self.advance is not None:
            self.advance()
        if self.failure is not None:
            raise self.failure
        if request.get_method() == "PUT":
            self.documents[request.full_url] = request.data
            return Response(b'{"expires_in":600}', 201)
        if request.full_url not in self.documents:
            raise urllib.error.HTTPError(request.full_url, 404, "absent", {}, io.BytesIO())
        return Response(self.documents[request.full_url])


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, duration):
        assert 0 < duration <= 0.6
        self.now += duration


@pytest.fixture
def peers(monkeypatch):
    mailbox._cooldowns.clear()
    host, clock = Host(), Clock()
    monkeypatch.setattr(mailbox, "_open", host.open)
    capability = new_capability(BASE)
    pair = mailbox.parse_pairing(capability, BASE)
    windows = NegativeControlMailbox(CONTEXT, "windows", "impaired", capability,
                                     base=BASE, clock=clock, sleep=clock.sleep)
    android = NegativeControlMailbox(CONTEXT, "android", "impaired", capability,
                                     base=BASE, clock=clock, sleep=clock.sleep)
    yield host, clock, pair, windows, android
    mailbox._cooldowns.clear()


def control(pair, *, stage="armed", scenario="impaired", context=CONTEXT,
            sender="windows", recipient="android", room_nonce=None, extra=None):
    value = {"v": 1, "context": dict(context), "scenario": scenario,
             "sender": sender, "recipient": recipient, "stage": stage,
             "room_nonce": room_nonce or pair["session"]}
    return {**value, **(extra or {})}


def inject(host, pair, value, *, slot="offer"):
    url = f"{BASE}/v2/signal/{pair['session']}/{slot}"
    raw = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    host.documents[url] = seal(raw, pair["secret"], pair["session"], slot)


@pytest.mark.parametrize("scenario", ["turn_tcp", "turn_tls", "impaired"])
def test_sealed_capability_phase_and_crypto_real_control_roundtrip(peers, scenario):
    host, clock, pair, windows, android = peers
    phase = "negative_control_" + scenario
    assert checked_payload(phase, {"capability": new_capability(BASE)})
    sender = Rendezvous(CONTEXT, "android")
    receiver = Rendezvous(CONTEXT, "windows")
    sender.bind_partner(receiver.public_manifest())
    receiver.bind_partner(sender.public_manifest())
    assert receiver.open(phase, sender.seal(phase, {"capability": new_capability(BASE)}))["capability"].startswith("MESHPAIR2.")
    assert windows.send("armed") is True
    assert android.receive("armed", deadline=clock.now + 4) is True
    assert android.send("ready") is True
    assert windows.receive("ready", deadline=clock.now + 4) is True
    assert windows.send("checked") is True
    assert android.receive("checked", deadline=clock.now + 4) is True
    assert len(host.documents) == 2
    for request in host.requests:
        if request.get_method() == "PUT":
            assert CONTEXT["source_commit"].encode() not in request.data
            assert pair["secret"].encode() not in request.data
        assert pair["secret"] not in request.full_url


def test_checked_poll_tolerates_only_prior_valid_armed(peers):
    host, clock, pair, windows, android = peers
    windows.send("armed")
    android.receive("armed", deadline=clock.now + 3)
    android.send("ready")
    windows.receive("ready", deadline=clock.now + 3)
    original_sleep = clock.sleep
    def after_first_poll(duration):
        original_sleep(duration)
        windows.send("checked")
    android.sleep = after_first_poll
    assert android.receive("checked", deadline=clock.now + 3) is True


def test_checked_poll_rejects_foreign_prior_armed(peers):
    host, clock, pair, windows, android = peers
    windows.send("armed")
    android.receive("armed", deadline=clock.now + 3)
    android.send("ready")
    inject(host, pair, control(pair, context={**CONTEXT, "run_attempt": 99}))
    with pytest.raises(ValueError):
        android.receive("checked", deadline=clock.now + 3)


@pytest.mark.parametrize("change", [
    {"context": {**CONTEXT, "repository": "foreign/mesh"}},
    {"context": {**CONTEXT, "repository_id": 124}},
    {"context": {**CONTEXT, "run_id": 457}},
    {"context": {**CONTEXT, "run_attempt": 3}},
    {"context": {**CONTEXT, "source_commit": "b" * 40}},
    {"scenario": "turn_tls"}, {"sender": "android"}, {"recipient": "windows"},
    {"room_nonce": "other-room"}, {"stage": "checked"}, {"unexpected": True},
])
def test_foreign_scope_future_stage_and_extra_fields_fail_closed(peers, change):
    host, clock, pair, windows, android = peers
    inject(host, pair, {**control(pair), **change})
    with pytest.raises(ValueError):
        android.receive("armed", deadline=clock.now + 3)


@pytest.mark.parametrize("raw", ["not-json", "[]", "{\"v\":1,\"v\":1}", "x" * 3000])
def test_malformed_duplicate_or_oversized_document_fails(peers, raw):
    host, clock, pair, windows, android = peers
    inject(host, pair, raw)
    with pytest.raises(ValueError):
        android.receive("armed", deadline=clock.now + 3)


def test_replay_and_local_order_fail_closed(peers):
    host, clock, pair, windows, android = peers
    with pytest.raises(ValueError):
        android.send("ready")
    with pytest.raises(ValueError):
        windows.send("checked")
    windows.send("armed")
    assert android.receive("armed", deadline=clock.now + 3) is True
    with pytest.raises(ValueError):
        android.receive("armed", deadline=clock.now + 3)
    android.send("ready")
    assert windows.receive("ready", deadline=clock.now + 3) is True
    with pytest.raises(ValueError):
        android.receive("checked", deadline=clock.now + 1)
    windows.send("checked")
    assert android.receive("checked", deadline=clock.now + 3) is True
    with pytest.raises(ValueError):
        windows.send("checked")


def test_stale_capability_and_bad_artifact_payload_are_rejected(peers):
    host, clock, pair, windows, android = peers
    value = json.loads(decode(new_capability(BASE)[len("MESHPAIR2."):]))
    value["expires_at"] = int(time.time()) - 1
    stale = "MESHPAIR2." + encode(json.dumps(value).encode())
    with pytest.raises(ValueError):
        NegativeControlMailbox(CONTEXT, "windows", "impaired", stale, base=BASE)
    for payload in ({"capability": "not-a-code"}, {"capability": new_capability(BASE), "extra": 1},
                    {"capability": "MESHPAIR2." + "x" * 3000}):
        with pytest.raises(ValueError):
            checked_payload("negative_control_impaired", payload)


@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError(BASE, 429, "rate limited", {"Retry-After": "60"}, io.BytesIO()),
    TimeoutError("PRIVATE_RAW_SECRET"),
])
def test_http_failure_is_sanitized_and_failed_publish_is_not_retried(peers, failure):
    host, clock, pair, windows, android = peers
    host.failure = failure
    with pytest.raises(ValueError) as caught:
        windows.send("armed")
    assert pair["secret"] not in str(caught.value)
    assert "PRIVATE_RAW_SECRET" not in str(caught.value)
    before = len(host.requests)
    with pytest.raises(ValueError):
        windows.send("armed")
    assert len(host.requests) == before
    with pytest.raises(ValueError) as caught:
        android.receive("armed", deadline=clock.now + 3)
    assert "PRIVATE_RAW_SECRET" not in str(caught.value)


def test_receive_finite_deadline_and_post_http_deadline_check(peers):
    host, clock, pair, windows, android = peers
    with pytest.raises(ValueError):
        android.receive("armed", deadline=float("inf"))
    with pytest.raises(ValueError):
        android.receive("armed", deadline=clock.now)
    inject(host, pair, control(pair))
    host.advance = lambda: setattr(clock, "now", clock.now + 5)
    with pytest.raises(ValueError):
        android.receive("armed", deadline=clock.now + 1)
