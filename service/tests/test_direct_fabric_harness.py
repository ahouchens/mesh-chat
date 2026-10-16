import os
from pathlib import Path

import pytest

from tools.direct_fabric_harness import run


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
    ))
