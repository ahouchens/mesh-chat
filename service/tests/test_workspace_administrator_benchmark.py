from __future__ import annotations

from pathlib import Path

from tools.workspace_administrator_benchmark import run
from tools.workspace_retention_benchmark import _unix_max_rss_bytes


def test_increment12_administrator_benchmark_schema_and_correctness(
    tmp_path: Path,
) -> None:
    result = run(tmp_path / "administrator-benchmark", 2_000, 3)
    assert all(result["assertions"].values())
    assert result["fixture"]["members"] == 8
    assert result["fixture"]["channels"] == 32
    assert result["fixture"]["private_control_chains"] == 4
    assert result["limits"]["request_encoded_bytes"] == 4 * 1024
    assert result["limits"]["decision_encoded_bytes"] == 48 * 1024
    assert result["work"]["approved"] >= 3
    assert result["work"]["declined"] == 1
    assert result["work"]["stale"] >= 1
    assert result["work"]["superseded"] >= 1
    assert result["work"]["expired"] >= 1
    assert result["work"]["conflicting_probes"] == 1


def test_unix_peak_rss_is_normalized_to_bytes() -> None:
    assert _unix_max_rss_bytes(1_024, "linux") == 1_024 * 1_024
    assert _unix_max_rss_bytes(1_024, "freebsd14") == 1_024 * 1_024
    assert _unix_max_rss_bytes(1_024, "darwin") == 1_024
