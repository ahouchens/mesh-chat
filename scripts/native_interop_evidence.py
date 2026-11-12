"""Consume fresh private observations; retain only scoped content-free evidence."""

import hashlib
import json
import math
import re
import time
from native_interop_workload import LEVEL, PATH_CASES, SCOPE, workload as required_workload

SCENARIOS = ("direct", "turn_udp", "turn_tcp", "turn_tls", "impaired", "cold_start_receipts")
APPLICATION = ("enqueued_packets", "enqueued_controls", "enqueued_bytes", "received_packets", "received_controls", "received_bytes")
ACCOUNTING = ("capacity", "reserved_count", "creating_count", "allocated_count", "active_count", "retiring_count")
SAMPLE_REJECTION_REASONS = frozenset({
    "sample_object", "qualification_scope", "sample_version", "service_incarnation", "profile_incarnation",
    "adapter_epoch", "sample_request", "sample_sequence", "sample_ttl", "sample_timestamp",
    "request_elapsed", "service_elapsed", "sample_resource", "sample_replay", "sample_readiness",
    "selected_transport", "direct_selected_type", "relay_selected_protocol", "application_counters", "selected_pair_identity",
})


class AccountingUnavailable(ValueError):
    code = "native_accounting_unavailable"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def token(value, length):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{" + str(length) + "}", value) is not None


def finite_clock(value):
    if type(value) not in {int, float}: return False
    try: return math.isfinite(value)
    except OverflowError: return False


def accounting(value, *, empty=False):
    if (not isinstance(value, dict) or value.get("v") != 1 or type(value["v"]) is not int
            or value.get("complete") is not True or value.get("semantics") != "native_allocation_leases"
            or not isinstance(value.get("availability"), dict) or set(value["availability"]) != set(ACCOUNTING)
            or any(value["availability"][name] is not True for name in ACCOUNTING)
            or any(type(value.get(name)) is not int or not 0 <= value[name] <= 16 for name in ACCOUNTING)
            or not 1 <= value["capacity"] <= 16 or value["reserved_count"] > value["capacity"]
            or value["creating_count"] > value["reserved_count"] or value["allocated_count"] > value["reserved_count"]
            or value["allocated_count"] != value["active_count"] + value["retiring_count"]):
        raise AccountingUnavailable("Complete actual native allocation accounting is unavailable")
    if empty and any(value[name] != 0 for name in ACCOUNTING if name != "capacity"):
        raise ValueError("Native allocation leases have not all retired")
    return {"v": 1, "complete": True, "semantics": value["semantics"], "availability": dict(value["availability"]),
            **{name: value[name] for name in ACCOUNTING}}


