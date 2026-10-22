from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - mobile fallbacks
    certifi = None

from .call_settings import validate_broker_url
from .errors import (
    MailboxRateLimited,
    MailboxUnauthorized,
    NetworkUnavailable,
    ValidationError,
)

MAX_DOCUMENT_BYTES = 48 * 1024
SESSION = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,160}$")
ROLES = {"request", "offer", "answer"}


def _context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()


def _token(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValidationError("Signaling mailbox token is invalid")
    return value


def _endpoint(base: str, session: str, role: str) -> str:
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        raise ValidationError("Signaling session is invalid")
    if role not in ROLES:
        raise ValidationError("Signaling role is invalid")
    return f"{validate_broker_url(base).rstrip('/')}/signal/{session}/{role}"


def _document_session(document: str) -> str:
    try:
        value = json.loads(document)
        return value["session_id"]
    except Exception as exc:
        raise ValidationError("Signaling document is invalid") from exc


def publish(
    base: str,
    document: str,
    role: str,
    *,
    token: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    if not isinstance(document, str):
        raise ValidationError("Signaling document is invalid")
    if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Signaling document is too large")
    target = _document_session(document) if session is None else session
    token = _token(token)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token is not None:
        # Sent as a capability header. Never include the token in an error,
        # diagnostic, or log line.
        headers["X-Mesh-Token"] = token
    request = urllib.request.Request(
        _endpoint(base, target, role),
        data=document.encode("utf-8"),
        method="PUT",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=10, context=_context()) as response:
            if response.status not in {200, 201}:
                raise NetworkUnavailable("Signaling mailbox rejected the document")
            body = response.read(4096)
    except (MailboxUnauthorized, MailboxRateLimited, NetworkUnavailable):
        raise
    except urllib.error.HTTPError as exc:
        raise _http_error(exc.code) from exc
    except Exception as exc:
        raise NetworkUnavailable("Signaling mailbox is unavailable") from exc
    rotated = False
    if body:
        try:
            rotated = bool(json.loads(body).get("rotated"))
        except Exception:
            rotated = False
    return {
        "session_id": target,
        "role": role,
        "expires_in": 600,
        "rotated": rotated,
    }


def fetch(
    base: str,
    session: str,
    role: str,
    *,
    token: str | None = None,
    pending: bool = False,
) -> dict[str, Any]:
    token = _token(token)
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["X-Mesh-Token"] = token
    request = urllib.request.Request(_endpoint(base, session, role), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10, context=_context()) as response:
            body = response.read(MAX_DOCUMENT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if pending and exc.code == 404:
            return {"session_id": session, "role": role, "document": None, "pending": True}
        raise _http_error(exc.code) from exc
    except Exception as exc:
        raise NetworkUnavailable("Signaling document is unavailable") from exc
    if len(body) > MAX_DOCUMENT_BYTES:
        raise NetworkUnavailable("Signaling document is too large")
    try:
        value = json.loads(body)
        document = value["document"]
    except Exception as exc:
        raise NetworkUnavailable("Signaling mailbox returned an invalid document") from exc
    if not isinstance(document, str):
        raise NetworkUnavailable("Signaling mailbox returned an invalid document")
    return {"session_id": session, "role": role, "document": document}


def _http_error(status: int) -> Exception:
    if status in {401, 403}:
        return MailboxUnauthorized("Signaling capability was rejected")
    if status == 429:
        return MailboxRateLimited("Signaling mailbox is rate limited")
    if status == 404:
        return NetworkUnavailable("Signaling document is unavailable")
    return NetworkUnavailable("Signaling mailbox is unavailable")
