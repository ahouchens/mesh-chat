"""Verify existing component evidence; this is not a release artifact gate."""

import hashlib
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace

from android_qualification import APKS, ROOT, cases
from connection_evidence import evidence as policy_evidence
from direct_qualification import SUITES as DIRECT_SUITES, read_suite as direct_suite
from test_desktop_transport import PYTHON_SOURCES, verified_report as desktop_evidence


def read(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Component evidence exceeds its report budget")
    return json.loads(path.read_text(encoding="utf-8"))


def hashes(values):
    if (not isinstance(values, dict) or not values
            or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                   for value in values.values())):
        raise ValueError("Component artifact digests are incomplete")


def android_evidence(record, source, tree):
    if (type(record.get("v")) is not int or record["v"] != 1 or record.get("passed") is not True
            or record.get("source_commit") != source or record.get("source_tree") != tree
            or record.get("evidence_level") != "android_emulator_optimized_native_and_python_components"):
        raise ValueError("Android evidence has the wrong source, type or outcome")
    binaries = record.get("artifacts")
    hashes(binaries)
    if set(binaries) != {str(path.relative_to(ROOT)).replace("\\", "/") for path in APKS}:
        raise ValueError("Android evidence does not identify both tested APKs")
    platform = record.get("platform", {})
    if platform.get("emulated") is not True or platform.get("test_host_cleanup") != "passed":
        raise ValueError("Android emulator execution or cleanup is unqualified")
    suites = record.get("suites")
    if not isinstance(suites, list) or len(suites) != 2:
        raise ValueError("Android suite inventory is incomplete")
    run_ids = set()
    for suite, expected in zip(suites, ("webrtc", "signaling")):
        run_id = suite.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id) or run_id in run_ids:
            raise ValueError("Android suite run identity is missing or duplicated")
        run_ids.add(run_id)
        required = [case["id"] for case in cases(expected)]
        scenarios = suite.get("scenarios", [])
        if (suite.get("suite") != expected or not isinstance(scenarios, list)
                or [case.get("scenario_id") for case in scenarios] != required
                or any(case.get("passed") is not True for case in scenarios)):
            raise ValueError("Android scenario execution is incomplete")
        hashes({case["scenario_id"]: case.get("report_sha256") for case in scenarios})
        for name, count in {"tests_collected": len(required), "tests_executed": len(required),
                            "tests_passed": len(required), "tests_failed": 0, "tests_skipped": 0}.items():
            if type(suite.get(name)) is not int or suite[name] != count:
                raise ValueError("Android execution counts do not match the required scenarios")
        duration = suite.get("duration_seconds")
        if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
            raise ValueError("Android execution duration is invalid")
    return record


def collect(directory: Path, source: str, tree: str, required):
    policy_path = directory / "policy/connection-policy.json"
    policy = read(policy_path)
    executed = policy_evidence(policy_path.with_suffix(".xml"), source, source,
                               policy_path.with_suffix(".inventory.json"))
    if policy != executed:
        raise ValueError("Policy report does not match its actual execution inventory")
    desktop_path = directory / "desktop/desktop-transport.json"
    desktop = read(desktop_path)
    if desktop.get("passed") is not True:
        raise ValueError("Windows transport execution did not pass")
    desktop_evidence(SimpleNamespace(returncode=0, stdout=json.dumps({
        key: desktop.get(key) for key in ("v", "source_commit", "evidence_level", "result")
    })), source)
    hashes({"native": desktop.get("native_binary_sha256")})
    hashes(desktop.get("python_sources_sha256"))
    if set(desktop["python_sources_sha256"]) != {str(path.relative_to(ROOT)).replace("\\", "/") for path in PYTHON_SOURCES}:
        raise ValueError("Windows source component digest inventory is incomplete")
    reports = {"policy": policy_path, "windows_transport": desktop_path}
    summary = {"policy_tests_executed": policy["tests_executed"],
               "windows_transport_checks": desktop["result"]["checks"],
               "windows_native_sha256": desktop["native_binary_sha256"]}
    if "android" in required:
        android_path = directory / "android/android-qualification.json"
        android = android_evidence(read(android_path), source, tree)
        reports["android"] = android_path
        summary["android_tests_executed"] = sum(suite["tests_executed"] for suite in android["suites"])
        summary["android_artifacts"] = android["artifacts"]
    if "direct" in required:
        direct = {}
        for platform, host in (("Linux", "posix"), ("Windows", "nt")):
            records = {}
            for suite in DIRECT_SUITES:
                path = directory / ("direct-" + platform) / (suite + ".json")
                record = direct_suite(path, source, tree, host)
                if record["suite"] != suite:
                    raise ValueError("Direct component report belongs to another suite")
                records[suite] = record
                reports["direct_" + platform + "_" + suite] = path
            if (len({record["qualification_run"] for record in records.values()}) != len(DIRECT_SUITES)
                    or records["recovery"]["artifacts"] != records["setup"]["artifacts"]):
                raise ValueError("Direct scenarios did not use distinct runs and the same shipping dispatcher")
            direct[platform] = {"tests_executed": sum(record["tests_executed"] for record in records.values()),
                                "artifacts": {**records["recovery"]["artifacts"], **records["fabric"]["artifacts"]}}
        summary["direct"] = direct
    return {**summary, "report_sha256": {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in reports.items()}}
