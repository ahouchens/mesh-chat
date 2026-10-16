"""Application receipt for an exact signed workspace join and delivery attempt.

This additive control does not change any invitation or admission document.
The authority key is obtained from the verified invitation, never the receipt.
"""
from __future__ import annotations

import time
from typing import Any

import RNS

from .errors import IdentityMismatch, ValidationError
from .workspace_protocol import (
    VerifiedWorkspaceJoin,
    _identity_from_public_key,
    _load_document,
    _require_fields,
    _sign,
    _validate_timestamp,
    _validate_uuid,
    _verify_signature,
    find_device,
)

MAX_JOIN_RECEIPT_BYTES = 2048
JOIN_RECEIPT_VERSION = 1


def _binding(join: VerifiedWorkspaceJoin, attempt_id: str) -> dict[str, Any]:
    return {
        "v": JOIN_RECEIPT_VERSION,
        "type": "workspace_join_receipt",
        "workspace_id": join.workspace_id,
        "join_digest": join.digest,
        "join_attempt_id": _validate_uuid(attempt_id, "Join attempt ID"),
        "audience_device_id": join.device.device_id,
        "audience_destination": join.device.destination_hash.hex(),
        "authority_device_id": join.invitation.offered_manifest.authority_device_id,
    }


def create_workspace_join_receipt(
    identity: RNS.Identity, join: VerifiedWorkspaceJoin, attempt_id: str,
    *, now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else now
    authority = find_device(
        join.invitation.offered_manifest,
        join.invitation.offered_manifest.authority_device_id,
    )
    if authority is None or identity.get_public_key() != authority[1].public_identity:
        raise IdentityMismatch("Only the invitation authority can acknowledge a join")
    if current > join.invitation.expires_at:
        raise ValidationError("Join receipt is outside the invitation window")
    return _sign(identity, {
        **_binding(join, attempt_id),
        # A small clock offset must not prevent an otherwise valid join from
        # being stored. Reuse the workspace protocol's timestamp tolerance.
        "received_at": max(current, join.created_at),
        "expires_at": join.invitation.expires_at,
    }, maximum=MAX_JOIN_RECEIPT_BYTES)


def verify_workspace_join_receipt(
    raw: str, join: VerifiedWorkspaceJoin, attempt_id: str,
    *, now: int | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_JOIN_RECEIPT_BYTES:
        raise ValidationError("Join receipt is too large")
    value = _load_document(raw, "workspace_join_receipt")
    expected = _binding(join, attempt_id)
    _require_fields(value, {*expected, "received_at", "expires_at", "signature"})
    if type(value["v"]) is not int or any(value[key] != item for key, item in expected.items()):
        raise ValidationError("Join receipt does not match this request")
    current = int(time.time()) if now is None else now
    received = _validate_timestamp(value["received_at"], now=current)
    expiry = value["expires_at"]
    if (
        type(expiry) is not int or expiry != join.invitation.expires_at
        or not join.created_at <= received <= expiry
        or current > expiry
    ):
        raise ValidationError("Join receipt validity is invalid")
    authority = find_device(join.invitation.offered_manifest, expected["authority_device_id"])
    if authority is None:
        raise IdentityMismatch("Join receipt authority is unavailable")
    _verify_signature(_identity_from_public_key(authority[1].public_identity), value, "Join receipt")
    return value
