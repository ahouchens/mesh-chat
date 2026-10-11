from __future__ import annotations

from pathlib import Path

from mesh_chat.workspace_service import (
    MAX_NOTIFICATION_BATCH,
    MAX_NOTIFICATION_NATIVE_BYTES,
    MAX_NOTIFICATION_QUEUE,
)


def test_increment_15_benchmark_freezes_scale_and_notification_limits() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "workspace_mobile_lifecycle_benchmark.py"
    ).read_text(encoding="utf-8")
    assert "50_000" in source
    assert 'fixture["members"] == 8' in source
    assert 'fixture["channels"] == 32' in source
    assert "historical=True" in source
    assert "whole_collection_scans" in source
    assert "samples < LIMITS" in source
    assert MAX_NOTIFICATION_QUEUE == 128
    assert MAX_NOTIFICATION_BATCH == 16
    assert MAX_NOTIFICATION_NATIVE_BYTES == 1024
