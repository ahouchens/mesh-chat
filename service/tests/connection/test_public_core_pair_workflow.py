"""The fresh public pair runs only through its isolated manual route."""

from pathlib import Path
import os
import re
import shutil
import subprocess

import pytest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def value(expression, event, **inputs):
    text = expression.removeprefix("${{").removesuffix("}}").strip()
    text = text.replace("github.event_name", repr(event))
    text = re.sub(r"\binputs\.([a-z0-9_]+)\b", lambda match: repr(inputs.get(match[1], False)), text)
    text = text.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    return eval(text, {"__builtins__": {}}, {})


def named_step(job, name):
    return next(step for step in job["steps"] if step.get("name") == name)


def test_parent_manual_modes_are_mutually_exclusive_and_do_not_run_required_gate():
    parent = workflow("connection-qualification.yml")
    dispatch = parent.get("on", parent.get(True))["workflow_dispatch"]["inputs"]
    assert dispatch["public_pair_diagnostic"]["type"] == "boolean"
    assert dispatch["public_pair_diagnostic"]["default"] is False
    jobs = parent["jobs"]
    assert jobs["public_pair_diagnostic"]["uses"] == "./.github/workflows/public-core-pair-diagnostic.yml"
    assert jobs["public_pair_diagnostic"]["permissions"] == {"contents": "read", "actions": "read"}
    names = ("diagnostic_conflict", "plan", "b8_first_cold_diagnostic", "public_pair_diagnostic", "gate")
    for event in ("workflow_dispatch", "push", "workflow_call"):
        for b8 in (False, True):
            for public in (False, True):
                flags = {"b8_first_cold_diagnostic": b8, "public_pair_diagnostic": public}
                selected = {name for name in names if value(jobs[name]["if"], event, **flags)}
                expected = ({"diagnostic_conflict"} if b8 and public else
                            {"b8_first_cold_diagnostic"} if b8 else
                            {"public_pair_diagnostic"} if public else {"plan", "gate"})
                if event != "workflow_dispatch":
                    expected = {"plan", "gate"}
                assert selected == expected
                cancellation = value(parent["concurrency"]["cancel-in-progress"], event, **flags)
                assert cancellation is (event != "workflow_dispatch" or not (b8 or public))


def test_public_diagnostic_uses_two_producers_before_concurrent_pair_roles():
    paired = workflow("public-core-pair-diagnostic.yml")
    assert set(paired.get("on", paired.get(True))) == {"workflow_call"}
    assert paired["concurrency"]["cancel-in-progress"] is False
    jobs = paired["jobs"]
    assert set(jobs) == {"verification", "android", "windows_public", "android_public", "public_pair_check"}
    for name, file in (("verification", "ci.yml"), ("android", "android-webrtc.yml")):
        assert jobs[name]["uses"] == f"./.github/workflows/{file}"
        assert jobs[name]["with"] == {"public_pair_producer": True}
        producer = workflow(file)
        inputs = producer.get("on", producer.get(True))["workflow_call"]["inputs"]
        assert inputs["public_pair_producer"]["default"] is False
        assert "inputs.public_pair_producer && '-public-pair'" in producer["concurrency"]["group"]
        assert "inputs.public_pair_producer" in producer["concurrency"]["cancel-in-progress"]
    for role in ("windows_public", "android_public"):
        job = jobs[role]
        assert job["needs"] == ["verification", "android"]
        assert "needs.verification.result == 'success'" in job["if"]
        assert "needs.android.result == 'success'" in job["if"]
        assert job["runs-on"] == ("windows-latest" if role == "windows_public" else "ubuntu-latest")


