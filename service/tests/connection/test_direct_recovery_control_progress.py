"""Replacement requires both authenticated recovery and ordinary signed control ingress."""

import copy

import pytest

import test_direct_recovery_pipeline as pipeline


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    result = Clock()
    monkeypatch.setattr(pipeline.time, "monotonic", result.monotonic)
    monkeypatch.setattr(pipeline.time, "sleep", result.sleep)
    return result


def observation(received, *, certificate="fresh", pending=0):
    return {"pending": pending, "paths": [{"recovery": True, "certificate": certificate}],
            "controls": {"sent": 4, "send_failed": 0, "received": received, "rejected": 0}}


def peers_for(clock, samples, *, ready=True, advance=None):
    peers = pipeline.Peers.__new__(pipeline.Peers)
    requests = []
    cursor = [0]

    def command(index, name, **_):
        requests.append((index, name))
        return [{"state": "connected", "authenticated_peer_live": True, "rns_ready": ready}]

    def call(index, name, **_):
        requests.append((index, name))
        sample = samples[min(cursor[0], len(samples) - 1)]
        cursor[0] += 1
        if advance is not None:
            clock.now = advance(cursor[0])
        return copy.deepcopy(sample)

    peers.command, peers.call = command, call
    return peers, requests


def test_existing_connection_snapshot_can_precede_control_ingress(clock):
    peers, requests = peers_for(clock, [observation(3), observation(4)])
    value = peers.connected(0, previous_certificate="old")
    assert value["controls"]["received"] == 3
    assert requests.count((0, "recovery_diagnostic")) == 1


def test_replacement_waits_for_control_ingress_after_authenticated_connection(clock):
    peers, requests = peers_for(clock, [observation(3), observation(3), observation(4)])
    value = peers.connected(0, previous_certificate="old", control_receipts_before=3)
    assert value["controls"]["received"] == 4
    assert requests.count((0, "recovery_diagnostic")) == 3
    assert clock.now == pytest.approx(0.4)


@pytest.mark.parametrize("fault", ["old_certificate", "pending", "not_ready"])
def test_control_ingress_does_not_replace_authenticated_recovery(clock, fault):
    sample = observation(4, certificate="old" if fault == "old_certificate" else "fresh",
                         pending=1 if fault == "pending" else 0)
    peers, _ = peers_for(clock, [sample], ready=fault != "not_ready", advance=lambda _: 179.9)
    with pytest.raises(AssertionError):
        peers.connected(0, previous_certificate="old", control_receipts_before=3)


@pytest.mark.parametrize("received", [3, 2, True, "4", None])
def test_missing_or_invalid_control_progress_fails_within_existing_window(clock, received):
    peers, _ = peers_for(clock, [observation(received)], advance=lambda _: 179.9)
    with pytest.raises(AssertionError) as failed:
        peers.connected(0, previous_certificate="old", control_receipts_before=3)
    assert clock.now < 181
    assert "PRIVATE" not in str(failed.value)
    assert failed.value.args[0]["replacement_control"]["connection_observed"] is True


def test_control_timeout_evidence_bounds_counters_and_omits_raw_fields(clock):
    sample = observation(100000)
    sample["controls"].update(sent=100000, rejected=True, raw="PRIVATE_SDP")
    peers, _ = peers_for(clock, [sample], advance=lambda _: 179.9)
    with pytest.raises(AssertionError) as failed:
        peers.connected(0, "old", control_receipts_before=100000)
    details = failed.value.args[0]["replacement_control"]
    assert details["received_before"] == 1024 and details["received_before_capped"] is True
    assert details["counts_capped"] is True
    assert details["last_counts"] == {"sent": 1024, "send_failed": 0, "received": 1024, "rejected": None}
    assert "PRIVATE" not in str(failed.value)


@pytest.mark.parametrize("baseline", [True, -1, "3"])
def test_invalid_control_baseline_is_rejected_before_observation(clock, baseline):
    peers, requests = peers_for(clock, [observation(4)])
    with pytest.raises(ValueError):
        peers.connected(0, "old", control_receipts_before=baseline)
    assert requests == []


def test_late_positive_control_reply_cannot_extend_existing_window(clock):
    peers, requests = peers_for(clock, [observation(4)], advance=lambda _: 181)
    with pytest.raises(AssertionError):
        peers.connected(0, previous_certificate="old", control_receipts_before=3)
    assert requests == [(0, "direct_recovery_status"), (0, "recovery_diagnostic")]


def test_shared_deadline_can_shorten_control_observation(clock):
    peers, _ = peers_for(clock, [observation(4)], advance=lambda _: 11)
    with pytest.raises(AssertionError):
        peers.connected(0, previous_certificate="old", control_receipts_before=3, deadline=10)


def test_each_peer_requires_its_own_control_baseline(clock):
    peers, requests = peers_for(clock, [observation(2), observation(5), observation(6)])
    assert peers.connected(0, "old", control_receipts_before=1)["controls"]["received"] == 2
    assert peers.connected(1, "old", control_receipts_before=5)["controls"]["received"] == 6
    assert requests.count((1, "recovery_diagnostic")) == 2


def test_legacy_connection_observation_keeps_original_late_reply_behavior(clock):
    peers, requests = peers_for(clock, [observation(3)], advance=lambda _: 181)
    assert peers.connected(0, "old")["controls"]["received"] == 3
    assert len(requests) == 2
