"""Strict failure-only projection for the private Android qualification transport."""

import json

OPERATION_STAGES = {
    "runtime_capabilities": frozenset({"core_admission", "capabilities", "session_escape", "frame_encode"}),
    "ice_servers": frozenset({"core_admission", "ice_adapter", "ice_service", "ice_return", "ice_view",
        "broker_url", "broker_request", "tls_context", "broker_open", "broker_status", "broker_read",
        "broker_size", "broker_json", "broker_validate", "session_escape", "frame_encode"}),
}
CATEGORIES = frozenset({"network_unavailable", "api_internal", "invalid_observation", "validation",
    "storage_unavailable", "unexpected", "response_encoding"})
CAUSES = frozenset({"certificate_verification", "tls_other", "name_resolution", "timeout", "http_error",
    "json_decode", "file_not_found", "permission_denied", "other", "none", "unknown"})


def core_failure_observation(value):
    try:
        if (type(value) is not dict or set(value) != {"v", "operation", "stage", "category", "cause"}
                or type(value["v"]) is not int or value["v"] != 1
                or any(type(value[name]) is not str for name in ("operation", "stage", "category", "cause"))
                or value["operation"] not in OPERATION_STAGES
                or value["stage"] not in OPERATION_STAGES[value["operation"]]
                or value["category"] not in CATEGORIES or value["cause"] not in CAUSES
                or ((value["category"] == "response_encoding") != (value["stage"] == "frame_encode"))
                or (value["category"] == "invalid_observation" and value["stage"] not in {"ice_return", "ice_view"})
                or len(json.dumps(value, separators=(",", ":")).encode("utf-8")) > 512):
            return None
        return dict(value)
    except Exception:
        return None
