"""Strict, narrow installed public-pair partition diagnostic evidence."""

import math

from check_public_core_pair import JOBS, ROLES, checked_context, hex_value, verify_flow
from public_core_partition_flow import (MAX_ADDITIONAL_REQUESTS, MAX_BLOCK_SECONDS,
    MIN_BLOCK_SECONDS, RECEIPT_SECONDS, RECOVERY_SECONDS, digest, text)


LEVEL = "installed_public_windows_android_partition_diagnostic"
SCENARIO = "public_pair_android_app_uid_partition"
SCOPE = ("Installed public Windows and Android consumers pair, approve and exchange receipts, "
         "then queue one message each under a counted 30-second Android app-UID network block "
         "and recover on the owned 150-ms-RTT emulator route; selected ICE path type, full SC04 "
         "and full SC21 acceptance remain open")
FAULT_FIELDS = {"app_uid_bound", "process_bound", "owned_route", "profile_restored", "dropped_packets"}
GATEWAY_FIELDS = {"namespace", "emulator_pid_bound", "adb_pid_bound", "cleanup", "impairment"}
PARTITION_FIELDS = {"v", "role", "pair_id", "outbound_text_sha256", "inbound_text_sha256",
    "outbound_message_count", "inbound_message_count", "outbound_delivered", "authority_unchanged",
    "no_receipt_during_block", "readiness_bound_origin", "readiness_after_origin_ms",
    "receipt_after_readiness_ms",
    "block_duration_ms", "fault_witness", "selected_path_type", "selected_path_qualified",
    "additional_request_count"}
REPORT_FIELDS = {"v", "passed", "evidence_level", "scenario", "scope", "role", "context",
    "source_tree", "flow", "inputs", "session", "gateway", "duration_seconds"}


def verify_partition_flow(value, role, pair_id):
    if type(value) is not dict or set(value) != {"baseline", "partition"}:
        raise ValueError("public_partition_flow_shape")
    verify_flow(value["baseline"], role, pair_id)
    row = value["partition"]
    other = "android" if role == "windows" else "windows"
    if (type(row) is not dict or set(row) != PARTITION_FIELDS
            or type(row["v"]) is not int or row["v"] != 1
            or row["role"] != role or row["pair_id"] != pair_id
            or row["outbound_text_sha256"] != digest(text(pair_id, role))
            or row["inbound_text_sha256"] != digest(text(pair_id, other))
            or any(type(row[name]) is not int or row[name] != 1
                   for name in ("outbound_message_count", "inbound_message_count"))
            or any(row[name] is not True for name in
                   ("outbound_delivered", "authority_unchanged", "no_receipt_during_block"))
            or row["selected_path_type"] is not None or row["selected_path_qualified"] is not False
            or row["readiness_bound_origin"] != ("fault_unblock" if role == "android" else "blocked_marker")
            or type(row["additional_request_count"]) is not int
            or not 1 <= row["additional_request_count"] <= MAX_ADDITIONAL_REQUESTS
            or value["baseline"]["public_request_count"] + row["additional_request_count"] > 126
            or any(type(row[name]) is not int or not 0 <= row[name] <= limit * 1000
                   for name, limit in (("readiness_after_origin_ms", RECOVERY_SECONDS),
                                       ("receipt_after_readiness_ms", RECEIPT_SECONDS)))):
        raise ValueError("public_partition_flow")
    if role == "android":
        witness = row["fault_witness"]
        if (type(row["block_duration_ms"]) is not int
                or not MIN_BLOCK_SECONDS * 1000 <= row["block_duration_ms"] <= MAX_BLOCK_SECONDS * 1000
                or type(witness) is not dict or set(witness) != FAULT_FIELDS
                or any(witness[key] is not True for key in
                       ("app_uid_bound", "process_bound", "owned_route", "profile_restored"))
                or type(witness["dropped_packets"]) is not int or witness["dropped_packets"] <= 0):
            raise ValueError("public_partition_fault")
    elif row["block_duration_ms"] is not None or row["fault_witness"] is not None:
        raise ValueError("public_partition_wrong_fault_owner")
    return row