class Samples:
    def __init__(self, *, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.previous = {}
        self._rejection = None

    def _reject(self, reason, message):
        error = ValueError(message)
        self._rejection = error, reason
        raise error

    def failure_reason(self, error):
        observed = self._rejection
        return (observed[1] if observed is not None and observed[0] is error
                and type(observed[1]) is str and observed[1] in SAMPLE_REJECTION_REASONS else None)

    def check_request(self, value, sample_request):
        self._rejection = None
        invalid = "Private native observation is stale or belongs to another runtime"
        if not isinstance(value, dict): self._reject("sample_object", invalid)
        if (type(sample_request) is not str or not token(sample_request, 32)
                or type(value.get("sample_request")) is not str or value["sample_request"] != sample_request):
            self._reject("sample_request", invalid)

    def consume(self, value, inventory, requested_at, *, sample_request, ready=False, scenario=None):
        self.check_request(value, sample_request)
        invalid = "Private native observation is stale or belongs to another runtime"
        if value.get("qualification_only") is not True: self._reject("qualification_scope", invalid)
        if type(value.get("v")) is not int or value["v"] != 1: self._reject("sample_version", invalid)
        if value.get("service_incarnation") != inventory.get("service_incarnation"):
            self._reject("service_incarnation", invalid)
        if value.get("profile_incarnation") != inventory.get("profile_incarnation"):
            self._reject("profile_incarnation", invalid)
        if not token(value.get("adapter_epoch"), 32): self._reject("adapter_epoch", invalid)
        if type(value.get("sample_sequence")) is not int or value["sample_sequence"] <= 0:
            self._reject("sample_sequence", invalid)
        if type(value.get("valid_for_ms")) is not int or value["valid_for_ms"] != 2000:
            self._reject("sample_ttl", invalid)
        # Native time is opaque here. Freshness is invocation-bound plus local elapsed time;
        # the producer validates the original timestamp in its own clock domain.
        if type(value.get("sampled_at_ms")) is not int or not 0 <= value["sampled_at_ms"] <= 2**53 - 1:
            self._reject("sample_timestamp", invalid)
        returned_at = self.monotonic()
        if (not finite_clock(requested_at) or not finite_clock(returned_at)
                or not 0 <= returned_at - requested_at <= 2):
            self._reject("request_elapsed", invalid)
        if type(value.get("sample_elapsed_ms")) is not int or not 0 <= value["sample_elapsed_ms"] <= 2000:
            self._reject("service_elapsed", invalid)
        resource = next((item for item in inventory.get("resources", [])
                         if item.get("logical_session") == value.get("logical_session")
                         and item.get("physical_resource") == value.get("resource")), None)
        if resource is None:
            self._reject("sample_resource", "Native observation does not identify a current exact resource")
        identity = (value["service_incarnation"], value["resource"], value["adapter_epoch"])
        previous = self.previous.get(identity, 0)
        if value["sample_sequence"] <= previous:
            self._reject("sample_replay", "Native observation sequence did not advance")
        self.previous[identity] = value["sample_sequence"]
        if ready and any(value.get(field) is not True for field in ("adopted", "attached", "messaging_ready")):
            self._reject("sample_readiness", "Selected ICE does not establish supervisor messaging readiness")
        pair = value.get("pair")
        if (value.get("status") != "selected" or not isinstance(pair, dict)
                or value.get("ice_state") not in {"connected", "completed"}
                or value.get("dtls_state") != "connected" or value.get("channel_state") != "open"):
            self._reject("selected_transport", "Required selected native path is unavailable")
        if scenario == "direct":
            if any(pair.get(field, {}).get("type") not in {"host", "srflx", "prflx"} for field in ("local", "remote")):
                self._reject("direct_selected_type", "Required direct path selected a relay")
        elif scenario in {"turn_udp", "turn_tcp", "turn_tls", "impaired"}:
            protocol = "udp" if scenario == "impaired" else scenario.removeprefix("turn_")
            if pair.get("local", {}).get("type") != "relay" or pair.get("relay_protocol") != protocol:
                self._reject("relay_selected_protocol", "TURN advertisement/configuration does not prove selected client protocol")
        counters = value.get("application")
        if (not isinstance(counters, dict) or set(counters) != set(APPLICATION)
                or any(type(count) is not int or count < 0 for count in counters.values())):
            self._reject("application_counters", "Native packet counters are unavailable")
        if not token(pair.get("token"), 32):
            self._reject("selected_pair_identity", "Selected pair identity is unavailable")
        self._rejection = None
        return value


def selection(value):
    """Never serialize raw endpoint tuples, resource names or relay sockets."""
    pair = value["pair"]
    return {"service": digest(value["service_incarnation"]), "profile": digest(value["profile_incarnation"]),
            "resource": digest([value["logical_session"], value["resource"], value["adapter_epoch"]]),
            "pair": digest(pair["token"]), "sequence": value["sample_sequence"],
            "local_type": pair["local"]["type"], "remote_type": pair["remote"]["type"],
            "relay_protocol": pair["relay_protocol"], "application": dict(value["application"]),
            "selected_pair_rtt_ms": pair["rtt_ms"],
            "adopted": value["adopted"], "attached": value["attached"], "messaging_ready": value["messaging_ready"]}


def traffic(before, after):
    for name in ("service_incarnation", "profile_incarnation", "resource", "logical_session", "adapter_epoch"):
        if before[name] != after[name]:
            raise ValueError("Traffic evidence crossed a native resource or service epoch")
    if before["pair"]["token"] != after["pair"]["token"] or after["sample_sequence"] <= before["sample_sequence"]:
        raise ValueError("Traffic evidence crossed its selected pair")
    delta = {name: after["application"][name] - before["application"][name] for name in APPLICATION}
    if any(count < 0 for count in delta.values()) or not all(delta[name] > 0 for name in
            ("enqueued_packets", "enqueued_bytes", "received_packets", "received_bytes")):
        raise ValueError("Authenticated message/receipt exchange lacks correlated native packet counters")
    return delta


def _require(condition, message):
    if not condition: raise ValueError(message)


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 3600000


def _selection(value, scenario=None):
    fields = {"service", "profile", "resource", "pair", "sequence", "local_type", "remote_type", "relay_protocol",
              "application", "selected_pair_rtt_ms", "adopted", "attached", "messaging_ready"}
    _require(isinstance(value, dict) and set(value) == fields, "Native selection projection is incomplete")
    _require(all(token(value[key], 64) for key in ("service", "profile", "resource", "pair"))
        and type(value["sequence"]) is int and value["sequence"] > 0
        and all(value[key] is True for key in ("adopted", "attached", "messaging_ready")), "Native selection lacks exact identity or readiness")
    _require(isinstance(value["application"], dict) and set(value["application"]) == set(APPLICATION)
        and all(type(count) is int and count >= 0 for count in value["application"].values()), "Native packet counters are invalid")
    _require(value["selected_pair_rtt_ms"] is None or _number(value["selected_pair_rtt_ms"]), "Native RTT observation is invalid")
    _require(value["local_type"] in {"host", "srflx", "prflx", "relay"}
        and value["remote_type"] in {"host", "srflx", "prflx", "relay"}
        and value["relay_protocol"] in {"udp", "tcp", "tls", "unknown", "not_applicable"}, "Native selected path category is invalid")
    if scenario == "direct":
        _require(value["local_type"] != "relay" and value["remote_type"] != "relay"
            and value["relay_protocol"] == "not_applicable", "Direct qualification selected a relay")
    elif scenario is not None:
        protocol = "udp" if scenario == "impaired" else scenario.removeprefix("turn_")
        _require(value["local_type"] == "relay" and value["relay_protocol"] == protocol,
                 "TURN client protocol was not actually selected")


def _delta(record, scenario=None):
    before, after = record["before"], record["after"]
    _selection(before, scenario)
    _selection(after, scenario)
    _require(all(before[key] == after[key] for key in ("service", "profile", "resource", "pair"))
        and after["sequence"] > before["sequence"], "Native traffic crossed a selected resource or epoch")
    expected = {name: after["application"][name] - before["application"][name] for name in APPLICATION}
    _require(record["native_delta"] == expected and all(value >= 0 for value in expected.values())
        and all(expected[name] > 0 for name in ("enqueued_packets", "enqueued_bytes", "received_packets", "received_bytes")),
        "Native message/receipt traffic lacks actual correlated packet deltas")


def _message(value, identities):
    _require(isinstance(value, dict) and set(value) == {"outbound", "inbound", "authenticated_receipt", "inbound_records", "outbound_records", "receipt_roundtrip_ms"},
             "Authenticated message inventory is incomplete")
    _require(value["authenticated_receipt"] is True and type(value["inbound_records"]) is int and value["inbound_records"] == 1
        and type(value["outbound_records"]) is int and value["outbound_records"] == 1 and _number(value["receipt_roundtrip_ms"]),
        "Messages duplicated or did not produce authenticated receipts")
    for key in ("outbound", "inbound"):
        _require(token(value[key], 64) and value[key] not in identities, "Message identities were reused")
        identities.add(value[key])


def verify_report(record, source, tree, role, *, workload="full"):
    plan = required_workload(workload)
    fields = {"v", "passed", "evidence_level", "role", "scope", "workload", "context", "source_commit", "source_tree", "platform", "preflight", "artifacts", "execution"}
    _require(isinstance(record, dict) and set(record) == fields and type(record["v"]) is int and record["v"] == 1
        and record["passed"] is True and record["evidence_level"] == plan["level"] and record["scope"] == plan["scope"]
        and record["workload"] == workload
        and record["role"] == role and role in {"windows", "android"}
        and record["source_commit"] == source and record["source_tree"] == tree, "Native interop report has wrong source, scope, role or outcome")
    context = record["context"]
    _require(isinstance(context, dict) and set(context) == {"repository", "repository_id", "run_id", "run_attempt", "source_commit"}
        and context["source_commit"] == source and isinstance(context["repository"], str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", context["repository"]) is not None
        and all(type(context[name]) is int and context[name] > 0 for name in ("repository_id", "run_id", "run_attempt")),
        "Native interop workflow context is incomplete")
    expected_platform = {"windows": True} if role == "windows" else {"emulated": True, "abi": "x86_64", "kvm": True}
    _require(record["platform"] == expected_platform and all(type(record["platform"][key]) is type(value) for key, value in expected_platform.items()),
             "Native role did not execute on its actual required platform")
    preflight = record["preflight"]
    _require(isinstance(preflight, dict) and set(preflight) == {"turn_advertised_transports", "mailbox_protocol", "mailbox_writes_enabled", "scope"}
        and preflight["turn_advertised_transports"] == ["tcp", "tls", "udp"] and type(preflight["mailbox_protocol"]) is int
        and preflight["mailbox_protocol"] == 2 and preflight["mailbox_writes_enabled"] is True
        and preflight["scope"] == "outbound health and advertisement only; no allocation or selected path", "Required production services were unavailable")
    artifacts = record["artifacts"]
    _require(isinstance(artifacts, dict) and artifacts and all(token(value, 64) for value in artifacts.values()), "Native artifacts are not digest-bound")
    if role == "windows":
        _require(set(artifacts) == {"sidecar_sha256", "build_input_sha256", "build_manifest_sha256"}, "Frozen Windows binary/build evidence is incomplete")
    else:
        from android_qualification import APKS, CORE_APKS, CONSUMER_ARTIFACTS, INDEPENDENT_ARTIFACTS, ROOT
        _require(set(artifacts) == {path.relative_to(ROOT).as_posix() for path in (*APKS, *CORE_APKS, *CONSUMER_ARTIFACTS, *INDEPENDENT_ARTIFACTS)},
                 "Android interop does not identify all previously qualified APK/AAR inputs")
    execution = record["execution"]
    _require(isinstance(execution, dict) and set(execution) == {"identity", "scenarios", "receipt_iterations", "processes_started", "forced_exits", "clean_exits", "webview_processes", "cleanup", "final_host_accounting"}
        and token(execution["identity"], 64) and execution["cleanup"] == "passed", "Native execution or exact cleanup is incomplete")
    cold_starts = (plan["iterations"] - 1) // plan["cold_start_every"] + 1
    for field, count in (("processes_started", cold_starts + 1), ("forced_exits", cold_starts), ("clean_exits", 1), ("webview_processes", 0)):
        _require(type(execution[field]) is int and execution[field] == count, "Periodic process restart/clean exit inventory differs")
    accounting(execution["final_host_accounting"], empty=True)
    cases = execution["scenarios"]
    _require(isinstance(cases, list) and [(item.get("scenario"), item.get("initiator")) for item in cases if isinstance(item, dict)] == list(plan["paths"]), "Required native path/initiator matrix is incomplete")
    identities = set()
    for case in cases:
        scenario = case["scenario"]
        _require(set(case) == {"scenario", "initiator", "supervisor_pairing", "before", "after", "native_delta", "messages", "impairment", "negative", "retired_host_accounting", "owner_retirement_acknowledged"}, "Native case contains unexpected or missing fields")
        _require(case["owner_retirement_acknowledged"] is True, "Native case lacks positive owner retirement acknowledgment")
        pairing = case["supervisor_pairing"]
        _require(isinstance(pairing, dict) and set(pairing) == {"operation", "role", "state", "transferred_cancel_preserves_carrier"}
            and token(pairing["operation"], 64) and pairing["role"] == ("offer" if role == case["initiator"] else "answer")
            and pairing["state"] == "transferred" and pairing["transferred_cancel_preserves_carrier"] is True,
            "Initial pairing did not use the supervisor-owned role and exact custody transfer")
        accounting(case["retired_host_accounting"], empty=True)
        _delta(case, scenario)
        _require(isinstance(case["messages"], list) and len(case["messages"]) == (20 if scenario == "impaired" else 1), "Native receipt workload is incomplete")
        for message in case["messages"]: _message(message, identities)
        negative = case["negative"]
        if scenario in {"turn_tcp", "turn_tls", "impaired"}:
            _require(isinstance(negative, dict) and set(negative) == {"blocked_packets", "delivered_while_blocked", "delivered_after_restore", "kernel_protocol", "kernel_target", "outbound", "inbound"}
                and negative["delivered_while_blocked"] is False and negative["delivered_after_restore"] is True,
                "Selected TURN transport lacks its blocked-path negative control")
            if role == "android":
                target = negative["kernel_target"]
                expected_kind = "uid_udp_all_destinations" if scenario == "impaired" else "uid_tcp_turn_destination_set"
                _require(type(negative["blocked_packets"]) is int and negative["blocked_packets"] > 0
                    and negative["kernel_protocol"] == ("udp" if scenario == "impaired" else "tcp")
                    and type(target) is dict and set(target) == {"kind", "digest", "rule_count"}
                    and target["kind"] == expected_kind and token(target["digest"], 64)
                    and type(target["rule_count"]) is int
                    and (target["rule_count"] == 2 if scenario == "impaired" else 1 <= target["rule_count"] <= 16),
                    "TURN negative control lacks actual scoped kernel drops")
            else:
                _require(negative["blocked_packets"] is None and negative["kernel_protocol"] is None and negative["kernel_target"] is None,
                         "Windows role cannot claim Android kernel counters")
            for name in ("outbound", "inbound"):
                _require(token(negative[name], 64) and negative[name] not in identities, "Negative control reused a message")
                identities.add(negative[name])
        else: _require(negative is None, "Unexpected negative-control claim")
        impairment = case["impairment"]
        if scenario == "impaired" and role == "android":
            _require(isinstance(impairment, dict) and set(impairment) == {"kind", "delay_ms_each_way", "jitter_ms_each_way", "loss_percent_each_way", "added_nominal_rtt_ms", "link_scope", "loss_observed", "counters"}
                and impairment["kind"] == "android_emulator_linux_kernel_tc_netem" and impairment["delay_ms_each_way"] == 75
                and impairment["jitter_ms_each_way"] == 10 and impairment["loss_percent_each_way"] == 0.1 and impairment["added_nominal_rtt_ms"] == 150
                and impairment["link_scope"] == "isolated_emulator_route", "Declared Linux-kernel impairment profile differs")
            counters = impairment["counters"]
            _require(isinstance(counters, dict) and set(counters) == {"egress", "ingress"}, "Kernel impairment lacks both directions")
            for values in counters.values():
                _require(isinstance(values, dict) and set(values) == {"bytes", "packets", "dropped"}
                    and all(type(count) is int and count >= 0 for count in values.values())
                    and values["bytes"] > 0 and values["packets"] > 0, "Kernel impairment did not carry actual native packets")
            _require(impairment["loss_observed"] is (sum(values["dropped"] for values in counters.values()) > 0)
                and case["before"]["selected_pair_rtt_ms"] is not None and case["after"]["selected_pair_rtt_ms"] is not None,
                "Impairment loss/actual selected-pair RTT evidence is incomplete")
        else: _require(impairment is None, "Unexecuted role cannot claim kernel impairment counters")
    iterations = execution["receipt_iterations"]
    _require(isinstance(iterations, list) and len(iterations) == plan["iterations"], "Required receipt iterations are incomplete")
    previous = None
    services = set()
    baseline = None
    for index, item in enumerate(iterations):
        _require(isinstance(item, dict) and set(item) == {"iteration", "cold_start", "native_resources", "warm_baseline_resources", "previous_service", "current_service", "identity", "before", "after", "native_delta", "message", "host_accounting", "warm_baseline_host_accounting"}
            and type(item["iteration"]) is int and item["iteration"] == index + 1
            and item["cold_start"] is (index % plan["cold_start_every"] == 0) and item["identity"] == execution["identity"], "Receipt iteration or periodic cold-start schedule differs")
        for key in ("previous_service", "current_service"): _require(token(item[key], 64), "Service epoch is missing")
        if previous is not None: _require(item["previous_service"] == previous, "Receipt iterations crossed an unreported runtime")
        else: services.add(item["previous_service"])
        if item["cold_start"]:
            _require(item["current_service"] not in services, "Cold start reused a service incarnation")
            services.add(item["current_service"])
        else: _require(item["current_service"] == item["previous_service"], "Warm iteration silently restarted its host")
        previous = item["current_service"]
        if baseline is None: baseline = item["warm_baseline_resources"]
        _require(type(baseline) is int and baseline > 0 and type(item["native_resources"]) is int
            and item["native_resources"] == item["warm_baseline_resources"] == baseline, "Native resources departed from the warm baseline")
        current_counts = accounting(item["host_accounting"])
        warm_counts = accounting(item["warm_baseline_host_accounting"])
        _require(current_counts == warm_counts and current_counts["active_count"] > 0
            and current_counts["creating_count"] == current_counts["retiring_count"] == 0,
            "Actual native reservations departed from their quiescent warm baseline")
        if index:
            _require(warm_counts == accounting(iterations[0]["warm_baseline_host_accounting"]), "Warm native baseline was replaced during soak")
        _delta(item)
        _require(item["before"]["service"] == item["current_service"], "Receipt traffic belongs to the old process")
        _message(item["message"], identities)
    return record


def verify_pair(windows, android, source, tree, *, context=None, workload="full"):
    verify_report(windows, source, tree, "windows", workload=workload)
    verify_report(android, source, tree, "android", workload=workload)
    _require(windows["context"] == android["context"] and windows["execution"]["identity"] != android["execution"]["identity"],
             "Native peers used another run/attempt or the same profile identity")
    if context is not None:
        _require(windows["context"] == context, "Native peer evidence belongs to another workflow run or attempt")
    def paired(left, right):
        _require(left["outbound"] == right["inbound"] and left["inbound"] == right["outbound"], "Peer reports do not identify the same actual native messages")
    for left, right in zip(windows["execution"]["scenarios"], android["execution"]["scenarios"]):
        for sent, received in zip(left["messages"], right["messages"]): paired(sent, received)
        if left["negative"] is not None: paired(left["negative"], right["negative"])
    for left, right in zip(windows["execution"]["receipt_iterations"], android["execution"]["receipt_iterations"]):
        paired(left["message"], right["message"])
    return windows, android
