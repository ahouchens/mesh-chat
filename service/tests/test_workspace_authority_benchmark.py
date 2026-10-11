from __future__ import annotations

from pathlib import Path

from tools.workspace_authority_benchmark import run


def test_increment13_authority_benchmark_schema_and_correctness(
    tmp_path: Path,
) -> None:
    result = run(tmp_path / "authority-benchmark", 2_000, 3)
    assert all(result["assertions"].values())
    assert result["fixture"]["members"] == 8
    assert result["fixture"]["channels"] == 32
    assert result["limits"]["authority_transitions"] == 8
    assert result["limits"]["offer_encoded_bytes"] == 8 * 1024
    assert result["limits"]["acceptance_encoded_bytes"] == 16 * 1024
    assert result["limits"]["bootstrap_encoded_bytes"] == 256 * 1024
    assert result["work"]["transition_count"] == 9
    assert result["work"]["duplicate_rejected"] == 3
    assert result["work"]["route_attempts"] > 0
    assert result["bytes"]["route_transfer"] > 0
