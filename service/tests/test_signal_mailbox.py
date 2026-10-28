from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from mesh_chat.errors import MailboxRateLimited, MailboxUnauthorized, NetworkUnavailable, ValidationError
from mesh_chat import signal_mailbox as mailbox
from mesh_chat.signal_crypto import (MAX_DOCUMENT_BYTES, derive_key, encode, new_secret, seal, unseal)

BASE = "https://signal.example.workers.dev"
SESSION = "a" * 40
TOKEN = "t" * 43
SECRET = encode(bytes(range(32)))


class FakeResponse:
    def __init__(self, body=b"", status=200):
        self.body = body
        self.status = status
    def read(self, amount=-1):
        return self.body[:amount] if amount >= 0 else self.body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


@pytest.fixture(autouse=True)
def reset_cooldowns():
    mailbox._cooldowns.clear()
    yield
    mailbox._cooldowns.clear()


def http_error(status, headers=None):
    return urllib.error.HTTPError(BASE, status, "redacted", headers or {}, io.BytesIO(b""))


def test_encrypted_http_round_trip_leaves_no_plaintext_or_key_at_host():
    stored = {}
    document = json.dumps({"type": "webrtc_reconnect_offer", "sdp": "private-ip and ice-password", "signer": "identity"})
    def transport(request):
        assert request.full_url == f"{BASE}/v2/signal/{SESSION}/offer"
        assert request.get_header("X-mesh-token") == TOKEN
        assert request.get_header("User-agent") == mailbox.USER_AGENT
        assert SECRET not in str(request.header_items()) + request.full_url
        if request.get_method() == "PUT":
            stored["body"] = request.data
            assert all(value.encode() not in request.data for value in ("private-ip", "ice-password", "identity", SECRET))
            return FakeResponse(b'{"expires_in":600}', 201)
        return FakeResponse(stored["body"])
    with patch.object(mailbox, "_open", transport):
        result = mailbox.publish(BASE, document, "offer", token=TOKEN, session=SESSION, secret=SECRET)
        assert result["session_id"] == SESSION
        assert mailbox.fetch(BASE, SESSION, "offer", token=TOKEN, secret=SECRET)["document"] == document


def test_crypto_context_tamper_and_no_plaintext_downgrade():
    raw = seal("signed-document", SECRET, SESSION, "offer")
    assert unseal(raw, SECRET, SESSION, "offer") == "signed-document"
    assert seal("signed-document", SECRET, SESSION, "offer") != raw
    for secret, session, role in [(new_secret(), SESSION, "offer"), (SECRET, "b"*40, "offer"), (SECRET, SESSION, "answer")]:
        with pytest.raises(ValidationError):
            unseal(raw, secret, session, role)
    altered = json.loads(raw)
    altered["ciphertext"] = ("A" if altered["ciphertext"][0] != "A" else "B") + altered["ciphertext"][1:]
    for invalid in [json.dumps(altered).encode(), b'{"v":1,"document":"plaintext"}', b'null', b'{"v":true,"ciphertext":"abc"}']:
        with pytest.raises(ValidationError):
            unseal(invalid, SECRET, SESSION, "offer")


def test_size_boundary_and_secret_validation():
    raw = seal("x" * MAX_DOCUMENT_BYTES, SECRET, SESSION, "request")
    assert len(unseal(raw, SECRET, SESSION, "request")) == MAX_DOCUMENT_BYTES
    with pytest.raises(ValidationError):
        seal("x" * (MAX_DOCUMENT_BYTES + 1), SECRET, SESSION, "request")
    for token, secret in [(None, SECRET), ("short", SECRET), (TOKEN, None), (TOKEN, "bad")]:
        with patch.object(mailbox, "_open") as opened, pytest.raises(ValidationError):
            mailbox.publish(BASE, "{}", "offer", token=token, session=SESSION, secret=secret)
        opened.assert_not_called()


def test_pending_and_redacted_http_errors():
    with patch.object(mailbox, "_open", side_effect=http_error(404)):
        assert mailbox.fetch(BASE, SESSION, "request", token=TOKEN, secret=SECRET, pending=True)["pending"]
        with pytest.raises(NetworkUnavailable):
            mailbox.fetch(BASE, SESSION, "request", token=TOKEN, secret=SECRET)
    for status, kind in [(401, MailboxUnauthorized), (403, MailboxUnauthorized), (500, NetworkUnavailable), (302, NetworkUnavailable)]:
        with patch.object(mailbox, "_open", side_effect=http_error(status)), pytest.raises(kind) as caught:
            mailbox.publish(BASE, "{}", "request", token=TOKEN, session=SESSION, secret=SECRET)
        assert TOKEN not in str(caught.value) and SECRET not in str(caught.value)


