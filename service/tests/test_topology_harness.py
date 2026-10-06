from __future__ import annotations

import os

import pytest

from tools.topology_harness import run


@pytest.mark.integration
def test_real_three_hop_lxmf_delivery() -> None:
    if os.environ.get("MESH_CHAT_RUN_NETWORK_TESTS") != "1":
        pytest.skip("Set MESH_CHAT_RUN_NETWORK_TESTS=1 to launch isolated peers")
    result = run(require_protected=os.environ.get("MESH_CHAT_REQUIRE_PROTECTED_STORAGE") == "1")
    assert result["route_ready"] is True
    assert result["reported_hops"] == 3
    assert result["recipient_ratchet"] is True
    assert result["signature_validated"] is True
    assert result["intermediate_plaintext_files"] == []

