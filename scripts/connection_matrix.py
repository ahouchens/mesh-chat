"""Verify existing component evidence; this is not a release artifact gate."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace

from android_qualification import APKS, CORE_APKS, CONSUMER_ARTIFACTS, INDEPENDENT_ARTIFACTS, SUITES as ANDROID_SUITES, ROOT, cases
from verify_android_independent_consumer import verify_record as independent_android_distribution
from connection_evidence import evidence as policy_evidence
from core_boundary_evidence import UI_LEVEL, WINDOWS_LEVEL, ui_evidence, windows_evidence
from native_windows_evidence import verify_report as native_evidence
from native_runtime_materials import verify_report as runtime_materials_evidence
from check_independent_core_consumers import verify_report as independent_bootstrap_evidence
from check_independent_core_pairing import verify_report as independent_pairing_evidence
from native_interop_evidence import verify_pair as native_interop_pair
from native_interop_workload import workload as required_native_workload
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
    if set(binaries) != ({str(path.relative_to(ROOT)).replace("\\", "/") for path in APKS}
                         | {str(path.relative_to(ROOT)).replace("\\", "/") for path in (*CORE_APKS, *CONSUMER_ARTIFACTS, *INDEPENDENT_ARTIFACTS)}):
        raise ValueError("Android evidence does not identify every tested APK")
    platform = record.get("platform", {})
    if platform.get("emulated") is not True or platform.get("test_host_cleanup") != "passed":
        raise ValueError("Android emulator execution or cleanup is unqualified")
    suites = record.get("suites")
    independent_android_distribution(record.get("independent_distribution", {}),
                                    {"source_commit": source, "source_tree": tree}, binaries)
    if not isinstance(suites, list) or len(suites) != len(ANDROID_SUITES):
        raise ValueError("Android suite inventory is incomplete")
    run_ids = set()
    for suite, expected in zip(suites, ANDROID_SUITES):
        run_id = suite.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id) or run_id in run_ids:
            raise ValueError("Android suite run identity is missing or duplicated")
        run_ids.add(run_id)
        required_cases = cases(expected)
        required = [case["id"] for case in required_cases]
        scenarios = suite.get("scenarios", [])
        if (suite.get("suite") != expected or not isinstance(scenarios, list)
                or [case.get("scenario_id") for case in scenarios] != required
                or any(case.get("passed") is not True for case in scenarios)):
            raise ValueError("Android scenario execution is incomplete")
        hashes({case["scenario_id"]: case.get("report_sha256") for case in scenarios})
        if any(case.get("scope") != item["scope"] for case, item in zip(scenarios, required_cases) if "scope" in item):
            raise ValueError("Android component scenario scope is missing or overstated")
        for name, count in {"tests_collected": len(required), "tests_executed": len(required),
                            "tests_passed": len(required), "tests_failed": 0, "tests_skipped": 0}.items():
            if type(suite.get(name)) is not int or suite[name] != count:
                raise ValueError("Android execution counts do not match the required scenarios")
        duration = suite.get("duration_seconds")
        if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0:
            raise ValueError("Android execution duration is invalid")
    return record


def collect(directory: Path, source: str, tree: str, required, *, native_workload="full"):
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
    if "verification" in required:
        ui_path = directory / "verification/core-ui-boundary.json"
        ui = ui_evidence(read(ui_path), ui_path.parent, source, tree)
        windows_path = directory / "desktop/core-windows-boundary.json"
        windows = windows_evidence(read(windows_path), windows_path.parent, source, tree)
        reports.update(core_ui_boundary=ui_path, core_windows_boundary=windows_path)
        for name, record in ui.items():
            suites.append(suite_record(name, UI_LEVEL, source, tree, report="core_ui_boundary",
                                       tests=counts(record["execution"]), artifacts=record["artifacts"]))
        suites.append(suite_record("core_windows_boundary", WINDOWS_LEVEL, source, tree,
                                  report="core_windows_boundary", tests=counts(windows["execution"]),
                                  artifacts=windows["artifacts"]))
        summary.update(core_ui_boundary_python_tests=ui["core_ui_boundary_python"]["execution"]["tests_executed"],
                       core_ui_boundary_rendered_tests=ui["core_ui_boundary_rendered"]["execution"]["tests_executed"],
                       core_windows_boundary_tests=windows["execution"]["tests_executed"])
        native_records = []
        for kind in ("control", "lifecycle"):
            name = "windows_native_" + kind
            path = directory / f"desktop/native-windows-{kind}.json"
            record = native_evidence(read(path), source, tree, kind)
            if (record["sidecar_sha256"] != packaged["sidecar_sha256"]
                    or record["build_input_sha256"] != packaged["build_input_sha256"]):
                raise ValueError("Native and packaged checks did not execute the same built sidecar")
            reports[name] = path
            native_records.append(record)
            suites.append(suite_record(name, record["evidence_level"], source, tree, report=name,
                                       checks=len(record["checks"]), cleanup="covered_by_checks",
                                       artifacts={field: record[field] for field in
                                                  ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")}))
            summary[name + "_counts"] = record["counts"]
        if (native_records[0]["build_manifest_sha256"] != native_records[1]["build_manifest_sha256"]
                or len({record["run_id"] for record in (*native_records, packaged, transport, pairing)}) != 5):
            raise ValueError("Native packaged runs require the same build manifest and distinct run identities")
        path = directory / "desktop/native-runtime-materials.json"
        record = runtime_materials_evidence(read(path), source, tree)
        bindings = ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")
        if any(record[field] != native_records[0][field] for field in bindings):
            raise ValueError("Runtime materials do not describe the tested frozen native sidecar")
        reports["windows_runtime_materials"] = path
        suites.append(suite_record("windows_runtime_materials", record["evidence_level"], source, tree,
                                   report="windows_runtime_materials", checks=record["inventory"]["notice_files_verified"],
                                   artifacts={field: record[field] for field in bindings}))
        path = directory / "desktop/windows-independent-bootstrap.json"
        record = independent_bootstrap_evidence(read(path), source, tree)
        installed_sdk = path.parent / record["sdk_artifact"]
        if (not 0 < installed_sdk.stat().st_size <= 2 * 1024 * 1024
                or hashlib.sha256(installed_sdk.read_bytes()).hexdigest() != record["sdk_sha256"]):
            raise ValueError("Retained independent SDK differs from the installed artifact")
        if (any(record[field] != native_records[0][field] for field in bindings)
                or record["run_id"] in {item["run_id"] for item in (*native_records, packaged, transport, pairing)}):
            raise ValueError("Independent application did not execute a distinct run of the same frozen runtime")
        reports["windows_independent_bootstrap"] = path
        suites.append(suite_record("windows_independent_bootstrap", record["evidence_level"], source, tree,
                                   report="windows_independent_bootstrap", checks=len(record["checks"]),
                                   cleanup=record["cleanup"],
                                   artifacts={field: record[field] for field in (*bindings, "sdk_sha256")}))
        bootstrap = record
        bootstrap_path = path
        path = directory / "desktop/windows-independent-pairing.json"
        record = independent_pairing_evidence(read(path), source, tree)
        if (any(record[field] != bootstrap[field] for field in (*bindings, "sdk_sha256"))
                or record["application"]["application_files"] != bootstrap["application"]["application_files"]
                or record["bootstrap_report_sha256"] != hashlib.sha256(bootstrap_path.read_bytes()).hexdigest()
                or record["run_id"] in {item["run_id"] for item in (*native_records, packaged, transport, pairing, bootstrap)}):
            raise ValueError("Independent public pairing did not execute its exact bootstrap artifacts in a distinct run")
        reports["windows_independent_pairing"] = path
        suites.append(suite_record("windows_independent_pairing", record["evidence_level"], source, tree,
                                   report="windows_independent_pairing", checks=len(record["checks"]),
                                   cleanup=record["cleanup"],
                                   artifacts={field: record[field] for field in (*bindings, "sdk_sha256")}))
    if "android" in required:
        for record in android["suites"]:
            suites.append(suite_record("android_" + record["suite"], android["evidence_level"], source, tree,
                                report="android", tests=counts(record),
                                artifacts=android["artifacts"],
                                cleanup=android["platform"]["test_host_cleanup"]))
    if "native_interop" in required:
        if not {"verification", "android"} <= set(required):
            raise ValueError("Native interoperability requires both actual packaged producer suites")
        paths = {role: directory / f"native-interop/native-interop-{role}.json" for role in ("windows", "android")}
        context = None
        if os.environ.get("GITHUB_ACTIONS") == "true":
            context = {"repository": os.environ["GITHUB_REPOSITORY"], "repository_id": int(os.environ["GITHUB_REPOSITORY_ID"]),
                       "run_id": int(os.environ["GITHUB_RUN_ID"]), "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "source_commit": source}
        plan = required_native_workload(native_workload)
        windows_peer, android_peer = native_interop_pair(read(paths["windows"]), read(paths["android"]), source, tree,
                                                       context=context, workload=native_workload)
        if any(windows_peer["artifacts"][field] != native_records[0][field]
               for field in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256")):
            raise ValueError("Native interop did not run the retained and tested Windows executable")
        if android_peer["artifacts"] != android["artifacts"]:
            raise ValueError("Native interop did not run the retained and tested Android artifacts")
        for role, peer in (("windows", windows_peer), ("android", android_peer)):
            name = "native_interop_" + role
            reports[name] = paths[role]
            checks = len(plan["paths"]) + plan["iterations"] + (3 if native_workload == "full" else 0)
            suites.append(suite_record("native_" + role + "_peer", plan["level"], source, tree,
                report=name, checks=checks, artifacts=peer["artifacts"], cleanup=peer["execution"]["cleanup"]))
        summary["native_interop"] = {"workload": native_workload, "receipt_iterations_per_role": plan["iterations"],
                                     "periodic_cold_starts_per_role": (plan["iterations"] - 1) // plan["cold_start_every"] + 1,
                                     "path_initiators": [list(case) for case in plan["paths"]],
                                     "impairment": "Linux kernel netem on an admitted emulator link plus counted app-UID UDP block controls" if native_workload == "full" else "not executed"}
    if "direct" in required:
        for platform in ("Linux", "Windows"):
            for record in direct_records[platform]:
                suites.append(suite_record("direct_" + platform + "_" + record["suite"], record["evidence_level"],
                                    source, tree, report="direct_" + platform + "_" + record["suite"],
                                    tests=counts(record), artifacts=record["artifacts"],
                                    cleanup="covered_by_checks"))
    return {**summary, "suites": unique_manifest(suites, reports), "report_sha256": {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in reports.items()}}
