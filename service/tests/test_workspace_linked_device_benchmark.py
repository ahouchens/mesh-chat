from __future__ import annotations

from pathlib import Path

from mesh_chat.workspace_protocol import MAX_ACTIVE_DEVICES, MAX_DEVICE_LINK_BYTES


def test_increment_14_benchmark_covers_the_release_topology() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "workspace_linked_device_benchmark.py"
    ).read_text(encoding="utf-8")
    assert "50_000" in source
    assert 'scaled["fixture"]["members"] == 8' in source
    assert 'scaled["fixture"]["channels"] == 32' in source
    assert 'protocol["work"]["devices"] == 24' in source
    assert 'protocol["work"]["remote_fanout_legs"] == 23' in source
    assert "private_identity_copies" in source
    assert "samples < LIMITS" in source


def test_increment_14_protocol_series_hits_caps_without_copying_identity() -> None:
    import sys

    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    try:
        import workspace_linked_device_benchmark as benchmark

        result = benchmark.protocol_series(3)
    finally:
        sys.path.remove(str(tools))
    assert result["work"]["devices"] == MAX_ACTIVE_DEVICES
    assert result["work"]["remote_fanout_legs"] == MAX_ACTIVE_DEVICES - 1
    assert result["work"]["private_identity_copies"] == 0
    assert result["bytes"]["acceptance_max"] <= MAX_DEVICE_LINK_BYTES
