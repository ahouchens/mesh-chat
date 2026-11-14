"""The first cold probe has a manual route and cannot replace qualification."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"


def read(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_manual_parent_uses_same_run_producers_and_distinct_pair_checker():
    workflow = read("native-interop-b8-diagnostic.yml")
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch"}
    assert set(workflow["jobs"]) == {"verification", "android", "native_interop", "b8_pair_check"}
    assert workflow["jobs"]["verification"]["uses"] == "./.github/workflows/ci.yml"
    assert workflow["jobs"]["android"]["uses"] == "./.github/workflows/android-webrtc.yml"
    native = workflow["jobs"]["native_interop"]
    assert native["needs"] == ["verification", "android"]
    assert "needs.verification.result == 'success'" in native["if"]
    assert "needs.android.result == 'success'" in native["if"]
    assert native["uses"] == "./.github/workflows/native-interop.yml"
    assert native["with"] == {"workload": "b8_first_cold"}
    assert native["permissions"] == {"contents": "read", "actions": "read"}
    pair = workflow["jobs"]["b8_pair_check"]
    assert pair["needs"] == ["verification", "android", "native_interop"]
    assert pair["if"] == "${{ !cancelled() }}"
    assert pair["runs-on"] == "ubuntu-latest"
    steps = pair["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v7")
    assert checkout["with"]["fetch-depth"] == 0
    downloads = [step for step in steps if step.get("uses") == "actions/download-artifact@v4"]
    assert len(downloads) == 2 and all(step["continue-on-error"] is True for step in downloads)
    for role, step in zip(("windows", "android"), downloads):
        assert step["with"]["name"] == (
            "native-interop-b8-first-cold-" + role
            + "-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}")
        assert step["with"]["path"] == "dist/qualification/native-interop-b8"
    checker = next(step for step in steps if "check_native_interop_b8_diagnostic.py" in step.get("run", ""))
    assert checker["if"] == "${{ !cancelled() }}"
    for flag, value in (("--expected-source", '"${{ github.sha }}"'),
                        ("--windows-report", "dist/qualification/native-interop-b8/native-interop-b8-first-cold-windows.json"),
                        ("--android-report", "dist/qualification/native-interop-b8/native-interop-b8-first-cold-android.json"),
                        ("--output", "dist/reports/native-interop-b8-first-cold-pair.json")):
        assert flag + " " + value in checker["run"]
    upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == (
        "native-interop-b8-first-cold-summary-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}")
    assert all(path in upload["with"]["path"] for path in (
        "dist/reports/native-interop-b8-first-cold-pair.json",
        "dist/qualification/native-interop-b8/native-interop-b8-first-cold-windows.json",
        "dist/qualification/native-interop-b8/native-interop-b8-first-cold-android.json"))


def test_role_jobs_keep_original_artifact_bindings_and_select_separate_diagnostic_reports():
    workflow = read("native-interop.yml")
    assert set(workflow["jobs"]) == {"native_windows_peer", "native_android_peer"}
    for role, job in (("windows", workflow["jobs"]["native_windows_peer"]),
                      ("android", workflow["jobs"]["native_android_peer"])):
        assert "needs" not in job
        action = next(step for step in job["steps"] if step.get("uses") == "./scripts/native-interop-artifact")
        assert action["with"] == {"role": role, "workload": "${{ inputs.workload }}"}
        source_name = "native-windows-tested-${{ github.sha }}" if role == "windows" else "android-webrtc-debug"
        assert any(step.get("with", {}).get("name") == source_name
                   for step in job["steps"] if step.get("uses") == "actions/download-artifact@v4")
        upload = next(step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4")
        assert upload["if"] == "always()"
        assert "format('native-interop-" + role + "-{0}', github.sha)" in upload["with"]["name"]
        assert "native-interop-b8-first-cold-" + role + "-{0}-{1}-{2}" in upload["with"]["name"]
        assert "'dist/reports/native-interop-" + role + ".json'" in upload["with"]["path"]
        assert "'dist/reports/native-interop-b8-first-cold-" + role + ".json'" in upload["with"]["path"]
    gate = (WORKFLOWS / "connection-qualification.yml").read_text(encoding="utf-8")
    assert "b8_first_cold" not in gate and "native-interop-b8-first-cold" not in gate
