"""Pure, bounded labels from retained pairing SDP; never project SDP or ICE secrets."""

from hashlib import sha256
from ipaddress import ip_address


MAX_SDP_BYTES = 32 * 1024
MAX_SDP_LINES = 512
MAX_CANDIDATES = 256
TYPES = ("host", "srflx", "prflx", "relay", "unknown")
PROTOCOLS = ("udp", "tcp", "unknown")
FAMILIES = ("ipv4", "ipv6", "mdns", "unknown")
_HEX = frozenset("0123456789abcdef")


def unavailable_ice_diagnostic():
    return {"availability": "unavailable", "local": None, "remote": None, "correlation": None}


def _lines(sdp):
    if type(sdp) is not str or not sdp.startswith(("v=0\r\n", "v=0\n")):
        return None
    try:
        if len(sdp.encode("utf-8")) > MAX_SDP_BYTES:
            return None
    except UnicodeError:
        return None
    lines = sdp.replace("\r\n", "\n").split("\n")
    if (len(lines) > MAX_SDP_LINES
            or len([line for line in lines if line.startswith("m=")]) != 1
            or not any(line.startswith("m=application ") for line in lines)
            or any(any(ord(char) < 32 or ord(char) == 127 for char in line) for line in lines)):
        return None
    return lines


def _ufrag_digest(lines):
    values = {line[len("a=ice-ufrag:"):] for line in lines if line.startswith("a=ice-ufrag:")}
    if len(values) != 1:
        return None
    value = next(iter(values))
    if (not 4 <= len(value) <= 256 or not all(
            char.isascii() and (char.isalnum() or char in "+/") for char in value)):
        return None
    return sha256(value.encode("ascii")).hexdigest()


def ufrag_pair(local_sdp, remote_sdp):
    """Private unordered generation key for detecting reused ICE credentials."""
    local, remote = _lines(local_sdp), _lines(remote_sdp)
    if local is None or remote is None:
        return None
    first, second = _ufrag_digest(local), _ufrag_digest(remote)
    return frozenset((first, second)) if first and second and first != second else None


def _family(address):
    try:
        return "ipv4" if ip_address(address).version == 4 else "ipv6"
    except ValueError:
        return "mdns" if (address.endswith(".local") and 1 <= len(address) <= 253
                          and all(char.isascii() and (char.isalnum() or char in "-.")
                                  for char in address)) else "unknown"


def _candidate_summary(lines):
    candidates = [line[len("a=candidate:"):] for line in lines if line.startswith("a=candidate:")]
    if len(candidates) > MAX_CANDIDATES:
        return None
    result = {"total": len(candidates), "types": dict.fromkeys(TYPES, 0),
              "protocols": dict.fromkeys(PROTOCOLS, 0), "families": dict.fromkeys(FAMILIES, 0)}
    for candidate in candidates:
        parts = candidate.split()
        if (len(parts) < 8 or len(candidate) > 1024 or not parts[0]
                or not parts[1].isdigit() or not 1 <= int(parts[1]) <= 256
                or not parts[3].isdigit() or not 0 <= int(parts[3]) <= 2**32 - 1
                or not parts[5].isdigit() or not 1 <= int(parts[5]) <= 65535
                or parts[6].lower() != "typ"):
            return None
        kind = parts[7].lower()
        protocol = parts[2].lower()
        result["types"][kind if kind in TYPES else "unknown"] += 1
        result["protocols"][protocol if protocol in PROTOCOLS else "unknown"] += 1
        result["families"][_family(parts[4])] += 1
    return result


def ice_diagnostic(local_sdp, remote_sdp):
    """Counts SDP candidate lines; does not infer a usable native checklist."""
    local, remote = _lines(local_sdp), _lines(remote_sdp)
    if local is None or remote is None:
        return unavailable_ice_diagnostic()
    first, second = _ufrag_digest(local), _ufrag_digest(remote)
    local_candidates, remote_candidates = _candidate_summary(local), _candidate_summary(remote)
    if (first is None or second is None or first == second
            or local_candidates is None or remote_candidates is None):
        return unavailable_ice_diagnostic()
    return {"availability": "selected", "local": local_candidates, "remote": remote_candidates,
            "correlation": {"local_ufrag_sha256": first, "remote_ufrag_sha256": second}}


def _valid_counts(value):
    if type(value) is not dict or set(value) != {"total", "types", "protocols", "families"}:
        return False
    total = value["total"]
    if type(total) is not int or not 0 <= total <= MAX_CANDIDATES:
        return False
    for field, labels in (("types", TYPES), ("protocols", PROTOCOLS), ("families", FAMILIES)):
        counts = value[field]
        if (type(counts) is not dict or set(counts) != set(labels)
                or any(type(counts[label]) is not int or not 0 <= counts[label] <= total for label in labels)
                or sum(counts.values()) != total):
            return False
    return True


def validated_pairing_ice_diagnostic(value):
    """Copy only the fixed private DTO; None means malformed, not unavailable."""
    if type(value) is not dict or set(value) != {"availability", "local", "remote", "correlation"}:
        return None
    if value["availability"] == "unavailable":
        return unavailable_ice_diagnostic() if (value["local"], value["remote"], value["correlation"]) == (None, None, None) else None
    if (value["availability"] != "selected" or not _valid_counts(value["local"])
            or not _valid_counts(value["remote"])):
        return None
    correlation = value["correlation"]
    if (type(correlation) is not dict
            or set(correlation) != {"local_ufrag_sha256", "remote_ufrag_sha256"}
            or any(type(item) is not str or len(item) != 64 or not set(item) <= _HEX
                   for item in correlation.values())
            or correlation["local_ufrag_sha256"] == correlation["remote_ufrag_sha256"]):
        return None
    return {"availability": "selected",
            "local": {"total": value["local"]["total"], **{
                field: dict(value["local"][field]) for field in ("types", "protocols", "families")}},
            "remote": {"total": value["remote"]["total"], **{
                field: dict(value["remote"][field]) for field in ("types", "protocols", "families")}},
            "correlation": dict(correlation)}
