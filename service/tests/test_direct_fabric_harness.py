import os
import hashlib
import struct
import queue
import time
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.direct_fabric_harness import PacketCarrier, run


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["revocation", "service-crash", "engine-crash", "suspend-resume", "restart"])
def test_real_services_over_private_direct_packet_carrier(failure):
    if os.environ.get("MESH_CHAT_RUN_DIRECT_FABRIC_TESTS") != "1":
        pytest.skip("Set MESH_CHAT_RUN_DIRECT_FABRIC_TESTS=1 for the isolated packet topology")
    native = os.environ.get("MESH_DIRECT_PROOF_BINARY")
    if failure == "engine-crash" and not native:
        pytest.skip("Requires the GitHub-built native carrier")
    result = run(executable=Path(native).resolve() if native else None, failure=failure)
    assert result["carrier"] == ("quic" if native else "source-pipes")
    assert all(result[key] for key in (
        "join_acknowledged", "admitted", "bidirectional_messages", "ratchets",
        "isolated", "admitted_key_rotation", "endpoint_receipts",
        "stale_activation_rejected", "ready_retains_answer", "failure_retired_adapters", "pending_admission_retired",
    ))
    assert result["failure"] == failure
    assert result["suspension_recovered"] == (failure == "suspend-resume")
    assert result["restart_recovered"] == (failure == "restart")
    assert result["engine_death_offline"] == (failure == "engine-crash")
    assert result["service_crash_cancels_carrier"] == (failure == "service-crash")
    assert result["live_revocation_offline"] == (failure == "revocation")
    assert result["revocation_cancels_carrier"] == (failure == "revocation")


