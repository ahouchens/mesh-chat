"""Public credential control carried by authenticated bootstrap LXMF only."""
import json

from .direct_binding import _parse
from .errors import ValidationError
from .invitations import canonical_bytes

MAX_BYTES = 64 * 1024


def encode(binding, certificate):
    value = {"v":2, "type":"direct_admission", "binding":binding, "certificate":certificate.hex()}
    raw = canonical_bytes(value).decode()
    decode(raw)
    return raw


def decode(raw):
    try:
        if not isinstance(raw, str) or not 1 <= len(raw.encode()) <= MAX_BYTES:
            raise ValueError()
        value = json.loads(raw)
        if (not isinstance(value,dict) or set(value) != {"v","type","binding","certificate"}
                or type(value["v"]) is not int or value["v"] != 2 or value["type"] != "direct_admission"
                or canonical_bytes(value).decode() != raw):
            raise ValueError()
        binding = _parse(value["binding"])
        if (type(binding.get("v")) is not int or binding["v"] != 2
                or not isinstance(binding.get("scope"),dict) or binding["scope"].get("kind") != "workspace"):
            raise ValueError()
        cert = value["certificate"]
        if not isinstance(cert,str) or not 2 <= len(cert) <= 32768 or any(ch not in "0123456789abcdef" for ch in cert):
            raise ValueError()
        return value["binding"], bytes.fromhex(cert)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise ValidationError("Direct admission control is invalid") from exc
