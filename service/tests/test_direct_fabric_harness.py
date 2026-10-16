import os
import queue
import time
import threading
from pathlib import Path

import pytest

from tools.direct_fabric_harness import PacketCarrier, run


@pytest.mark.integration
def test_real_services_over_private_direct_packet_carrier():
    if os.environ.get("MESH_CHAT_RUN_DIRECT_FABRIC_TESTS") != "1":
        pytest.skip("Set MESH_CHAT_RUN_DIRECT_FABRIC_TESTS=1 for the isolated packet topology")
    native = os.environ.get("MESH_DIRECT_PROOF_BINARY")
    result = run(executable=Path(native).resolve() if native else None)
    assert result["carrier"] == ("quic" if native else "source-pipes")
    assert all(result[key] for key in (
        "join_acknowledged", "admitted", "bidirectional_messages", "ratchets",
        "engine_death_offline", "isolated", "admitted_key_rotation", "endpoint_receipts",
        "stale_activation_rejected", "live_revocation_offline", "revocation_cancels_carrier", "ready_retains_answer",
    ))


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
