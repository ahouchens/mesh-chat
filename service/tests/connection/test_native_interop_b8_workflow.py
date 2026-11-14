"""The first cold probe has a manual route and cannot replace qualification."""

import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"


def read(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def selected(expression, event, diagnostic):
    value = expression.removeprefix("${{").removesuffix("}}").strip()
    value = value.replace("github.event_name", repr(event))
    value = value.replace("inputs.b8_first_cold_diagnostic", repr(diagnostic))
    value = value.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
    value = re.sub(r"!(?!=)", " not ", value)
    return eval(value, {"__builtins__": {}}, {})


def test_manual_parent_uses_same_run_producers_and_distinct_pair_checker():
    workflow = read("native-interop-b8-diagnostic.yml")
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_call", "workflow_dispatch"}
    assert set(workflow["jobs"]) == {"verification", "android", "native_interop", "b8_pair_check"}
    assert workflow["jobs"]["verification"]["uses"] == "./.github/workflows/ci.yml"
    assert workflow["jobs"]["android"]["uses"] == "./.github/workflows/android-webrtc.yml"
    assert workflow["jobs"]["verification"]["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert workflow["jobs"]["android"]["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert workflow["jobs"]["verification"]["with"] == {"b8_diagnostic_producer": True}
    assert workflow["jobs"]["android"]["with"] == {"b8_diagnostic_producer": True}
    native = workflow["jobs"]["native_interop"]
    assert native["needs"] == ["verification", "android"]
    assert "needs.verification.result == 'success'" in native["if"]
    assert "needs.android.result == 'success'" in native["if"]
    assert native["uses"] == "./.github/workflows/native-interop.yml"
    assert native["with"] == {"workload": "b8_first_cold"}
    assert native["permissions"] == {"contents": "read", "actions": "read"}
    pair = workflow["jobs"]["b8_pair_check"]
    assert pair["needs"] == ["verification", "android", "native_interop"]
    assert pair["if"] == "${{ !cancelled() && github.event_name == 'workflow_dispatch' }}"
    assert pair["runs-on"] == "ubuntu-latest"
    steps = pair["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v7")
    assert checkout["with"]["fetch-depth"] == 0
    setup_index = next(index for index, step in enumerate(steps)
                       if step.get("uses") == "actions/setup-python@v7")
    install_index = next(index for index, step in enumerate(steps)
                         if step.get("run") == "python -m pip install --disable-pip-version-check -r service/requirements-dev.lock")
    checker_index = next(index for index, step in enumerate(steps)
                         if "check_native_interop_b8_diagnostic.py" in step.get("run", ""))
    assert setup_index < install_index < checker_index
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


def test_existing_manual_dispatch_routes_diagnostic_without_running_required_gate():
    workflow = read("connection-qualification.yml")
    dispatch = workflow.get("on", workflow.get(True))["workflow_dispatch"]
    assert dispatch["inputs"]["b8_first_cold_diagnostic"]["default"] is False
    jobs = workflow["jobs"]
    diagnostic = jobs["b8_first_cold_diagnostic"]
    assert diagnostic["uses"] == "./.github/workflows/native-interop-b8-diagnostic.yml"
    assert diagnostic["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["native_interop"]["uses"] == "./.github/workflows/native-interop.yml"
    assert set(jobs["gate"]["needs"]) >= {"plan", "verification", "android", "native_interop"}
    for event in ("workflow_dispatch", "push", "workflow_call"):
        assert selected(jobs["plan"]["if"], event, False) is True
        assert selected(jobs["gate"]["if"], event, False) is True
        assert selected(diagnostic["if"], event, False) is False
    assert selected(jobs["plan"]["if"], "workflow_dispatch", True) is False
    assert selected(jobs["gate"]["if"], "workflow_dispatch", True) is False
    assert selected(diagnostic["if"], "workflow_dispatch", True) is True
    assert selected(jobs["plan"]["if"], "push", True) is True
    assert selected(jobs["gate"]["if"], "push", True) is True
    assert selected(diagnostic["if"], "push", True) is False


def test_manual_diagnostic_has_isolated_parent_concurrency_without_cancellation():
    concurrency = read("connection-qualification.yml")["concurrency"]
    group = concurrency["group"]
    assert group.endswith("-${{ github.ref }}")
    group_prefix = group.removesuffix("-${{ github.ref }}")
    cancel = concurrency["cancel-in-progress"]
    for event in ("workflow_dispatch", "push", "workflow_call"):
        assert selected(group_prefix, event, False) == "connection-qualification"
        assert selected(cancel, event, False) is True
    assert selected(group_prefix, "workflow_dispatch", True) == "connection-b8-diagnostic"
    assert selected(cancel, "workflow_dispatch", True) is False
    assert selected(group_prefix, "push", True) == "connection-qualification"
    assert selected(cancel, "push", True) is True


def test_paired_producers_have_distinct_concurrency_without_changing_defaults():
    for workflow_name, default_group in (
        ("ci.yml", "ci-${{ github.workflow }}-${{ github.ref }}"),
        ("android-webrtc.yml", None),
    ):
        workflow = read(workflow_name)
        call_input = workflow.get("on", workflow.get(True))["workflow_call"]["inputs"]
        assert call_input["b8_diagnostic_producer"]["default"] is False
        group = workflow["concurrency"]["group"]
        suffix = "${{ inputs.b8_diagnostic_producer && '-b8-first-cold' || '' }}"
        assert group.endswith(suffix)
        if default_group is not None:
            assert group.removesuffix(suffix) == default_group
        else:
            assert group.removesuffix(suffix).startswith("android-webrtc-${{ github.ref }}")
        assert workflow["concurrency"]["cancel-in-progress"] == "${{ !inputs.b8_diagnostic_producer }}"


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
    qualification = read("connection-qualification.yml")["jobs"]
    assert qualification["native_interop"]["with"]["workload"] == "${{ needs.plan.outputs.native_workload }}"
    assert "native-interop-b8-first-cold" not in json.dumps(qualification["gate"])


def test_android_producer_restores_rust_cache_without_saving_after_toolchain_cleanup():
    steps = read("android-webrtc.yml")["jobs"]["android"]["steps"]
    rust_index = next(index for index, step in enumerate(steps)
                      if step.get("uses") == "Swatinem/rust-cache@v2")
    cleanup_index = next(index for index, step in enumerate(steps)
                         if step.get("name") == "Free disk for the emulator system image")
    assert rust_index < cleanup_index
    assert 'rm -rf "$HOME/.rustup"' in steps[cleanup_index]["run"]
    assert steps[rust_index]["with"]["save-if"] == "false"
    assert "cache-on-failure" not in steps[rust_index]["with"]
