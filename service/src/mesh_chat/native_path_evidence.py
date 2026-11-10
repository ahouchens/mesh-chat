"""Private qualification observations; never normal diagnostics or durable truth."""
import hashlib
import ipaddress
import json
import math

from .errors import NativeUnavailable

MAX_BYTES = 16 * 1024
MAX_INTEGER = 2**53 - 1
SAMPLE_TIMEOUT = 2.0
COUNTERS = ("enqueued_packets", "enqueued_controls", "enqueued_bytes",
            "received_packets", "received_controls", "received_bytes")


def endpoint(address, port):
    if not isinstance(address, str):
        raise ValueError("Invalid address")
    address = str(ipaddress.ip_address(address))
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return {"address": address, "port": port}


def candidate(address, port, kind, protocol):
    if kind not in {"host", "srflx", "prflx", "relay"} or protocol not in {"udp", "tcp"}:
        raise ValueError("Invalid candidate")
    return {**endpoint(address, port), "type": kind, "protocol": protocol}


def pair_token(epoch, resource, local, remote):
    material = json.dumps([epoch, resource, local, remote], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("ascii")).hexdigest()[:32]


def observation(resource, epoch, sequence, sampled_at_ms, *, status, ice_state,
                dtls_state, channel_state, sample_request, pair=None, application=None):
    return {"v": 1, "resource": resource, "adapter_epoch": epoch,
            "sample_sequence": sequence, "sampled_at_ms": sampled_at_ms,
            "sample_request": sample_request, "status": status,
            "ice_state": ice_state, "dtls_state": dtls_state, "channel_state": channel_state,
            "pair": pair, "availability": availability(pair),
            "application": application or {key: 0 for key in COUNTERS}}


def availability(pair):
    return {"selected_pair": pair is not None,
            "relay_protocol": pair is not None and pair["relay_protocol"] != "unknown",
            "relay_socket": pair is not None and pair["relay_socket"] is not None,
            "pair_bytes": pair is not None and pair["bytes_sent"] is not None and pair["bytes_received"] is not None,
            "rtt": pair is not None and pair["rtt_ms"] is not None}


def validate_sample_request(value):
    if (type(value) is not str or len(value) != 32
            or any(character not in "0123456789abcdef" for character in value)):
        raise NativeUnavailable("Native sample request is invalid")
    return value


def validate_observation(value, resource, sample_request):
    """Reject unbounded/foreign fields rather than exporting backend contents."""
    try:
        validate_sample_request(sample_request)
        if not isinstance(value, dict) or set(value) != {
            "v", "resource", "adapter_epoch", "sample_sequence", "sampled_at_ms", "status",
            "sample_request", "ice_state", "dtls_state", "channel_state", "pair", "application", "availability",
        }:
            raise ValueError
        if validate_sample_request(value["sample_request"]) != sample_request:
            raise ValueError
        if value["v"] != 1 or type(value["v"]) is not int or value["resource"] != resource:
            raise ValueError
        if not isinstance(resource, str) or not 1 <= len(resource) <= 128:
            raise ValueError
        epoch = value["adapter_epoch"]
        if not isinstance(epoch, str) or len(epoch) != 32 or any(c not in "0123456789abcdef" for c in epoch):
            raise ValueError
        for key in ("sample_sequence", "sampled_at_ms"):
            _integer(value[key])
        if value["sample_sequence"] == 0 or value["status"] not in {"selected", "not_selected", "unsupported", "unavailable"}:
            raise ValueError
        states = {"ice_state": {"new", "checking", "connected", "completed", "disconnected", "failed", "closed", "unknown"},
                  "dtls_state": {"new", "connecting", "connected", "closed", "failed", "unknown"},
                  "channel_state": {"connecting", "open", "closing", "closed", "missing", "unknown"}}
        for key, allowed in states.items():
            if value[key] not in allowed:
                raise ValueError
        application = value["application"]
        if not isinstance(application, dict) or set(application) != set(COUNTERS):
            raise ValueError
        for count in application.values():
            _integer(count)
        pair = value["pair"]
        if pair is None:
            if value["status"] == "selected":
                raise ValueError
        else:
            _validate_pair(pair, value)
        if value["availability"] != availability(pair) or any(type(v) is not bool for v in value["availability"].values()):
            raise ValueError
        raw = json.dumps(value, allow_nan=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_BYTES:
            raise ValueError
        return json.loads(raw)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise NativeUnavailable("Native path evidence is invalid") from error


def _integer(value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError


def _validate_pair(pair, value):
    if (not isinstance(pair, dict) or set(pair) != {
            "token", "local", "remote", "nominated", "relay_protocol", "relay_socket",
            "bytes_sent", "bytes_received", "rtt_ms"}
            or value["status"] != "selected" or value["ice_state"] not in {"connected", "completed"}):
        raise ValueError
    for key in ("local", "remote"):
        current = pair[key]
        if not isinstance(current, dict) or set(current) != {"address", "port", "type", "protocol"}:
            raise ValueError
        candidate(current["address"], current["port"], current["type"], current["protocol"])
    if pair["token"] != pair_token(value["adapter_epoch"], value["resource"], pair["local"], pair["remote"]):
        raise ValueError
    if pair["nominated"] is not None and type(pair["nominated"]) is not bool:
        raise ValueError
    if pair["relay_protocol"] not in {"udp", "tcp", "tls", "unknown", "not_applicable"}:
        raise ValueError
    if ((pair["local"]["type"] == "relay") == (pair["relay_protocol"] == "not_applicable")):
        raise ValueError
    socket = pair["relay_socket"]
    if socket is not None:
        if set(socket) != {"local", "remote", "protocol"} or socket["protocol"] != pair["relay_protocol"]:
            raise ValueError
        for key in ("local", "remote"):
            if not isinstance(socket[key], dict) or set(socket[key]) != {"address", "port"}:
                raise ValueError
            endpoint(**socket[key])
    for key in ("bytes_sent", "bytes_received"):
        if pair[key] is not None:
            _integer(pair[key])
    rtt = pair["rtt_ms"]
    if rtt is not None and (type(rtt) not in {int, float} or not math.isfinite(rtt) or not 0 <= rtt <= 3600_000):
        raise ValueError
