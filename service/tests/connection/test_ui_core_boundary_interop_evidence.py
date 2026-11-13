"""Selected-path evidence is fresh, current, packet-correlated and redacted."""

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_evidence as evidence
from mesh_chat.native_path_evidence import candidate, pair_token

REQUEST = "c" * 32


def test_impaired_pair_accepts_truthful_link_and_uid_udp_scope():
    from test_ui_core_boundary_interop_controller import interop_reports
    windows, android = interop_reports()
    impaired = android["execution"]["scenarios"][-1]
    evidence.verify_pair(windows, android, "a" * 40, "b" * 40)
    impaired["negative"]["kernel_target"].update(kind="pid_udp_socket_flow", rule_count=1)
    with pytest.raises(ValueError):
        evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


def test_zero_native_counts_cannot_replace_positive_owner_retirement_acknowledgment():
    from test_ui_core_boundary_interop_controller import interop_reports
    windows, android = interop_reports()
    for report in (windows, android):
        for case in report["execution"]["scenarios"]: case.pop("owner_retirement_acknowledged", None)
    with pytest.raises(ValueError): evidence.verify_pair(windows, android, "a" * 40, "b" * 40)


@pytest.mark.parametrize("role", [0, 1])
@pytest.mark.parametrize("case_index", range(6))
def test_every_case_requires_its_own_retained_owner_ack(role, case_index):
    from test_ui_core_boundary_interop_controller import interop_reports
    reports = interop_reports()
    reports[role]["execution"]["scenarios"][case_index].pop("owner_retirement_acknowledged")
    with pytest.raises(ValueError): evidence.verify_pair(*reports, "a" * 40, "b" * 40)


@pytest.mark.parametrize("case_index,value", [(0, False), (1, None), (2, 0), (3, 1), (4, "true"), (5, {}), (5, [])])
def test_retained_owner_ack_requires_exact_true_and_contains_no_correlation_ids(case_index, value):
    from test_ui_core_boundary_interop_controller import interop_reports
    reports = interop_reports()
    reports[0]["execution"]["scenarios"][case_index]["owner_retirement_acknowledged"] = value
    with pytest.raises(ValueError): evidence.verify_pair(*reports, "a" * 40, "b" * 40)
    reports = interop_reports()
    reports[0]["execution"]["scenarios"][case_index]["request_id"] = "PRIVATE_REQUEST"
    with pytest.raises(ValueError): evidence.verify_pair(*reports, "a" * 40, "b" * 40)


@pytest.fixture
def sample():
    local = candidate("192.0.2.1", 1234, "relay", "udp")
    remote = candidate("198.51.100.2", 4321, "relay", "udp")
    pair = {"token": pair_token("a" * 32, "physical", local, remote), "local": local, "remote": remote,
            "nominated": True, "relay_protocol": "udp", "relay_socket": None,
            "bytes_sent": None, "bytes_received": None, "rtt_ms": None}
    # Private producer DTO double; actual native/service composition is a separate control.
    value = {"v": 1, "resource": "physical", "adapter_epoch": "a" * 32, "sample_sequence": 1,
        "sampled_at_ms": 100000, "sample_request": REQUEST, "status": "selected", "ice_state": "completed",
        "dtls_state": "connected", "channel_state": "open", "pair": pair,
        "application": dict.fromkeys(evidence.APPLICATION, 0), "availability": {
            "selected_pair": True, "relay_protocol": True, "relay_socket": False, "pair_bytes": False, "rtt": False}}
    value.update(service_incarnation="service", profile_incarnation="profile", logical_session="logical",
                 qualification_only=True, valid_for_ms=2000, sample_elapsed_ms=1,
                 adopted=True, attached=True, messaging_ready=True)
    inventory = {"service_incarnation": "service", "profile_incarnation": "profile", "resources": [
        {"logical_session": "logical", "physical_resource": "physical", "adopted": True}]}
    return value, inventory


def tracker():
    return evidence.Samples(monotonic=lambda: 10)


def test_fresh_native_monotonic_timestamp_does_not_require_wall_epoch(sample):
    value, inventory = sample
    value["sampled_at_ms"] = 6000  # Producer-local origin, unrelated to controller wall time.
    samples = tracker()
    assert samples.consume(value, inventory, 9.9, sample_request=REQUEST, ready=True, scenario="turn_udp") == value


def test_actual_private_observation_shape_proves_selected_protocol_then_exports_only_categories(sample):
    value, inventory = sample
    assert tracker().consume(value, inventory, 9.9, sample_request=REQUEST, ready=True, scenario="turn_udp") == value
    projected = evidence.selection(value)
    text = json.dumps(projected)
    assert "192.0.2.1" not in text and "198.51.100.2" not in text
    assert "physical" not in text and "logical" not in text
    assert "sample_request" not in projected and REQUEST not in text
    assert projected["relay_protocol"] == "udp" and projected["messaging_ready"] is True
    assert all(len(projected[name]) == 64 for name in ("service", "profile", "resource", "pair"))


