"""Strict evidence for one public Windows owner restart with Android held alive.

This is a separate diagnostic from the fresh-pair report. The controller and
workflow that collect these role reports are intentionally supplied later.
"""

import math

from check_public_core_pair import JOBS, ROLES, checked_context, hex_value, verify_flow


LEVEL = "installed_public_windows_owner_restart_diagnostic"
SCENARIO = "windows_owner_restart_with_continuous_android"
SCOPE = ("Installed public Windows owner positively retired and reopened on the same EFS data "
         "while one Android public session remains alive; original profile, contact and messages "
         "persist, and one new message with receipt passes each direction; no pending/offline work, "
         "partition, Android restart, media, physical device or full SC21 acceptance")
WINDOWS_CHECKS = {"baseline_preserved": True, "positive_owner_stop": True,
                  "new_owner_process": True, "same_data_reopen": True,
                  "ready_after_restart": True, "outbound_delivered": True, "inbound_once": True}
ANDROID_CHECKS = {"baseline_preserved": True, "same_session_during_owner_stop": True,
                  "same_session_after_reopen": True, "ready_after_restart": True,
                  "outbound_delivered": True, "inbound_once": True}
FLOW_FIELDS = {"v", "role", "pair_id", "baseline", "checks", "request_counts",
               "post_outbound_text_sha256", "post_inbound_text_sha256",
               "post_outbound_message_count", "post_inbound_message_count"}
REPORT_FIELDS = {"v", "passed", "evidence_level", "scenario", "scope", "role", "context",
                 "source_tree", "flow", "inputs", "session", "duration_seconds"}


def post_text_digest(pair_id, role):
    import hashlib
    return hashlib.sha256(f"public-core-restart:v1:{pair_id}:{role}".encode("utf-8")).hexdigest()


def verify_restart_flow(value, role, pair_id):
    if (role not in ROLES or type(value) is not dict or set(value) != FLOW_FIELDS
            or type(value["v"]) is not int or value["v"] != 1
            or value["role"] != role or value["pair_id"] != pair_id):
        raise ValueError("public_restart_flow_shape")
    verify_flow(value["baseline"], role, pair_id)
    expected = WINDOWS_CHECKS if role == "windows" else ANDROID_CHECKS
    checks = value["checks"]
    if (type(checks) is not dict or set(checks) != set(expected)
            or any(type(checks[key]) is not bool or checks[key] is not True for key in expected)):
        raise ValueError("public_restart_checks")
    counts = value["request_counts"]
    baseline = value["baseline"]["public_request_count"]
    if role == "windows":
        valid_counts = (type(counts) is dict and set(counts) == {"baseline", "before_stop", "after_reopen"}
                        and all(type(item) is int for item in counts.values())
                        and counts["baseline"] == baseline
                        and baseline + 3 <= counts["before_stop"] <= 96
                        and 12 <= counts["after_reopen"] <= 96)
    else:
        valid_counts = (type(counts) is dict and set(counts) == {"baseline", "additional", "total"}
                        and all(type(item) is int for item in counts.values())
                        and counts["baseline"] == baseline
                        and 18 <= counts["additional"] and counts["total"] == baseline + counts["additional"]
                        and counts["total"] <= 126)
    other = "android" if role == "windows" else "windows"
    if (not valid_counts or type(value["post_outbound_message_count"]) is not int
            or value["post_outbound_message_count"] != 1
            or type(value["post_inbound_message_count"]) is not int
            or value["post_inbound_message_count"] != 1
            or value["post_outbound_text_sha256"] != post_text_digest(pair_id, role)
            or value["post_inbound_text_sha256"] != post_text_digest(pair_id, other)):
        raise ValueError("public_restart_counts_or_text")
    return value


def verify_role_report(value, role, context, tree, expected_inputs):
    checked_context(context)
    if (type(value) is not dict or set(value) != REPORT_FIELDS
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["evidence_level"] != LEVEL or value["scenario"] != SCENARIO
            or value["scope"] != SCOPE or value["role"] != role
            or value["context"] != context or value["source_tree"] != tree
            or value["inputs"] != expected_inputs
            or type(value["session"]) is not dict
            or set(value["session"]) != {"finished", "cleanup", "owner_incarnations_finished"}
            or value["session"]["finished"] is not True
            or value["session"]["cleanup"] is not True
            or type(value["session"]["owner_incarnations_finished"]) is not int
            or value["session"]["owner_incarnations_finished"] != (2 if role == "windows" else 1)
            or type(value["duration_seconds"]) not in {int, float}
            or not math.isfinite(value["duration_seconds"])
            or not 0 < value["duration_seconds"] <= 1200):
        raise ValueError("public_restart_role")
    if not hex_value(tree, 40):
        raise ValueError("public_restart_tree")
    verify_restart_flow(value["flow"], role, context["pair_id"])
    return value


def verify_pair_reports(windows, android, context, tree, expected_inputs, needs):
    checked_context(context)
    if (type(expected_inputs) is not dict or set(expected_inputs) != set(ROLES)
            or type(needs) is not dict or set(needs) != JOBS
            or any(type(job) is not dict or job.get("result") != "success" for job in needs.values())):
        raise ValueError("public_restart_prerequisites")
    for role, report in (("windows", windows), ("android", android)):
        verify_role_report(report, role, context, tree, expected_inputs[role])
    left, right = windows["flow"], android["flow"]
    for own, other in ((left, right), (right, left)):
        if (own["baseline"]["self_destination_sha256"] != other["baseline"]["peer_destination_sha256"]
                or own["baseline"]["outbound_text_sha256"] != other["baseline"]["inbound_text_sha256"]
                or own["post_outbound_text_sha256"] != other["post_inbound_text_sha256"]):
            raise ValueError("public_restart_cross_match")
    return True
