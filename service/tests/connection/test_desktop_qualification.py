"""A native qualification gate cannot accept stale, incomplete or failed evidence."""

import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


gate = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/test_desktop_transport.py"))


def record():
    return {"v": 1, "source_commit": "a" * 40,
            "evidence_level": "windows_webview2_private_host_component",
            "result": {"ok": True, "checks": sorted(gate["CHECKS"])}}


def verify(value, exit_code=0):
    return gate["verified_report"](SimpleNamespace(stdout=json.dumps(value), returncode=exit_code), "a" * 40)


def test_only_complete_success_from_the_required_revision_is_evidence():
    assert verify(record()) == record()
    with pytest.raises(RuntimeError, match="did not all pass"):
        verify(record(), exit_code=1)


@pytest.mark.parametrize("change", [
    {"source_commit": "b" * 40}, {"evidence_level": "simulated"}, {"v": True}, {"passed": True},
    {"result": {"ok": True, "checks": ["offer"]}},
    {"result": {"ok": True, "checks": sorted(gate["CHECKS"]) + ["offer"]}},
    {"result": {"ok": False, "checks": sorted(gate["CHECKS"])}},
])
def test_stale_incompatible_or_partial_evidence_is_rejected(change):
    with pytest.raises(RuntimeError):
        verify({**record(), **change})


@pytest.mark.parametrize("stdout", ["", json.dumps(record()) + "\n" + json.dumps(record())])
def test_missing_or_ambiguous_execution_is_not_a_passing_skip(stdout):
    with pytest.raises(RuntimeError, match="one result"):
        gate["verified_report"](SimpleNamespace(stdout=stdout, returncode=0), "a" * 40)