@pytest.mark.parametrize("fault", ["service", "profile", "physical", "logical", "epoch", "sequence", "ttl",
    "negative_timestamp", "overbounded_timestamp", "slow_sample", "not_selected", "ice", "dtls", "channel", "adopted", "attached", "ready", "protocol", "no_relay", "counters"])
def test_stale_foreign_unready_or_merely_advertised_path_cannot_qualify(sample, fault):
    value, inventory = sample
    if fault in {"service", "profile"}: value[fault + "_incarnation"] = "other"
    elif fault == "physical": value["resource"] = "different"
    elif fault == "logical": value["logical_session"] = "different"
    elif fault == "epoch": value["adapter_epoch"] = "invalid"
    elif fault == "sequence": value["sample_sequence"] = 0
    elif fault == "ttl": value["valid_for_ms"] = 600000
    elif fault == "negative_timestamp": value["sampled_at_ms"] = -1
    elif fault == "overbounded_timestamp": value["sampled_at_ms"] = 2**53
    elif fault == "slow_sample": value["sample_elapsed_ms"] = 2001
    elif fault == "not_selected": value["status"] = "unsupported"
    elif fault in {"ice", "dtls", "channel"}: value[fault + "_state"] = "closed"
    elif fault in {"adopted", "attached"}: value[fault] = False
    elif fault == "ready": value["messaging_ready"] = False
    elif fault == "protocol": value["pair"]["relay_protocol"] = "tcp"
    elif fault == "no_relay": value["pair"]["local"]["type"] = "srflx"
    else: value["application"]["received_packets"] = None
    with pytest.raises(ValueError): tracker().consume(value, inventory, 9.9, sample_request=REQUEST, ready=True, scenario="turn_udp")


def test_local_request_deadline_prevents_slow_or_replayed_first_sample(sample):
    value, inventory = sample
    with pytest.raises(ValueError): tracker().consume(value, inventory, 7.9, sample_request=REQUEST)
    observer = tracker()
    observer.consume(value, inventory, 9.9, sample_request=REQUEST)
    with pytest.raises(ValueError, match="sequence"): observer.consume(value, inventory, 9.9, sample_request=REQUEST)


def test_relay_only_setting_cannot_qualify_direct_and_udp_cannot_qualify_tcp_or_tls(sample):
    value, inventory = sample
    for scenario in ("direct", "turn_tcp", "turn_tls"):
        with pytest.raises(ValueError): tracker().consume(value, inventory, 9.9, sample_request=REQUEST, scenario=scenario)


REJECTION_CASES = ["sample_object", "qualification_scope", "sample_version", "service_incarnation", "profile_incarnation",
    "adapter_epoch", "sample_request", "sample_sequence", "sample_ttl", "sample_timestamp", "request_elapsed",
    "service_elapsed", "sample_resource", "sample_replay", "sample_readiness", "selected_transport",
    "direct_selected_type", "relay_selected_protocol", "application_counters", "selected_pair_identity"]


@pytest.mark.parametrize("reason", REJECTION_CASES)
def test_every_sample_rejection_has_only_same_exception_literal_reason(sample, reason):
    value, inventory = sample
    samples, requested, scenario = tracker(), 9.9, "turn_udp"
    if reason == "sample_object": value = None
    elif reason == "qualification_scope": value["qualification_only"] = False
    elif reason == "sample_version": value["v"] = True
    elif reason in {"service_incarnation", "profile_incarnation"}: value[reason] = "PRIVATE_OTHER_RUNTIME"
    elif reason == "adapter_epoch": value["adapter_epoch"] = "PRIVATE_EPOCH"
    elif reason == "sample_request": value.pop("sample_request")
    elif reason == "sample_sequence": value["sample_sequence"] = True
    elif reason == "sample_ttl": value["valid_for_ms"] = 2000.0
    elif reason == "sample_timestamp": value["sampled_at_ms"] = -1
    elif reason == "request_elapsed": requested = 7.9
    elif reason == "service_elapsed": value["sample_elapsed_ms"] = 2001
    elif reason == "sample_resource": value["resource"] = "PRIVATE_FOREIGN_RESOURCE"
    elif reason == "sample_replay": samples.consume(value, inventory, requested, sample_request=REQUEST)
    elif reason == "sample_readiness": value["adopted"] = False
    elif reason == "selected_transport": value["dtls_state"] = "closed"
    elif reason == "direct_selected_type": scenario = "direct"
    elif reason == "relay_selected_protocol": scenario = "turn_tcp"
    elif reason == "application_counters": value["application"]["received_bytes"] = True
    elif reason == "selected_pair_identity": value["pair"]["token"] = "PRIVATE_PAIR_TOKEN"
    with pytest.raises(ValueError) as failure:
        samples.consume(value, inventory, requested, sample_request=REQUEST, ready=True, scenario=scenario)
    assert type(failure.value) is ValueError and samples.failure_reason(failure.value) == reason
    foreign = ValueError("PRIVATE_UPSTREAM_ERROR")
    foreign.sample_rejection_reason = reason
    assert samples.failure_reason(foreign) is None
    assert evidence.SAMPLE_REJECTION_REASONS == frozenset(REJECTION_CASES)


