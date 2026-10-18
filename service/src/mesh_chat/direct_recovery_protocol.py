"""Admitted RNS authority and bounded opaque recovery documents; no invitations."""
import hashlib

from .direct_binding import BindingAuthority, _parse
from .errors import ValidationError
from .invitations import canonical_bytes
from .workspace_protocol import _destination_for, _identity_from_public_key

PREFIX = "mesh-recover:"
MAX_BYTES = 16 * 1024


def authority(record, *, now):
    scope = record["scope"]
    if scope.get("kind") != "workspace":
        raise ValidationError("Recovery requires current membership")
    material = canonical_bytes({"purpose": "mesh-direct-recovery/1", "scope": scope,
        "issuer": record["issuer"], "audience": record["audience"]})
    return BindingAuthority(bytes.fromhex(record["issuer"]), bytes.fromhex(record["audience"]),
                            dict(scope), now+3600, hashlib.sha256(material).digest())


def outgoing_authority(service, incoming, *, now):
    peer = _destination_for(_identity_from_public_key(incoming.issuer_public_identity))
    scope = {**incoming.scope, "issuer_device_id": incoming.scope["audience_device_id"],
             "audience_device_id": incoming.scope["issuer_device_id"]}
    return authority({"scope": scope, "issuer": service._identity.get_public_key().hex(),
                      "audience": peer.hex()}, now=now)


def encode(raw, certificate):
    text = PREFIX + canonical_bytes({"v":1,"type":"direct_recovery","binding":raw,
                                      "certificate":certificate.hex()}).decode()
    decode(text)
    return text


def decode(text):
    if not isinstance(text,str) or not text.startswith(PREFIX) or len(text.encode()) > MAX_BYTES:
        raise ValidationError("Invalid connection update")
    value = _parse(text[len(PREFIX):])
    if (set(value) != {"v","type","binding","certificate"} or type(value["v"]) is not int
            or value["v"] != 1 or value["type"] != "direct_recovery"):
        raise ValidationError("Invalid connection update")
    raw = value["binding"]
    binding = _parse(raw)
    if binding.get("v") != 3 or binding.get("scope",{}).get("kind") != "workspace":
        raise ValidationError("Connection update requires admitted recovery authority")
    try:
        cert = bytes.fromhex(value["certificate"])
        if not 1 <= len(cert) <= 4096 or cert.hex() != value["certificate"]:
            raise ValueError()
    except (TypeError,ValueError):
        raise ValidationError("Invalid recovery certificate") from None
    return raw, cert, binding


def capsule(peer_identity, raw):
    if len(raw.encode()) > 16*1024 or _parse(raw).get("v") != 3:
        raise ValidationError("Invalid recovery binding")
    return _identity_from_public_key(peer_identity).encrypt(raw.encode())


def open_capsule(identity, encrypted):
    if not isinstance(encrypted,bytes) or not 1 <= len(encrypted) <= 20*1024:
        raise ValidationError("Invalid recovery capsule")
    try:
        raw = identity.decrypt(encrypted).decode("utf-8")
        if _parse(raw).get("v") != 3:
            raise ValueError()
        return raw
    except (AttributeError,UnicodeError,ValueError,TypeError):
        raise ValidationError("Recovery capsule authentication failed") from None
