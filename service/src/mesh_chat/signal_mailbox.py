from __future__ import annotations

import json
import ssl
import urllib.request
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - mobile fallbacks
    certifi = None

from .call_settings import validate_broker_url
from .errors import NetworkUnavailable, ValidationError

MAX_DOCUMENT_BYTES = 48 * 1024
SESSION = __import__("re").compile(r"^[A-Za-z0-9_-]{16,80}$")
ROLES = {"offer", "answer"}


def _context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()


def _endpoint(base: str, session: str, role: str) -> str:
    if not isinstance(session, str) or not SESSION.fullmatch(session):
        raise ValidationError("Signaling session is invalid")
    if role not in ROLES:
        raise ValidationError("Signaling role is invalid")
    return f"{validate_broker_url(base).rstrip('/')}/signal/{session}/{role}"


def publish(base: str, document: str, role: str) -> dict[str, Any]:
    if not isinstance(document, str):
        raise ValidationError("Signaling document is invalid")
    if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Signaling document is too large")
    try:
        value = json.loads(document)
        session = value["session_id"]
    except Exception as exc:
        raise ValidationError("Signaling document is invalid") from exc
    request = urllib.request.Request(
        _endpoint(base, session, role),
        data=document.encode("utf-8"),
        method="PUT",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10, context=_context()) as response:
            if response.status not in {200, 201}:
                raise NetworkUnavailable("Signaling mailbox rejected the document")
    except NetworkUnavailable:
        raise
    except Exception as exc:
        raise NetworkUnavailable("Signaling mailbox is unavailable") from exc
    return {"session_id": session, "role": role, "expires_in": 600}


def fetch(base: str, session: str, role: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _endpoint(base, session, role),
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10, context=_context()) as response:
            body = response.read(MAX_DOCUMENT_BYTES + 1)
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