class RequestString(str): pass


@pytest.mark.parametrize("sample_request", [None, b"c" * 32, [], {}, True, "c" * 31, "c" * 33, "C" * 32, "g" * 32, RequestString(REQUEST)])
def test_expected_request_must_be_exact_bounded_lowercase_hex(sample, sample_request):
    value, inventory = sample
    samples = tracker()
    with pytest.raises(ValueError) as failure: samples.consume(value, inventory, 9.9, sample_request=sample_request)
    assert samples.failure_reason(failure.value) == "sample_request" and samples.previous == {}


@pytest.mark.parametrize("echo", [None, [], {}, False, 1, b"c" * 32, "d" * 32, "C" * 32, RequestString(REQUEST)])
def test_foreign_cached_or_malformed_first_reply_cannot_qualify(sample, echo):
    value, inventory = sample
    value["sample_request"] = echo
    samples = tracker()
    with pytest.raises(ValueError) as failure: samples.consume(value, inventory, 9.9, sample_request=REQUEST)
    assert samples.failure_reason(failure.value) == "sample_request" and samples.previous == {}


def test_prior_inflight_response_cannot_answer_new_invocation_even_as_first_sample(sample):
    value, inventory = sample
    samples = tracker()
    with pytest.raises(ValueError) as failure:
        samples.consume(value, inventory, 9.9, sample_request="d" * 32)
    assert samples.failure_reason(failure.value) == "sample_request" and samples.previous == {}


@pytest.mark.parametrize("timestamp", [0, 1, 6000, 1700000000000, 2**53 - 1])
def test_timestamp_is_bounded_opaque_metadata_with_no_epoch_assumption(sample, timestamp):
    value, inventory = sample
    value["sampled_at_ms"] = timestamp
    assert tracker().consume(value, inventory, 8, sample_request=REQUEST) is value


@pytest.mark.parametrize("field,value", [("sampled_at_ms", True), ("sampled_at_ms", 1.0),
    ("sampled_at_ms", 2**53), ("sample_elapsed_ms", -1), ("sample_elapsed_ms", True), ("sample_elapsed_ms", 2001)])
def test_timestamp_and_service_elapsed_keep_strict_bounds(sample, field, value):
    sample[0][field] = value
    with pytest.raises(ValueError): tracker().consume(*sample, 9.9, sample_request=REQUEST)


@pytest.mark.parametrize("requested", [7.999, 10.001])
def test_request_roundtrip_cannot_be_late_or_from_future(sample, requested):
    with pytest.raises(ValueError): tracker().consume(*sample, requested, sample_request=REQUEST)


@pytest.mark.parametrize("field", ["requested", "returned"])
@pytest.mark.parametrize("invalid", [True, False, None, "10", [], {}, float("nan"), float("inf"), -float("inf"), 1j,
    10**1000, -10**1000])
def test_local_clock_inputs_are_exact_finite_numbers_without_bool_coercion(sample, field, invalid):
    calls = []
    def monotonic():
        calls.append(1)
        return invalid if field == "returned" else 10
    samples = evidence.Samples(monotonic=monotonic)
    with pytest.raises(ValueError) as failure:
        samples.consume(*sample, invalid if field == "requested" else 9.9, sample_request=REQUEST)
    assert samples.failure_reason(failure.value) == "request_elapsed" and calls == [1]


def test_fractional_over_two_second_rtt_cannot_be_truncated_into_the_budget(sample):
    samples = evidence.Samples(monotonic=lambda: 10.0001)
    with pytest.raises(ValueError) as failure: samples.consume(*sample, 8, sample_request=REQUEST)
    assert samples.failure_reason(failure.value) == "request_elapsed"


def test_success_clears_old_reason_and_unknown_internal_literal_is_never_selected(sample):
    value, inventory = sample
    samples = tracker()
    with pytest.raises(ValueError) as failure: samples.consume(value, inventory, 9.9, sample_request="d" * 32)
    assert samples.failure_reason(failure.value) == "sample_request"
    samples.consume(value, inventory, 9.9, sample_request=REQUEST)
    assert samples.failure_reason(failure.value) is None
    samples._rejection = failure.value, "PRIVATE_FORGED_REASON"
    assert samples.failure_reason(failure.value) is None


def test_receipt_traffic_requires_both_native_packet_directions_on_one_exact_pair(sample):
    before, _ = sample
    after = copy.deepcopy(before)
    after["sample_sequence"] += 1
    for name in evidence.APPLICATION:
        after["application"][name] += 2
    assert evidence.traffic(before, after)["received_packets"] == 2
    for fault in ("service_incarnation", "profile_incarnation", "resource", "logical_session", "adapter_epoch"):
        changed = copy.deepcopy(after)
        changed[fault] = "other"
        with pytest.raises(ValueError): evidence.traffic(before, changed)
    after["application"]["received_packets"] = 0
    with pytest.raises(ValueError): evidence.traffic(before, after)
