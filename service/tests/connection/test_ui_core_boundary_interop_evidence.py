"""Selected-path evidence is fresh, current, packet-correlated and redacted."""

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_interop_evidence as evidence
from mesh_chat.native_path_evidence import observation, candidate, pair_token


@pytest.fixture
def sample():
    local = candidate("192.0.2.1", 1234, "relay", "udp")
    remote = candidate("198.51.100.2", 4321, "relay", "udp")
    pair = {"token": pair_token("a" * 32, "physical", local, remote), "local": local, "remote": remote,
            "nominated": True, "relay_protocol": "udp", "relay_socket": None,
            "bytes_sent": None, "bytes_received": None, "rtt_ms": None}
    value = observation("physical", "a" * 32, 1, 100000, status="selected", ice_state="completed",
        dtls_state="connected", channel_state="open", pair=pair)
    value.update(service_incarnation="service", profile_incarnation="profile", logical_session="logical",
                 qualification_only=True, valid_for_ms=2000, sample_elapsed_ms=1,
                 adopted=True, attached=True, messaging_ready=True)
    inventory = {"service_incarnation": "service", "profile_incarnation": "profile", "resources": [
        {"logical_session": "logical", "physical_resource": "physical", "adopted": True}]}
    return value, inventory


def tracker():
    return evidence.Samples(clock=lambda: 100, monotonic=lambda: 10)


def test_actual_private_observation_shape_proves_selected_protocol_then_exports_only_categories(sample):
    value, inventory = sample
    assert tracker().consume(value, inventory, 9.9, ready=True, scenario="turn_udp") == value
    projected = evidence.selection(value)
    text = json.dumps(projected)
    assert "192.0.2.1" not in text and "198.51.100.2" not in text
    assert "physical" not in text and "logical" not in text
    assert projected["relay_protocol"] == "udp" and projected["messaging_ready"] is True
    assert all(len(projected[name]) == 64 for name in ("service", "profile", "resource", "pair"))


@pytest.mark.parametrize("fault", ["service", "profile", "physical", "logical", "epoch", "sequence", "ttl",
    "old_timestamp", "future_timestamp", "slow_sample", "not_selected", "ice", "dtls", "channel", "adopted", "attached", "ready", "protocol", "no_relay", "counters"])
def test_stale_foreign_unready_or_merely_advertised_path_cannot_qualify(sample, fault):
    value, inventory = sample
    if fault in {"service", "profile"}: value[fault + "_incarnation"] = "other"
    elif fault == "physical": value["resource"] = "different"
    elif fault == "logical": value["logical_session"] = "different"
    elif fault == "epoch": value["adapter_epoch"] = "invalid"
    elif fault == "sequence": value["sample_sequence"] = 0
    elif fault == "ttl": value["valid_for_ms"] = 600000
    elif fault == "old_timestamp": value["sampled_at_ms"] = 97999
    elif fault == "future_timestamp": value["sampled_at_ms"] = 100001
    elif fault == "slow_sample": value["sample_elapsed_ms"] = 2001
    elif fault == "not_selected": value["status"] = "unsupported"
    elif fault in {"ice", "dtls", "channel"}: value[fault + "_state"] = "closed"
    elif fault in {"adopted", "attached"}: value[fault] = False
    elif fault == "ready": value["messaging_ready"] = False
    elif fault == "protocol": value["pair"]["relay_protocol"] = "tcp"
    elif fault == "no_relay": value["pair"]["local"]["type"] = "srflx"
    else: value["application"]["received_packets"] = None
    with pytest.raises(ValueError): tracker().consume(value, inventory, 9.9, ready=True, scenario="turn_udp")


def test_local_request_deadline_prevents_slow_or_replayed_first_sample(sample):
    value, inventory = sample
    with pytest.raises(ValueError): tracker().consume(value, inventory, 7.9)
    observer = tracker()
    observer.consume(value, inventory, 9.9)
    with pytest.raises(ValueError, match="sequence"): observer.consume(value, inventory, 9.9)


def test_relay_only_setting_cannot_qualify_direct_and_udp_cannot_qualify_tcp_or_tls(sample):
    value, inventory = sample
    for scenario in ("direct", "turn_tcp", "turn_tls"):
        with pytest.raises(ValueError): tracker().consume(value, inventory, 9.9, scenario=scenario)


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