@pytest.mark.integration
@pytest.mark.parametrize("activate", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_native_carrier_authorization_expiry_closes_process(activate, refresh):
    native = os.environ.get("MESH_DIRECT_PROOF_BINARY")
    if os.environ.get("MESH_CHAT_RUN_DIRECT_FABRIC_TESTS") != "1" or not native:
        pytest.skip("Requires the GitHub-built native carrier")
    peers = [{"incoming": queue.Queue(maxsize=128), "outgoing": queue.Queue(maxsize=128), "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    # Longer active-case lifetime permits handshake scheduling on CI. Neither
    # test closes stdin nor sends cancellation: exit must follow native expiry.
    carrier = PacketCarrier(peers, Path(native).resolve(), expires_at=time.time() + (6 if activate else 3))
    try:
        ready_generation = carrier.refresh_owner("authorized local descriptor B") if refresh else None
        if activate:
            # This focused native lifecycle probe acts as the trusted controller;
            # the separate real-service topology verifies signed authorization.
            carrier.start(["authorized local descriptor A", "authorized local descriptor B"],
                          ready_generation=ready_generation)
        code = carrier.process.wait(timeout=10)
        assert (code == 0) == activate
        assert carrier.stop.wait(timeout=2)
        assert all(peer["carrier_lost"].wait(timeout=2) for peer in peers)
    finally:
        carrier.close()


def test_revocation_control_survives_full_packet_queues():
    peers = [{"incoming": queue.Queue(maxsize=1), "outgoing": queue.Queue(maxsize=1),
              "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    carrier = PacketCarrier(peers, expires_at=time.time() + 30)
    for peer in peers:
        peer["incoming"].put(b"queued packet")
        peer["outgoing"].put(b"queued packet")
    try:
        carrier.start(["descriptor A", "descriptor B"])
        peers[0]["revoked"].set()
        assert carrier.cancellation_requested.wait(timeout=2)
        assert carrier.stop.wait(timeout=2)
        assert all(peer["carrier_lost"].wait(timeout=2) for peer in peers)
        assert all(peer["incoming"].get_nowait() == b"queued packet" for peer in peers)
    finally:
        carrier.close()


def test_carrier_close_signals_loss_without_packet_queue_capacity():
    peers = [{"incoming": queue.Queue(maxsize=1), "outgoing": queue.Queue(maxsize=1),
              "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    carrier = PacketCarrier(peers, expires_at=time.time() + 30)
    for peer in peers:
        peer["incoming"].put(b"queued packet")
    carrier.close()
    carrier.close()  # Repeated teardown remains terminal and safe.
    assert all(peer["carrier_lost"].is_set() for peer in peers)
    assert all(peer["incoming"].get_nowait() == b"queued packet" for peer in peers)


def test_ready_requires_owned_answer_and_fresh_owner_generation():
    peers = [{"incoming": queue.Queue(maxsize=1), "outgoing": queue.Queue(maxsize=1),
              "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    carrier = PacketCarrier(peers, expires_at=time.time() + 30)
    try:
        old_certificates, old_sessions = list(carrier.certificates), list(carrier.session_ids)
        with pytest.raises(ValueError, match="refreshed owner"):
            carrier.start(["ready", "answer"], ready_generation=2)
        generation = carrier.refresh_owner("answer")
        assert generation == 2
        assert carrier.certificates[0] != old_certificates[0]
        assert carrier.session_ids[0] != old_sessions[0]
        assert carrier.certificates[1] == old_certificates[1]
        assert carrier.session_ids[1] == old_sessions[1]
        with pytest.raises(ValueError, match="one pending"):
            carrier.refresh_owner("replacement")
        with pytest.raises(ValueError, match="exact owned Answer"):
            carrier.start(["ready", "replacement"], ready_generation=2)
        with pytest.raises(ValueError, match="fresh owner generation"):
            carrier.start(["ready", "answer"], ready_generation=1)
        carrier.start(["ready", "answer"], ready_generation=2)
        with pytest.raises(ValueError, match="already consumed"):
            carrier.start(["ready", "answer"], ready_generation=2)
    finally:
        carrier.close()


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["answer-mismatch", "ready-generation", "repeated-refresh", "packet-before-ready", "oversized-frame"])
def test_native_ready_rejects_conflicting_or_misphased_control(fault):
    native = os.environ.get("MESH_DIRECT_PROOF_BINARY")
    if os.environ.get("MESH_CHAT_RUN_DIRECT_FABRIC_TESTS") != "1" or not native:
        pytest.skip("Requires the GitHub-built native carrier")
    peers = [{"incoming": queue.Queue(maxsize=1), "outgoing": queue.Queue(maxsize=1),
              "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    carrier = PacketCarrier(peers, Path(native).resolve(), expires_at=time.time() + 30)
    digest = lambda text: hashlib.sha256(text.encode("utf-8")).digest()
    try:
        carrier.refresh_owner("answer")
        if fault == "answer-mismatch":
            side, payload = 2, digest("ready") + digest("other answer") + struct.pack("!Q", 2)
        elif fault == "ready-generation":
            side, payload = 2, digest("ready") + digest("answer") + struct.pack("!Q", 3)
        elif fault == "repeated-refresh":
            side, payload = 2, b"R" + carrier.session_ids[0].bytes + struct.pack("!Q", 3) + digest("answer")
        elif fault == "packet-before-ready":
            side, payload = 0, b"unauthorized packet"
        else:
            side, payload = 2, b"x" * 517
        # Bypass the controller's preflight checks to test the native boundary.
        carrier._write(side, payload)
        assert carrier.process.wait(timeout=5) != 0
        assert all(peer["carrier_lost"].wait(timeout=2) for peer in peers)
    finally:
        carrier.close()


def test_crashed_carrier_closes_all_streams_when_dead_pipe_flush_fails():
    peers = [{"incoming": queue.Queue(maxsize=1), "outgoing": queue.Queue(maxsize=1),
              "revoked": threading.Event(), "carrier_lost": threading.Event()} for _ in range(2)]
    carrier = PacketCarrier(peers, expires_at=time.time() + 30)
    closed = []
    class Stream:
        def __init__(self, name):
            self.name = name
        def close(self):
            closed.append(self.name)
            if self.name == "stdin":
                raise OSError(22, "dead reader flush")
    carrier.process = SimpleNamespace(poll=lambda: 1, returncode=1,
        stdin=Stream("stdin"), stdout=Stream("stdout"), stderr=Stream("stderr"))
    carrier.close()
    assert closed == ["stdin", "stdout", "stderr"]
    assert all(peer["carrier_lost"].is_set() for peer in peers)
    with pytest.raises(RuntimeError, match="gracefully"):
        carrier.close(require_graceful=True)
    assert closed == ["stdin", "stdout", "stderr"] * 2