def test_retry_after_prevents_requests_until_cooldown_ends():
    with patch.object(mailbox.time, "monotonic", return_value=100), patch.object(mailbox, "_open", side_effect=http_error(429, {"Retry-After": "120"})) as opened:
        for _ in range(2):
            with pytest.raises(MailboxRateLimited):
                mailbox.fetch(BASE, SESSION, "request", token=TOKEN, secret=SECRET)
        assert opened.call_count == 1
    with patch.object(mailbox.time, "monotonic", return_value=221), patch.object(mailbox, "_open", return_value=FakeResponse(seal("{}", SECRET, SESSION, "request"))) as opened:
        mailbox.fetch(BASE, SESSION, "request", token=TOKEN, secret=SECRET)
        opened.assert_called_once()


def test_redirect_handler_never_forwards_capabilities():
    request = mailbox.urllib.request.Request(BASE, headers={"X-Mesh-Token": TOKEN})
    assert mailbox._NoRedirect().redirect_request(request, None, 302, "", {}, "https://other.example") is None


def test_pairing_expiry_schema_and_configured_host():
    with patch.object(mailbox.time, "time", return_value=1000):
        code = mailbox.create_pairing(BASE)
        parsed = mailbox.parse_pairing(code, BASE)
        assert parsed["secret"] != parsed["token"]
        assert parsed["expires_at"] == 1600
        with pytest.raises(ValidationError, match="same signaling mailbox"):
            mailbox.parse_pairing(code, "https://other.example")
        with pytest.raises(ValidationError):
            mailbox.parse_pairing("legacy-session-0123456789", BASE)
    with patch.object(mailbox.time, "time", return_value=1601), pytest.raises(ValidationError):
        mailbox.parse_pairing(code, BASE)


def test_derivation_vector_matches_rfc5869_reference():
    # Independent stdlib reference, not the library implementation under test.
    import hashlib
    import hmac
    salt = b"mesh-chat:signal:v2"
    context = b'["mesh-chat:signal:v2","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","offer"]'
    prk = hmac.new(salt, bytes(range(32)), hashlib.sha256).digest()
    first = hmac.new(prk, context + bytes([1]), hashlib.sha256).digest()
    second = hmac.new(prk, first + context + bytes([2]), hashlib.sha256).digest()
    assert derive_key(SECRET, SESSION, "offer") == first + second
    with patch("os.urandom", return_value=bytes(range(16))):
        vector = json.loads(seal("mesh-chat signaling vector", SECRET, SESSION, "offer"))
    assert vector["ciphertext"] == "AAECAwQFBgcICQoLDA0ODwhO9MYGHUzAqsG7rMbbDMyAEmTI7Ph1Z8Hq8q1euHYuXYcg8UH7RmaGppOoaA_UeKZ-gw2WqFXz2_kDIASwIj0"


def test_mobile_internal_crypto_interoperates_with_desktop():
    import subprocess
    import sys
    from pathlib import Path
    raw = seal("desktop to mobile", SECRET, SESSION, "offer")
    script = f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})\n" + '''
import importlib.util, json, sys
original = importlib.util.find_spec
importlib.util.find_spec = lambda name, *args, **kwargs: None if name == "cryptography" else original(name, *args, **kwargs)
from mesh_chat.signal_crypto import seal, unseal
from RNS.Cryptography import Provider
value = json.load(sys.stdin)
print(json.dumps({"provider": Provider.backend(),
    "document": unseal(value["envelope"].encode(), value["secret"], value["session"], "offer"),
    "envelope": seal("mobile to desktop", value["secret"], value["session"], "answer").decode()}))
'''
    result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True, check=True, timeout=30,
                            input=json.dumps({"envelope": raw.decode(), "secret": SECRET, "session": SESSION}))
    value = json.loads(result.stdout)
    assert value["provider"] == "internal"
    assert value["document"] == "desktop to mobile"
    assert unseal(value["envelope"].encode(), SECRET, SESSION, "answer") == "mobile to desktop"
