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
from test_packaged_lifecycle import verify_report as packaged_evidence
from test_packaged_transport import verify_report as packaged_transport_evidence, verify_pairing_report


def read(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Component evidence exceeds its report budget")
    return json.loads(path.read_text(encoding="utf-8"))


def hashes(values):
    if (not isinstance(values, dict) or not values
            or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                   for value in values.values())):
        raise ValueError("Component artifact digests are incomplete")


COUNT_FIELDS = {"collected": "tests_collected", "executed": "tests_executed",
                "passed": "tests_passed", "failed": "tests_failed", "skipped": "tests_skipped"}


def counts(record):
    values = {name: record.get(field) for name, field in COUNT_FIELDS.items()}
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("Component test counts are incomplete")
    return values


def validated_counts(tests):
    if tests is None:
        return None
    if (set(tests) != set(COUNT_FIELDS)
            or any(type(value) is not int or value < 0 for value in tests.values())
            or tests["failed"] or tests["skipped"]):
        raise ValueError("Required component evidence cannot skip or fail cases")
    return tests


def validated_checks(checks):
    if checks is not None and (type(checks) is not int or checks <= 0):
        raise ValueError("Component check inventory is incomplete")
    return checks


def validated_digests(artifacts):
    digests = dict(artifacts or {})
    if any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
           for value in digests.values()):
        raise ValueError("Component artifact digests are incomplete")
    return digests


def suite_record(name, level, source, tree, *, report, tests=None, checks=None,
                 artifacts=None, cleanup="not_applicable"):
    """One uniform record per required component, whatever its native shape."""
    return {"suite": name, "evidence_level": level, "source_commit": source, "source_tree": tree,
            "tests": validated_counts(tests), "checks": validated_checks(checks),
            "artifacts": validated_digests(artifacts), "cleanup": cleanup, "report": report}


def unique_manifest(records, reports):
    """Attach report digests and reject duplicate or unbound component identities."""
    names = [record["suite"] for record in records]
    if len(set(names)) != len(names):
        raise ValueError("Component suite identities are duplicated")
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in reports.items()}
    for record in records:
        record["report_sha256"] = digests[record.pop("report")]
    return records


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
    packaged_path = directory / "desktop/packaged-lifecycle.json"
    packaged = packaged_evidence(read(packaged_path), source, tree)
    transport_path = directory / "desktop/packaged-transport.json"
    transport = packaged_transport_evidence(read(transport_path), source, tree)
    pairing_path = directory / "desktop/packaged-pairing.json"
    pairing = verify_pairing_report(read(pairing_path), source, tree)
    if any(record["sidecar_sha256"] != packaged["sidecar_sha256"]
            or record["build_input_sha256"] != packaged["build_input_sha256"]
            or record["native_binary_sha256"] != desktop["native_binary_sha256"] for record in (transport, pairing)):
        raise ValueError("Windows scenarios did not execute the same frozen service and native host")
    if len({record["run_id"] for record in (packaged, transport, pairing)}) != 3:
        raise ValueError("Packaged scenarios require separate execution identities")
    reports = {"policy": policy_path, "windows_transport": desktop_path,
               "windows_packaged_lifecycle": packaged_path, "windows_packaged_transport": transport_path,
               "windows_packaged_pairing": pairing_path}
    summary = {"policy_tests_executed": policy["tests_executed"],
               "windows_transport_checks": desktop["result"]["checks"],
               "windows_native_sha256": desktop["native_binary_sha256"],
               "windows_packaged_lifecycle_checks": packaged["checks"],
               "windows_packaged_transport_checks": transport["checks"],
               "windows_packaged_pairing_checks": pairing["checks"],
               "windows_sidecar_sha256": packaged["sidecar_sha256"]}
    if "android" in required:
        android_path = directory / "android/android-qualification.json"
        android = android_evidence(read(android_path), source, tree)
        reports["android"] = android_path
        summary["android_tests_executed"] = sum(suite["tests_executed"] for suite in android["suites"])
        summary["android_artifacts"] = android["artifacts"]
    direct_records = {}
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
            direct_records[platform] = list(records.values())
            direct[platform] = {"tests_executed": sum(record["tests_executed"] for record in records.values()),
                                "artifacts": {**records["recovery"]["artifacts"], **records["fabric"]["artifacts"]}}
        summary["direct"] = direct
    suites = [
        suite_record("policy", policy["evidence_level"], source, tree, report="policy",
              tests=counts(policy)),
        suite_record("windows_transport", desktop["evidence_level"], source, tree,
              report="windows_transport", checks=len(desktop["result"]["checks"]),
              artifacts={"native_binary": desktop["native_binary_sha256"]},
              cleanup="covered_by_checks"),
        suite_record("windows_packaged_lifecycle", packaged["evidence_level"], source, tree,
              report="windows_packaged_lifecycle", checks=len(packaged["checks"]),
              artifacts={"sidecar": packaged["sidecar_sha256"]}, cleanup="covered_by_checks"),
        suite_record("windows_packaged_transport", transport["evidence_level"], source, tree,
              report="windows_packaged_transport", checks=len(transport["checks"]),
              artifacts={"sidecar": transport["sidecar_sha256"],
                         "native_binary": transport["native_binary_sha256"]},
              cleanup="covered_by_checks"),
        suite_record("windows_packaged_pairing", pairing["evidence_level"], source, tree,
              report="windows_packaged_pairing", checks=len(pairing["checks"]),
              artifacts={"sidecar": pairing["sidecar_sha256"]}, cleanup="covered_by_checks"),
    ]
    if "android" in required:
        for record in android["suites"]:
            suites.append(suite_record("android_" + record["suite"], android["evidence_level"], source, tree,
                                report="android", tests=counts(record),
                                artifacts=android["artifacts"],
                                cleanup=android["platform"]["test_host_cleanup"]))
    if "direct" in required:
        for platform in ("Linux", "Windows"):
            for record in direct_records[platform]:
                suites.append(suite_record("direct_" + platform + "_" + record["suite"], record["evidence_level"],
                                    source, tree, report="direct_" + platform + "_" + record["suite"],
                                    tests=counts(record), artifacts=record["artifacts"],
                                    cleanup="covered_by_checks"))
    return {**summary, "suites": unique_manifest(suites, reports), "report_sha256": {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in reports.items()}}
