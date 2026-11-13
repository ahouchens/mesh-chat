"""Run the fast cross-language boundary gate before expensive package checks."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PYTHON_SELECTION = (
    "service/tests/connection/test_ui_core_boundary_requests.py",
    "service/tests/connection/test_ui_core_boundary_ci.py",
    "service/tests/connection/test_ui_core_boundary_calls.py",
    "service/tests/connection/test_ui_core_boundary_replay_authority.py",
    "service/tests/connection/test_ui_core_boundary_consent.py",
    "service/tests/connection/test_ui_core_boundary_noop_idempotency.py",
    "service/tests/connection/test_ui_core_boundary_native_evidence.py",
    "service/tests/connection/test_ui_core_boundary_composer.py",
    "service/tests/connection/test_ui_core_boundary_rendezvous.py",
    "service/tests/connection/test_ui_core_boundary_interop_artifacts.py",
    "service/tests/connection/test_ui_core_boundary_interop_preflight.py",
    "service/tests/connection/test_ui_core_boundary_runtime_materials.py",
    "service/tests/connection/test_ui_core_boundary_sdk_staging.py",
    "service/tests/connection/test_ui_core_boundary_interop_peers.py",
    "service/tests/connection/test_ui_core_boundary_interop_evidence.py",
    "service/tests/connection/test_ui_core_boundary_interop_faults.py",
    "service/tests/connection/test_ui_core_boundary_interop_path_setup.py",
    "service/tests/connection/test_ui_core_boundary_interop_controller.py",
    "service/tests/connection/test_ui_core_boundary_interop_adoption_race.py",
    "service/tests/connection/test_ui_core_boundary_interop_carrier_observation.py",
    "service/tests/connection/test_ui_core_boundary_interop_ice_observation.py",
    "service/tests/connection/test_ui_core_boundary_interop_recovery_observation.py",
)
RENDERED_CASES = {("tests/core-ui-boundary/app.test.tsx",
                   "rendered UI through the production framed Core session > " + name) for name in (
    "creates one fresh identity from rendered onboarding and resolves a lost committed reply",
    "enqueues durable text through the real serializer and service",
    "keeps accepted text cleared when the following snapshot fails",
    "retries an uncertain committed enqueue with the same key and one durable record",
    "preserves canonical workspace conversation fields from rendered channel send",
    "serializes thread_root to a real timeline query without legacy field aliases",
    "restores an unsent composer after renderer remount and real vault reopen",
    "resolves a lost draft enqueue reply after remount and vault reopen without a second send",
    "replays lost committed group creation with the original caller key and one durable group",
    "replays lost committed group send once and preserves a newer draft through actual Core",
    "restores an unsent group composer after renderer remount and real vault reopen",
    "resolves a lost group draft enqueue after remount and vault reopen without a second send",
)}


def rendered_inventory(path):
    tests = list(ET.parse(path).getroot().iter("testcase"))
    identities = [(case.get("classname"), case.get("name")) for case in tests]
    return len(identities) == len(RENDERED_CASES) and set(identities) == RENDERED_CASES


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def junit_summary(path):
    root = ET.parse(path).getroot()
    tests = list(root.iter("testcase"))
    failed = sum(test.find("failure") is not None or test.find("error") is not None for test in tests)
    skipped = sum(test.find("skipped") is not None for test in tests)
    return {"tests_executed": len(tests), "tests_failed": failed, "tests_skipped": skipped,
            "passed": bool(tests) and failed == skipped == 0 and not list(root.iter("error")),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--node", default=os.environ.get("MESH_NODE", "node"))
    args = parser.parse_args()
    reports = ROOT / "dist/reports"
    reports.mkdir(parents=True, exist_ok=True)
    output = reports / "core-ui-boundary.json"
    output.unlink(missing_ok=True)
    source = git("rev-parse", "HEAD")
    if source != args.expected_source or git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Commit all source changes before recording exact-source boundary evidence")
    version = subprocess.check_output([args.node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 20:
        raise ValueError("Boundary qualification requires Node 20 or newer")
    commands = {
        "python": [sys.executable, "tests/core-ui-boundary/run_python.py", "--source", source],
        "rendered_ui": [args.node, "node_modules/vitest/vitest.mjs", "run", "--config",
                        "tests/core-ui-boundary/vitest.config.ts", "--reporter=junit"],
    }
    results = {}
    started = time.monotonic()
    environment = {**os.environ, "MESH_BOUNDARY_PYTHON": sys.executable, "PYTHONUTF8": "1",
                   "PYTHONDONTWRITEBYTECODE": "1"}
    for name, command in commands.items():
        junit = reports / f"core-ui-boundary-{name}.xml"
        junit.unlink(missing_ok=True)
        command += (["--junit", str(junit)] if name == "python" else [f"--outputFile={junit}"])
        begin = time.monotonic()
        status = subprocess.run(command, cwd=ROOT, env=environment, timeout=180).returncode
        summary = junit_summary(junit) if junit.exists() else {"passed": False, "missing_junit": True}
        if name == "rendered_ui" and (not junit.exists() or not rendered_inventory(junit)):
            summary.update(passed=False, incomplete_required_inventory=True)
        if name == "python" and junit.with_suffix(".inventory.json").exists():
            summary["inventory_sha256"] = hashlib.sha256(junit.with_suffix(".inventory.json").read_bytes()).hexdigest()
        results[name] = {**summary, "exit_code": status, "wall_seconds": time.monotonic() - begin}
    passed = all(result["passed"] and result["exit_code"] == 0 for result in results.values())
    result = {"v": 1, "source_commit": source, "source_tree": git("rev-parse", "HEAD^{tree}"),
              "evidence_level": "rendered_ui_and_in_process_service", "passed": passed,
              "scope": "Real serializer/framing/parser/session/vault; substituted Tauri invoke; no native or physical qualification",
              "wall_seconds": time.monotonic() - started, "node": version, "suites": results}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
