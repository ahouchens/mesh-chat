"""Partition dispatch cannot masquerade as the fresh or restart public route."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_manual_partition_route_uses_exact_producers_owned_android_gateway_and_strict_aggregate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/public-core-partition-diagnostic.yml").read_text())
    events = workflow.get("on", workflow.get(True))
    assert events == {"workflow_dispatch": None, "push": {
        "branches": ["codex/mesh-core-integration-lead"],
        "paths": [".github/workflows/public-core-partition-diagnostic.yml"]}}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    jobs = workflow["jobs"]
    assert set(jobs) == {"verification", "android", "windows_public", "android_public", "public_pair_check"}
    assert all("github.event_name == 'workflow_dispatch'" in job["if"] for job in jobs.values())
    for name, file in (("verification", "ci.yml"), ("android", "android-webrtc.yml")):
        assert jobs[name]["uses"] == f"./.github/workflows/{file}"
        assert jobs[name]["with"] == {"public_pair_producer": True}
        assert jobs[name]["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    for role in ("windows", "android"):
        job = jobs[role + "_public"]
        assert job["needs"] == ["verification", "android"]
        assert "needs.verification.result == 'success'" in job["if"]
        assert "needs.android.result == 'success'" in job["if"]
        action = [step for step in job["steps"] if step.get("uses") == "./scripts/public-core-pair-action"]
        assert len(action) == 1 and action[0]["with"]["scenario"] == "partition"
        assert action[0]["with"]["role"] == role
        assert action[0]["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
        assert any(step.get("uses") == "actions/upload-artifact@v4"
                   and step.get("if") == "always()"
                   and step["with"]["if-no-files-found"] == "error" for step in job["steps"])
    android = jobs["android_public"]
    assert not any(step.get("uses") == "reactivecircus/android-emulator-runner@v2"
                   for step in android["steps"])
    assert any("sdkmanager" in step.get("run", "") for step in android["steps"])
    assert jobs["public_pair_check"]["needs"] == ["verification", "android", "windows_public", "android_public"]
    assert jobs["public_pair_check"]["if"] == "${{ !cancelled() && github.event_name == 'workflow_dispatch' }}"
    checker = next(step for step in jobs["public_pair_check"]["steps"]
                   if step.get("name") == "Check public partition diagnostic only")
    assert "scripts/check_public_core_partition.py" in checker["run"]
    assert checker["env"]["PUBLIC_PAIR_SCENARIO"] == "partition"
    assert checker["env"]["PUBLIC_PAIR_NEEDS"] == "${{ toJSON(needs) }}"
