import json

import pytest

from tools import direct_nat_harness as harness


def test_failed_nat_trial_preserves_failure_evidence_and_does_not_retry(tmp_path, monkeypatch):
    calls = []
    success = {"passed": True, "connected": False, "coordinated_checks": False}
    failure = {"passed": False, "connected": False, "coordinated_checks": True,
               "failure_reason": "unexpected_topology_result", "native_ports": [40000, 40001],
               "router_diagnostics": {"rb": {"udp_mappings": "test-only mapping"}}}
    def trial(*args):
        calls.append(args)
        if len(calls) == 1:
            return success
        raise harness.TrialFailure(failure)
    monkeypatch.setattr(harness, "trial", trial)
    report = tmp_path / "evidence.json"
    with pytest.raises(harness.TrialFailure, match="unexpected_topology_result"):
        harness.run_trials("test-dispatcher", report, [(False, "", False), (True, "", False), (True, "", False)])
    evidence = json.loads(report.read_text())
    assert evidence["trials"] == [success, failure]
    assert evidence["expected_trial_count"] == 3
    assert not evidence["physical_evidence"]
    assert len(calls) == 2
