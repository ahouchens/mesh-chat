from __future__ import annotations

import json
import re
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

try:
    import certifi
except ImportError:  # pragma: no cover - mobile fallbacks
    certifi = None

from .call_settings import validate_mailbox_url
from .errors import MailboxRateLimited, MailboxUnauthorized, NetworkUnavailable, ValidationError
from .signal_crypto import (MAX_DOCUMENT_BYTES, MAX_ENVELOPE_BYTES, SESSION, ROLES,
                            decode, encode, new_secret, seal, unseal, validate_secret)

TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,160}$")
PAIR_PREFIX = "MESHPAIR2."
USER_AGENT = "MeshChat-Signaling/2"
_cooldowns: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def _context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request):
    # Do not forward capabilities to redirects or change the global opener.
    return urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=_context())).open(request, timeout=10)


def validate_base(base: Any) -> str:
    return validate_mailbox_url(base)


def _token(value: Any) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValidationError("Encrypted signaling capability is missing or invalid")
    return value


def _endpoint(base: str, session: str, role: str) -> str:
    if not isinstance(session, str) or not SESSION.fullmatch(session) or not isinstance(role, str) or role not in ROLES:
        raise ValidationError("Signaling context is invalid")
    return f"{validate_base(base)}/v2/signal/{session}/{role}"


def _request(request):
    # Bounded process-local origin cooldowns contain no pair secrets or room IDs.
    origin = urlsplit(request.full_url).netloc
    with _cooldown_lock:
        now = time.monotonic()
        for key in list(_cooldowns):
            if _cooldowns[key] <= now:
                del _cooldowns[key]
        if _cooldowns.get(origin, 0) > now:
            raise MailboxRateLimited("Signaling mailbox is rate limited")
    try:
        return _open(request)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                delay = max(1, min(3600, int(exc.headers.get("Retry-After", "60"))))
            except (ValueError, TypeError):
                delay = 60
            with _cooldown_lock:
                if len(_cooldowns) >= 128:
                    _cooldowns.pop(next(iter(_cooldowns)))
                _cooldowns[origin] = time.monotonic() + delay
        raise


def publish(base: str, document: str, role: str, *, token: str | None = None,
            session: str | None = None, secret: str | None = None) -> dict[str, Any]:
    endpoint = _endpoint(base, session, role)
    token = _token(token)
    validate_secret(secret)
    payload = seal(document, secret, session, role)
    request = urllib.request.Request(endpoint, data=payload, method="PUT",
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Mesh-Token": token,
                 "User-Agent": USER_AGENT})
    try:
        with _request(request) as response:
            if response.status not in {200, 201}:
                raise NetworkUnavailable("Signaling mailbox rejected the document")
            response.read(4096)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc.code) from None
    except (MailboxRateLimited, NetworkUnavailable):
        raise
    except Exception:
        raise NetworkUnavailable("Signaling mailbox is unavailable") from None
    return {"session_id": session, "role": role, "expires_in": 600, "rotated": False}


def fetch(base: str, session: str, role: str, *, token: str | None = None,
          secret: str | None = None, pending: bool = False) -> dict[str, Any]:
    endpoint = _endpoint(base, session, role)
    token = _token(token)
    validate_secret(secret)
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json", "X-Mesh-Token": token,
                                                      "User-Agent": USER_AGENT})
    try:
        with _request(request) as response:
            body = response.read(MAX_ENVELOPE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if pending and exc.code == 404:
            return {"session_id": session, "role": role, "document": None, "pending": True}
        raise _http_error(exc.code) from None
    except MailboxRateLimited:
        raise
    except Exception:
        raise NetworkUnavailable("Signaling document is unavailable") from None
    document = unseal(body, secret, session, role)
    return {"session_id": session, "role": role, "document": document}


def create_pairing(base: str) -> str:
    value = {"v": 2, "url": validate_base(base), "session": secrets.token_urlsafe(24),
             "token": secrets.token_urlsafe(32), "secret": new_secret(), "expires_at": int(time.time()) + 600}
    return PAIR_PREFIX + encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def parse_pairing(code: Any, configured_base: str) -> dict[str, Any]:
    try:
        if not isinstance(code, str) or not code.startswith(PAIR_PREFIX) or len(code) > 2048:
            raise ValueError()
        value = json.loads(decode(code[len(PAIR_PREFIX):], maximum=2048))
        if not isinstance(value, dict) or set(value) != {"v", "url", "session", "token", "secret", "expires_at"}:
            raise ValueError()
        if type(value["v"]) is not int or value["v"] != 2:
            raise ValueError()
        if type(value["expires_at"]) is not int or not time.time() < value["expires_at"] <= time.time() + 900:
            raise ValueError()
        _endpoint(value["url"], value["session"], "offer")
        _token(value["token"])
        validate_secret(value["secret"])
    except Exception:
        raise ValidationError("Encrypted pairing code is invalid or expired; create a new invitation") from None
    if value["url"] != validate_base(configured_base):
        # Imported links cannot silently target arbitrary hosts/private networks.
        raise ValidationError("Set the same signaling mailbox on both devices before using this invitation")
    return value


def _http_error(status: int) -> Exception:
    if status in {401, 403}:
        return MailboxUnauthorized("Signaling capability was rejected")
    if status == 429:
        return MailboxRateLimited("Signaling mailbox is rate limited")
    return NetworkUnavailable("Signaling mailbox is unavailable")
