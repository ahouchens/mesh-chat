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
    environment = {**os.environ, "MESH_BOUNDARY_PYTHON": sys.executable, "PYTHONUTF8": "1"}
    for name, command in commands.items():
        junit = reports / f"core-ui-boundary-{name}.xml"
        junit.unlink(missing_ok=True)
        command += (["--junit", str(junit)] if name == "python" else [f"--outputFile={junit}"])
        begin = time.monotonic()
        status = subprocess.run(command, cwd=ROOT, env=environment, timeout=180).returncode
        summary = junit_summary(junit) if junit.exists() else {"passed": False, "missing_junit": True}
        if name == "rendered_ui" and summary.get("tests_executed") != 5:
            summary.update(passed=False, incomplete_required_inventory=True)
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