def verify_role_report(value, role, context, tree, inputs):
    checked_context(context)
    if (type(value) is not dict or set(value) != REPORT_FIELDS
            or type(value["v"]) is not int or value["v"] != 1 or value["passed"] is not True
            or value["evidence_level"] != LEVEL or value["scenario"] != SCENARIO or value["scope"] != SCOPE
            or value["role"] != role or value["context"] != context or value["source_tree"] != tree
            or value["inputs"] != inputs or not hex_value(tree, 40)
            or type(value["session"]) is not dict or set(value["session"]) != {"finished", "cleanup", "fault_closed"}
            or any(value["session"][key] is not True for key in value["session"])
            or type(value["duration_seconds"]) not in (int, float)
            or not math.isfinite(value["duration_seconds"])
            or not 0 < value["duration_seconds"] <= 1200):
        raise ValueError("public_partition_role")
    if role == "android":
        gateway = value["gateway"]
        if (type(gateway) is not dict or set(gateway) != GATEWAY_FIELDS
                or gateway["namespace"] != "owned_linux_network_namespace"
                or gateway["cleanup"] != "passed"
                or any(gateway[key] is not True for key in ("emulator_pid_bound", "adb_pid_bound"))):
            raise ValueError("public_partition_gateway")
        impairment = gateway["impairment"]
        if (type(impairment) is not dict
                or set(impairment) != {"kind", "delay_ms_each_way", "jitter_ms_each_way",
                                       "loss_percent_each_way", "added_nominal_rtt_ms",
                                       "link_scope", "counters", "loss_observed", "gateway_coverage"}
                or impairment.get("kind") != "android_emulator_host_gateway_tc_netem"
                or impairment.get("delay_ms_each_way") != 75
                or impairment.get("jitter_ms_each_way") != 10
                or impairment.get("loss_percent_each_way") != 0.1
                or impairment.get("added_nominal_rtt_ms") != 150
                or impairment.get("link_scope") != "owned_host_namespace_veth"
                or type(impairment.get("counters")) is not dict
                or set(impairment["counters"]) != {"egress", "ingress"}
                or any(type(row) is not dict or set(row) != {"bytes", "packets", "dropped"}
                       or any(type(row[key]) is not int or row[key] < 0 for key in row)
                       or row["bytes"] <= 0 or row["packets"] <= 0
                       for row in impairment["counters"].values())
                or type(impairment.get("gateway_coverage")) is not dict
                or set(impairment["gateway_coverage"]) != {"external_links", "namespace_bound",
                    "ipv6_disabled", "veth_identity_current", "directional_veth_packets"}
                or impairment["gateway_coverage"].get("external_links") != 1
                or impairment["gateway_coverage"].get("namespace_bound") is not True
                or impairment["gateway_coverage"].get("ipv6_disabled") is not True
                or impairment["gateway_coverage"].get("veth_identity_current") is not True
                or type(impairment["gateway_coverage"].get("directional_veth_packets")) is not dict
                or set(impairment["gateway_coverage"]["directional_veth_packets"]) != {"egress", "ingress"}
                or any(type(count) is not int or count <= 0 for count in
                       impairment["gateway_coverage"]["directional_veth_packets"].values())):
            raise ValueError("public_partition_impairment")
    elif value["gateway"] is not None:
        raise ValueError("public_partition_windows_gateway")
    verify_partition_flow(value["flow"], role, context["pair_id"])
    return value


def verify_pair_reports(windows, android, context, tree, inputs, needs):
    checked_context(context)
    if (type(inputs) is not dict or set(inputs) != set(ROLES)
            or type(needs) is not dict or set(needs) != JOBS
            or any(type(job) is not dict or job.get("result") != "success" for job in needs.values())):
        raise ValueError("public_partition_prerequisites")
    for role, report in (("windows", windows), ("android", android)):
        verify_role_report(report, role, context, tree, inputs[role])
    left, right = windows["flow"], android["flow"]
    for own, other in ((left, right), (right, left)):
        if (own["baseline"]["self_destination_sha256"] != other["baseline"]["peer_destination_sha256"]
                or own["baseline"]["outbound_text_sha256"] != other["baseline"]["inbound_text_sha256"]
                or own["partition"]["outbound_text_sha256"] != other["partition"]["inbound_text_sha256"]):
            raise ValueError("public_partition_cross_match")
    return True
