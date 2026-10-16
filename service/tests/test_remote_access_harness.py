from __future__ import annotations

import os

import pytest

from tools.remote_access_harness import run


@pytest.mark.integration
def test_real_personal_and_workspace_remote_access_topology() -> None:
    if os.environ.get("MESH_CHAT_RUN_REMOTE_NETWORK_TESTS") != "1":
        pytest.skip(
            "Set MESH_CHAT_RUN_REMOTE_NETWORK_TESTS=1 to launch the isolated access point"
        )
    result = run()
    assert result["relay_only"] is True
    assert result["preview_did_not_connect"] is True
    assert result["personal_v2"] is True
    assert result["personal_consent_disclosed"] is True
    assert result["personal_received"] is True
    assert result["personal_delivered"] is True
    assert result["workspace_v2"] is True
    assert result["workspace_consent_disclosed"] is True
    assert result["workspace_joined"] is True
    assert result["workspace_join_acknowledged"] is True
    assert result["workspace_received"] is True
    assert result["workspace_direct_received"] is True
    assert result["alex_route"] == "remote"
    assert result["blair_route"] == "remote"
