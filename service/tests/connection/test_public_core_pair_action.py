"""The separate Node Action admits only its exact public-pair role."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest
import yaml


SOURCE = Path(__file__).resolve().parents[3] / "scripts/public-core-pair-action"


def input_key(name):
    metadata = yaml.safe_load((SOURCE / "action.yml").read_text(encoding="utf-8"))
    assert name in metadata["inputs"]
    return "INPUT_" + name.replace(" ", "_").upper()


def action(tmp_path, *, timeout_ms=None):
    root = tmp_path / "candidate"
    directory = root / "scripts/public-core-pair-action"
    directory.mkdir(parents=True)
    text = (SOURCE / "action.mjs").read_text(encoding="utf-8")
    if timeout_ms is not None:
        text = text.replace("const CONTROLLER_MS = 1_500_000;", f"const CONTROLLER_MS = {timeout_ms};")
    script = directory / "action.mjs"
    script.write_text(text, encoding="utf-8")
    controller = root / "scripts/public_core_pair_controller.py"
    controller.write_text('''
import argparse, json, os, pathlib, sys, time
p=argparse.ArgumentParser()
p.add_argument("--role", required=True)
p.add_argument("--expected-source", required=True)
p.add_argument("--output", required=True)
p.add_argument("--disposable-emulator-serial")
a=p.parse_args()
if os.environ.get("MESH_TEST_SLEEP"):
    time.sleep(5)
path=pathlib.Path(a.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({"role":a.role,"source":a.expected_source,"output":str(path),
    "serial":a.disposable_emulator_serial,"git_token":bool(os.environ.get("GITHUB_TOKEN")),
    "runtime_token":bool(os.environ.get("ACTIONS_RUNTIME_TOKEN"))}))
print("PRIVATE_PRODUCT_OUTPUT")
print("PRIVATE_EXCEPTION_OUTPUT", file=sys.stderr)
raise SystemExit(7 if os.environ.get("MESH_TEST_FAIL") else 0)
''', encoding="utf-8")
    (root / "scripts/public_core_restart_controller.py").write_text(
        controller.read_text().replace('"role":a.role',
            '"scenario":os.environ.get("PUBLIC_PAIR_SCENARIO"),"role":a.role'), encoding="utf-8")
    return script, root


def environment(role):
    return {**os.environ, input_key("role"): role, input_key("python"): sys.executable,
            input_key("disposable-emulator-serial"): "emulator-5554" if role == "android" else "",
            "GITHUB_JOB": "android_public" if role == "android" else "windows_public",
            "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": "example/mesh",
            "GITHUB_REPOSITORY_ID": "123", "GITHUB_RUN_ID": "456",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_TOKEN": "PRIVATE_TEST_GITHUB_TOKEN",
            "ACTIONS_RUNTIME_TOKEN": "PRIVATE_TEST_RUNTIME_TOKEN"}


def invoke(script, env):
    node = os.environ.get("MESH_NODE") or shutil.which("node")
    assert node
    return subprocess.run([node, str(script)], env=env, capture_output=True, text=True, timeout=15)


def test_action_metadata_is_an_independent_node24_entry():
    value = yaml.safe_load((SOURCE / "action.yml").read_text(encoding="utf-8"))
    assert value["runs"] == {"using": "node24", "main": "action.mjs"}
    assert set(value["inputs"]) == {"role", "python", "disposable-emulator-serial", "scenario"}
    assert value["inputs"]["scenario"]["default"] == "fresh"
    assert value["inputs"]["role"]["required"] is True


@pytest.mark.parametrize("role", ["windows", "android"])
def test_real_action_invokes_only_exact_role_controller_and_discards_output(tmp_path, role):
    script, root = action(tmp_path)
    result = invoke(script, environment(role))
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == f"Public Core pair {role} controller passed.\n"
    report = json.loads((root / f"dist/reports/public-core-pair-{role}.json").read_text())
    assert report == {"role": role, "source": "a" * 40,
                      "output": str(root / f"dist/reports/public-core-pair-{role}.json"),
                      "serial": "emulator-5554" if role == "android" else None,
                      "git_token": True, "runtime_token": True}
    assert "PRIVATE" not in result.stdout + result.stderr


@pytest.mark.parametrize("field,bad", [
    ("INPUT_SCENARIO", "../other"), ("INPUT_SCENARIO", "restart"),
    ("INPUT_ROLE", "native"), ("GITHUB_JOB", "native_windows_peer"),
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_ACTIONS", "false"),
    ("GITHUB_SHA", "A" * 40), ("GITHUB_RUN_ID", "0"),
    ("GITHUB_REPOSITORY", "../mesh"),
    ("GITHUB_RUN_ID", "999999999999999999999"),
    ("GITHUB_TOKEN", ""), ("ACTIONS_RUNTIME_TOKEN", ""),
    (input_key("disposable-emulator-serial"), "emulator-5556"),
])
def test_action_rejects_wrong_windows_admission_before_controller(tmp_path, field, bad):
    script, root = action(tmp_path)
    env = environment("windows")
    env[field] = bad
    result = invoke(script, env)
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout == "Public Core pair controller admission failed.\n"
    assert not (root / "dist/reports/public-core-pair-windows.json").exists()


def test_android_requires_pinned_disposable_emulator(tmp_path):
    script, root = action(tmp_path)
    env = environment("android")
    env[input_key("disposable-emulator-serial")] = ""
    result = invoke(script, env)
    assert result.returncode == 1 and result.stdout == "Public Core pair controller admission failed.\n"
    assert not (root / "dist/reports/public-core-pair-android.json").exists()


def test_android_rejects_underscore_alias_without_declared_input(tmp_path):
    script, root = action(tmp_path)
    env = environment("android")
    env[input_key("disposable-emulator-serial")] = ""
    env["INPUT_DISPOSABLE_EMULATOR_SERIAL"] = "emulator-5554"
    result = invoke(script, env)
    assert result.returncode == 1 and result.stdout == "Public Core pair controller admission failed.\n"
    assert not (root / "dist/reports/public-core-pair-android.json").exists()


def test_child_failure_does_not_expose_product_output(tmp_path):
    script, root = action(tmp_path)
    env = {**environment("windows"), "MESH_TEST_FAIL": "1"}
    result = invoke(script, env)
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout == "Public Core pair windows controller failed.\n"
    assert (root / "dist/reports/public-core-pair-windows.json").exists()


def test_missing_python_child_is_a_generic_failure(tmp_path):
    script, root = action(tmp_path)
    env = {**environment("windows"), "INPUT_PYTHON": str(root / "missing-python.exe")}
    result = invoke(script, env)
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout == "Public Core pair windows controller failed.\n"
    assert not (root / "dist/reports/public-core-pair-windows.json").exists()


def test_timeout_waits_for_exact_child_close_then_fails(tmp_path):
    script, root = action(tmp_path, timeout_ms=50)
    env = {**environment("windows"), "MESH_TEST_SLEEP": "1"}
    started = time.monotonic()
    result = invoke(script, env)
    assert time.monotonic() - started < 5
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout == "Public Core pair windows controller failed.\n"
    assert not (root / "dist/reports/public-core-pair-windows.json").exists()


@pytest.mark.parametrize("role", ["windows", "android"])
def test_restart_routes_exact_controller_and_admission_without_fresh_report(tmp_path, role):
    script, root = action(tmp_path)
    result = invoke(script, {**environment(role), "INPUT_SCENARIO": "owner_restart",
                             "PUBLIC_PAIR_SCENARIO": "untrusted-parent-value"})
    assert result.returncode == 0 and result.stderr == ""
    report = json.loads((root / f"dist/reports/public-core-restart-{role}.json").read_text())
    assert report["scenario"] == "owner_restart" and report["role"] == role
    assert report["source"] == "a" * 40
    assert report["serial"] == ("emulator-5554" if role == "android" else None)
    assert not (root / f"dist/reports/public-core-pair-{role}.json").exists()
