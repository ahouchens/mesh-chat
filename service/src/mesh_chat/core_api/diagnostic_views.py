"""Allowlisted, bounded presentation of current policy observations."""

import json

from .diagnostics import MAX_DIAGNOSTICS, MAX_DIAGNOSTIC_BYTES
from .errors import ApiFailure
from .views import _timestamp, connection_view


def diagnostics_view(profile, value, limit, connection_handle):
    if (type(value.available) is not bool or not isinstance(value.connections, dict)
            or (value.runtime_failure is not None and not isinstance(value.runtime_failure, str))
            or (not value.available and (value.connections or value.runtime_failure is not None))):
        raise ApiFailure("internal")
    if len(value.connections) > MAX_DIAGNOSTICS:
        raise ApiFailure("resource_exhausted")
    if any(not isinstance(key, str) or not 1 <= len(key) <= 256 for key in value.connections):
        raise ApiFailure("internal")
    failure = value.runtime_failure
    if failure not in {None, "adapter_quarantined", "cleanup_failed"}:
        failure = "unknown"
    connections = sorted((connection_handle(key), state) for key, state in value.connections.items())
    result = {
        "profile": profile, "captured_at": _timestamp(value.captured_at),
        "available": value.available, "runtime_failure": failure,
        "connections": [{"connection": handle, "observation": connection_view(state)}
                        for handle, state in connections[:limit]],
        "total_connections": len(connections), "truncated": len(connections) > limit,
    }
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > MAX_DIAGNOSTIC_BYTES - 256:
        raise ApiFailure("internal")
    return result
