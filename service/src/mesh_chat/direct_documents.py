"""Public email/file container for independently signed version-2 controls.

Parsing verifies the entire chain against the enclosed existing invitation.
It never accepts replay state, creates membership, or activates a native handle.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

from .direct_binding import BindingAuthority, _parse
from .direct_offer import OfferAuthority, verify_offer
from .direct_exchange import verify_answer, verify_ready
from .errors import ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import (verify_workspace_invitation, workspace_document_digest,
    find_device, _destination_for, _identity_from_public_key)

PREFIX = "mesh-direct:"
MAX_BYTES = 768 * 1024


@dataclass(frozen=True)
class ConnectionDocument:
    invitation: object
    offer: str
    offer_certificate: bytes
    answer: str | None
    answer_certificate: bytes | None
    ready: str | None
    ready_certificate: bytes | None
    offer_authority: OfferAuthority
    answer_authority: BindingAuthority | None
    ready_authority: BindingAuthority | None
    serialized: str

    @property
    def kind(self):
        return "ready" if self.ready else "answer" if self.answer else "offer"

    def preview(self):
        value = _parse(self.ready or self.answer or self.offer)
        binding = value if self.kind == "offer" else value["binding"]
        return {"kind": self.kind, "workspace_id": self.invitation.workspace_id,
                "workspace_name": self.invitation.offered_manifest.name,
                "expires_at": binding["expires_at"], "candidate_count": len(binding["candidates"]),
                "state": "candidates_unverified" if binding["candidates"] else "no_public_candidate"}


def _control(value, *, required=False):
    if value is None and not required:
        return None, None
    if not isinstance(value, dict) or set(value) != {"document", "certificate"}:
        raise ValidationError("Direct document control is invalid")
    parsed = _parse(value["document"])
    if type(parsed.get("v")) is not int or parsed["v"] != 2:
        raise ValidationError("Public direct documents require version 2")
    certificate = value["certificate"]
    if (not isinstance(certificate, str) or not 2 <= len(certificate) <= 32768
            or len(certificate) % 2 or any(ch not in "0123456789abcdef" for ch in certificate)):
        raise ValidationError("Direct document certificate is invalid")
    return value["document"], bytes.fromhex(certificate)


def verify_connection_document(raw, *, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(raw, str) or len(raw) > MAX_BYTES * 4 // 3 + len(PREFIX) + 32:
        raise ValidationError("Direct document is too large")
    try:
        raw = raw.strip()
        if raw.startswith(PREFIX):
            token = raw[len(PREFIX):]
            if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in token):
                raise ValueError("token")
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != token:
                raise ValueError("token")
            raw = decoded.decode("utf-8")
        if not 1 <= len(raw.encode("utf-8")) <= MAX_BYTES:
            raise ValueError("size")
        value = json.loads(raw)
        if (not isinstance(value, dict) or canonical_bytes(value).decode("utf-8") != raw
                or set(value) != {"v", "type", "invitation", "offer", "answer", "ready"}
                or type(value["v"]) is not int or value["v"] != 2 or value["type"] != "direct_connection"):
            raise ValueError("fields")
        invite = verify_workspace_invitation(value["invitation"], now=now)
        offer, oc = _control(value["offer"], required=True)
        answer, ac = _control(value["answer"])
        ready, rc = _control(value["ready"])
        if ready and not answer:
            raise ValueError("missing Answer")
        owner = find_device(invite.offered_manifest, invite.offered_manifest.authority_device_id)
        if owner is None or owner[0].status != "active":
            raise ValueError("authority")
        fields = _parse(offer)
        expiry = fields["expires_at"]
        if type(expiry) is not int or expiry > fields["issued_at"] + 300:
            raise ValueError("window")
        scope = {"kind": "invitation", "digest": workspace_document_digest(invite.serialized),
                 "expires_at": invite.expires_at}
        oa = OfferAuthority(owner[1].public_identity, scope, min(expiry, invite.expires_at),
                            bytes.fromhex(fields["challenge"]))
        verify_offer(offer, oa, oc, now=now)
        aa, ra = None, None
        if answer:
            issuer = bytes.fromhex(_parse(answer)["binding"]["issuer_public_identity"])
            aa = BindingAuthority(issuer, owner[1].destination_hash, scope, oa.expires_at, oa.challenge)
            verify_answer(answer, aa, ac, offer_raw=offer, offer_authority=oa, offer_certificate_der=oc, now=now)
            if ready:
                ra = BindingAuthority(owner[1].public_identity, _destination_for(_identity_from_public_key(issuer)),
                                      scope, oa.expires_at, oa.challenge)
                verify_ready(ready, ra, rc, answer_raw=answer, answer_authority=aa,
                    answer_certificate_der=ac, offer_raw=offer, offer_authority=oa,
                    offer_certificate_der=oc, now=now)
        return ConnectionDocument(invite, offer, oc, answer, ac, ready, rc, oa, aa, ra, raw)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Direct connection document is invalid") from exc


def export_connection_document(invitation, offer, offer_certificate, *, answer=None,
                               answer_certificate=None, ready=None, ready_certificate=None, now=None):
    def control(document, certificate):
        if document is None and certificate is None:
            return None
        if not isinstance(document, str) or not isinstance(certificate, bytes):
            raise ValidationError("Direct document control is incomplete")
        return {"document": document, "certificate": certificate.hex()}
    value = {"v": 2, "type": "direct_connection", "invitation": invitation,
             "offer": control(offer, offer_certificate), "answer": control(answer, answer_certificate),
             "ready": control(ready, ready_certificate)}
    raw = canonical_bytes(value).decode("utf-8")
    verify_connection_document(raw, now=now)
    return PREFIX + base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
