import os
import queue
import time
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
        "stale_activation_rejected", "live_revocation_offline",
    ))


@pytest.mark.integration
@pytest.mark.parametrize("activate", [False, True])
def test_native_carrier_authorization_expiry_closes_process(activate):
    native = os.environ.get("MESH_DIRECT_PROOF_BINARY")
    if os.environ.get("MESH_CHAT_RUN_DIRECT_FABRIC_TESTS") != "1" or not native:
        pytest.skip("Requires the GitHub-built native carrier")
    peers = [{"incoming": queue.Queue(maxsize=128), "outgoing": queue.Queue(maxsize=128)} for _ in range(2)]
    # Longer active-case lifetime permits handshake scheduling on CI. Neither
    # test closes stdin nor sends cancellation: exit must follow native expiry.
    carrier = PacketCarrier(peers, Path(native).resolve(), expires_at=time.time() + (6 if activate else 3))
    try:
        if activate:
            # This focused native lifecycle probe acts as the trusted controller;
            # the separate real-service topology verifies signed authorization.
            carrier.start(["authorized local descriptor A", "authorized local descriptor B"])
        code = carrier.process.wait(timeout=10)
        assert (code == 0) == activate
        assert carrier.stop.wait(timeout=2)
        assert all(peer["incoming"].get(timeout=2) is None for peer in peers)
    finally:
        carrier.close()