def test_role_downloads_run_action_with_exact_emulator_lifetime_and_retain_provenance():
    jobs = workflow("public-core-pair-diagnostic.yml")["jobs"]
    windows = jobs["windows_public"]
    downloads = [step for step in windows["steps"] if step.get("uses") == "actions/download-artifact@v4"]
    assert [(step["with"]["name"], step["with"]["path"]) for step in downloads] == [
        ("desktop-transport-${{ github.sha }}", "dist/reports"),
        ("native-windows-tested-${{ github.sha }}", "."),
    ]
    action = named_step(windows, "Run public Windows pair role with Actions artifact runtime")
    assert action["uses"] == "./scripts/public-core-pair-action"
    assert action["with"] == {"role": "windows"}
    assert action["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    android = jobs["android_public"]
    download = named_step(android, "Download exact-source installed Android consumer and distribution report")
    assert download["with"] == {"name": "android-webrtc-debug", "path": "."}
    emulator = named_step(android, "Run public Android pair role while the emulator is alive")
    assert emulator["uses"] == "reactivecircus/android-emulator-runner@v2"
    assert emulator["with"]["emulator-port"] == 5554
    assert emulator["with"]["script"] == (
        "env 'INPUT_DISPOSABLE-EMULATOR-SERIAL=emulator-5554' "
        "node scripts/public-core-pair-action/action.mjs")
    assert emulator["env"] == {
        "GITHUB_TOKEN": "${{ github.token }}", "INPUT_ROLE": "android", "INPUT_PYTHON": "python"}
    for role, report in (("windows", "windows-independent-bootstrap.json"),
                         ("android", "android-independent-distribution.json")):
        upload = named_step(jobs[f"{role}_public"], f"Retain public {role.title()} role and original producer report")
        assert upload["if"] == "always()"
        assert upload["with"]["name"] == (
            f"public-core-pair-{role}-${{{{ github.sha }}}}-${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}")
        assert f"dist/reports/public-core-pair-{role}.json" in upload["with"]["path"]
        assert f"dist/reports/{report}" in upload["with"]["path"]


def test_checker_receives_four_exact_needs_and_original_producer_reports():
    job = workflow("public-core-pair-diagnostic.yml")["jobs"]["public_pair_check"]
    assert job["needs"] == ["verification", "android", "windows_public", "android_public"]
    assert job["if"] == "${{ !cancelled() && github.event_name == 'workflow_dispatch' }}"
    downloads = [step for step in job["steps"] if step.get("uses") == "actions/download-artifact@v4"]
    assert len(downloads) == 2 and all(step["continue-on-error"] is True for step in downloads)
    checker = named_step(job, "Check public fresh-pair diagnostic only")
    assert checker["env"] == {"PUBLIC_PAIR_NEEDS": "${{ toJSON(needs) }}"}
    for flag, path in (("windows-report", "windows/public-core-pair-windows.json"),
                       ("android-report", "android/public-core-pair-android.json"),
                       ("windows-bootstrap", "windows/windows-independent-bootstrap.json"),
                       ("android-distribution", "android/android-independent-distribution.json")):
        assert f"--{flag} dist/qualification/public-pair/{path}" in checker["run"]
    assert '--expected-source "${{ github.sha }}"' in checker["run"]
    assert "--output dist/reports/public-core-pair-summary.json" in checker["run"]
    summary = named_step(job, "Retain distinct public fresh-pair diagnostic")
    assert summary["if"] == "always()"
    assert "dist/reports/public-core-pair-summary.json" in summary["with"]["path"]


def test_android_emulator_shell_restores_declared_hyphenated_input_after_shell_boundary():
    emulator = named_step(workflow("public-core-pair-diagnostic.yml")["jobs"]["android_public"],
                          "Run public Android pair role while the emulator is alive")
    script = emulator["with"]["script"]
    shell = shutil.which("sh")
    if shell is None:
        git_dash = Path("C:/Program Files/Git/usr/bin/dash.exe")
        shell = str(git_dash) if git_dash.is_file() else None
    if shell is None:
        pytest.skip("POSIX shell unavailable on this host")
    environment = dict(os.environ)
    if os.name == "nt":
        # Git-for-Windows dash needs its POSIX tools explicitly on PATH.
        environment["PATH"] = "/usr/bin:" + environment["PATH"]
    environment["GITHUB_TOKEN"] = "test-github-token"
    environment["ACTIONS_RUNTIME_TOKEN"] = "test-runtime-token"
    environment["INPUT_DISPOSABLE-EMULATOR-SERIAL"] = "emulator-5554"
    inherited = subprocess.run([shell, "-c", "/usr/bin/env"], env=environment,
                               capture_output=True, text=True, timeout=10, check=True)
    assert "INPUT_DISPOSABLE-EMULATOR-SERIAL=emulator-5554" not in inherited.stdout
    environment.pop("INPUT_DISPOSABLE-EMULATOR-SERIAL")
    command = script.replace("node scripts/public-core-pair-action/action.mjs", "/usr/bin/env")
    restored = subprocess.run([shell, "-c", command], env=environment,
                              capture_output=True, text=True, timeout=10, check=True)
    assert "INPUT_DISPOSABLE-EMULATOR-SERIAL=emulator-5554" in restored.stdout
    assert "GITHUB_TOKEN=test-github-token" in restored.stdout
    assert "ACTIONS_RUNTIME_TOKEN=test-runtime-token" in restored.stdout
