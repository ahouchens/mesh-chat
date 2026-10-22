from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from mesh_chat.errors import (
    MailboxRateLimited,
    MailboxUnauthorized,
    NetworkUnavailable,
    ValidationError,
)
from mesh_chat.signal_mailbox import TOKEN, fetch, publish

BASE = "https://signal.example.workers.dev"
SESSION = "a" * 40
TOKEN_VALUE = "token-0123456789abcdefghijklmnop"


class FakeResponse:
    def __init__(self, body: dict | None = None, status: int = 201) -> None:
        self._body = b"" if body is None else json.dumps(body).encode("utf-8")
        self.status = status

    def read(self, amount: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(BASE, status, "error", {}, io.BytesIO(b""))


def test_publish_sends_the_capability_header_and_explicit_session() -> None:
    document = json.dumps({"type": "webrtc_reconnect_request", "v": 1})
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=10, context=None):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["method"] = request.get_method()
        return FakeResponse({"expires_in": 600}, 201)

    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen", fake_urlopen):
        result = publish(BASE, document, "request", token=TOKEN_VALUE, session=SESSION)

    assert captured["url"] == f"{BASE}/signal/{SESSION}/request"
    assert captured["headers"]["x-mesh-token"] == TOKEN_VALUE
    assert captured["method"] == "PUT"
    assert result["session_id"] == SESSION
    assert TOKEN_VALUE not in json.dumps(result)


def test_publish_derives_the_session_from_the_document_for_legacy_flows() -> None:
    document = json.dumps(
        {"type": "webrtc_onboarding_offer", "session_id": "onboarding-0123456789"}
    )
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=10, context=None):
        captured["url"] = request.full_url
        return FakeResponse({}, 201)

    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen", fake_urlopen):
        publish(BASE, document, "offer")
    assert captured["url"].endswith("/signal/onboarding-0123456789/offer")


def test_fetch_sends_the_token_and_reports_pending_documents() -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=10, context=None):
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return FakeResponse({"document": "{}"}, 200)

    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen", fake_urlopen):
        result = fetch(BASE, SESSION, "request", token=TOKEN_VALUE)
    assert captured["headers"]["x-mesh-token"] == TOKEN_VALUE
    assert result["document"] == "{}"

    def missing(request, timeout=10, context=None):
        raise _http_error(404)

    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen", missing):
        pending = fetch(BASE, SESSION, "request", token=TOKEN_VALUE, pending=True)
        assert pending["pending"] is True
        assert pending["document"] is None
        with pytest.raises(NetworkUnavailable):
            fetch(BASE, SESSION, "request", token=TOKEN_VALUE)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, MailboxUnauthorized),
        (403, MailboxUnauthorized),
        (429, MailboxRateLimited),
        (500, NetworkUnavailable),
    ],
)
def test_mailbox_statuses_map_to_redacted_errors(status: int, error: type[Exception]) -> None:
    def fake_urlopen(request, timeout=10, context=None):
        raise _http_error(status)

    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen", fake_urlopen):
        with pytest.raises(error) as caught:
            publish(BASE, "{}", "request", token=TOKEN_VALUE, session=SESSION)
    assert TOKEN_VALUE not in str(caught.value)


@pytest.mark.parametrize("token", ["short", "bad token with spaces", "x" * 161, 42])
def test_invalid_tokens_are_rejected_before_any_request(token: object) -> None:
    with patch("mesh_chat.signal_mailbox.urllib.request.urlopen") as opened:
        with pytest.raises(ValidationError):
            publish(BASE, "{}", "request", token=token, session=SESSION)  # type: ignore[arg-type]
        opened.assert_not_called()


def test_roles_and_sessions_are_validated() -> None:
    with pytest.raises(ValidationError):
        publish(BASE, "{}", "bogus", token=TOKEN_VALUE, session=SESSION)
    with pytest.raises(ValidationError):
        fetch(BASE, "short", "request", token=TOKEN_VALUE)
    assert TOKEN.fullmatch(TOKEN_VALUE)
