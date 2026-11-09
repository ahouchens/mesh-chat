import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


@pytest.fixture(autouse=True)
def isolate_synthetic_reports_from_live_workflow(monkeypatch):
    # These component fixtures describe example/mesh run 2, never the live CI
    # run. A test exercising CI admission opts back in with an explicit context.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import connection_matrix as matrix
import native_runtime_materials as runtime_materials
from connection_evidence import execution_evidence
from direct_qualification import LEVEL, SUITES as DIRECT_SUITES
from connection_test_inventory import REQUIRED_SUITES
from check_core_ui_boundary import PYTHON_SELECTION, RENDERED_CASES, junit_summary
from check_core_windows_boundary import CASES as WINDOWS_CASES, SELECTION as WINDOWS_SELECTION
from core_boundary_evidence import UI_LEVEL, WINDOWS_LEVEL, digest
from native_windows_evidence import LEVELS as NATIVE_LEVELS, CHECKS as NATIVE_CHECKS, COUNTS as NATIVE_COUNTS, SCOPE as NATIVE_SCOPE
from test_desktop_transport import CHECKS
from test_packaged_lifecycle import CHECKS as PACKAGED_CHECKS, COUNTS as PACKAGED_COUNTS, LEVEL as PACKAGED_LEVEL
from test_packaged_transport import CHECKS as TRANSPORT_CHECKS, COUNTS as TRANSPORT_COUNTS, LEVEL as TRANSPORT_LEVEL
from test_packaged_transport import PAIRING_CHECKS, PAIRING_COUNTS, PAIRING_LEVEL


def fixture(directory):
    source, tree = "a" * 40, "b" * 40
    for name in ("policy", "desktop", "android", "verification"):
        (directory / name).mkdir()
    inventory = {"v": 1, "source_commit": source, "selection": list(REQUIRED_SUITES),
                 "nodeids": ["test_case"], "run_id": "current"}
    report = ET.Element("testsuite")
    test = ET.SubElement(report, "testcase", name="test_case", time="1")
    properties = ET.SubElement(test, "properties")
    for name, value in {"qualification_nodeid": "test_case", "qualification_run": "current"}.items():
        ET.SubElement(properties, "property", name=name, value=value)
    xml = directory / "policy/connection-policy.xml"
    inv = directory / "policy/connection-policy.inventory.json"
    ET.ElementTree(report).write(xml)
    inv.write_text(json.dumps(inventory))
    policy = matrix.policy_evidence(xml, source, source, inv)
    desktop = {"v": 1, "passed": True, "source_commit": source,
               "evidence_level": "windows_webview2_private_host_component",
               "result": {"ok": True, "checks": sorted(CHECKS)},
               "native_binary_sha256": "c" * 64, "python_sources_sha256": {
                   str(path.relative_to(matrix.ROOT)).replace("\\", "/"): "d" * 64 for path in matrix.PYTHON_SOURCES}}
    packaged = {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
                "evidence_level": PACKAGED_LEVEL, "run_id": "c" * 32, "sidecar_sha256": "d" * 64,
                "build_input_sha256": "e" * 64, "checks": list(PACKAGED_CHECKS),
                "counts": dict(PACKAGED_COUNTS), "duration_seconds": 1.0}
    android = {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
               "evidence_level": "android_emulator_optimized_native_and_python_components",
               "artifacts": {str(path.relative_to(matrix.ROOT)).replace("\\", "/"): "e" * 64
                  for path in (*matrix.APKS, *matrix.CORE_APKS, *matrix.CONSUMER_ARTIFACTS)},
               "platform": {"emulated": True, "test_host_cleanup": "passed"}, "suites": []}
    for suite, run in (("webrtc", "f"), ("signaling", "a"), ("core_api", "b"), ("core_consumer", "c")):
        cases = matrix.cases(suite)
        android["suites"].append({"suite": suite, "run_id": run * 32, "tests_collected": len(cases),
            "tests_executed": len(cases), "tests_passed": len(cases), "tests_failed": 0, "tests_skipped": 0,
            "duration_seconds": 1, "scenarios": [{"scenario_id": case["id"], "passed": True,
                "report_sha256": "b" * 64,
                **({"scope": case["scope"]} if "scope" in case else {})} for case in cases]})
    transport = {**packaged, "evidence_level": TRANSPORT_LEVEL, "checks": list(TRANSPORT_CHECKS),
                 "counts": dict(TRANSPORT_COUNTS), "run_id": "b" * 32,
                 "native_binary_sha256": desktop["native_binary_sha256"]}
    pairing = {**transport, "evidence_level": PAIRING_LEVEL, "checks": list(PAIRING_CHECKS),
               "counts": dict(PAIRING_COUNTS), "run_id": "a" * 32}
    for path, value in (("policy/connection-policy.json", policy),
                        ("desktop/desktop-transport.json", desktop),
                        ("desktop/packaged-lifecycle.json", packaged),
                        ("desktop/packaged-transport.json", transport),
                        ("desktop/packaged-pairing.json", pairing),
                        ("android/android-qualification.json", android)):
        (directory / path).write_text(json.dumps(value))
    boundary_reports(directory, source, tree)
    for index, kind in enumerate(("control", "lifecycle"), start=3):
        native = {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
                  "evidence_level": NATIVE_LEVELS[kind], "run_id": str(index) * 32,
                  "sidecar_sha256": packaged["sidecar_sha256"], "build_input_sha256": packaged["build_input_sha256"],
                  "build_manifest_sha256": "f" * 64, "checks": list(NATIVE_CHECKS[kind]),
                  "counts": dict(NATIVE_COUNTS[kind]), "duration_seconds": 1.0, "scope": NATIVE_SCOPE}
        if kind == "lifecycle":
            native["timings_ms"] = {"open_max": 100, "control_max": 200, "control_p95": 150}
        (directory / f"desktop/native-windows-{kind}.json").write_text(json.dumps(native))
    (directory / "desktop/native-runtime-materials.json").write_text(json.dumps(materials_report(source, tree)))
    return source, tree, android


def materials_report(source, tree):
    """Synthetic complete material declarations only, never actual archive evidence."""
    declaration = json.loads(runtime_materials.DECLARATION.read_text())
    packages = []
    for name, version in sorted(runtime_materials.locked_distributions(matrix.ROOT / "service/requirements.lock").items()):
        notices = [{"path": f"{runtime_materials.PREFIX}/distributions/{name}/METADATA", "kind": "metadata", "sha256": "a" * 64}]
        if name in declaration["required_notice_distributions"]:
            notices.append({"path": f"{runtime_materials.PREFIX}/distributions/{name}/LICENSE", "kind": "notice", "sha256": "b" * 64})
        packages.append({"name": name, "version": version, "declared_license": "synthetic", "notice_files": notices,
                         "wheel_native_files": [{"path": "av.libs/avcodec-fixture.dll", "sha256": "c" * 64}] if name == "av" else []})
    inventory = {"packages": packages, "native_archive_files": [{"path": "av.libs/avcodec-fixture.dll", "sha256": "c" * 64,
                "wheel_distributions": ["av"]}], "notice_files_verified": sum(len(item["notice_files"]) for item in packages),
                "required_modules_verified": declaration["required_modules"], "notice_limits": declaration["wheel_native_notice_limit"],
                "native_files_without_wheel_owner": [], "release_approval": False,
                "project_license_sha256": runtime_materials.digest(runtime_materials.text_bytes(matrix.ROOT / "LICENSE"))}
    return {"v": 1, "passed": True, "evidence_level": runtime_materials.LEVEL, "source_commit": source, "source_tree": tree,
            "sidecar_sha256": "d" * 64, "build_input_sha256": "e" * 64, "build_manifest_sha256": "f" * 64,
            "inventory": inventory, "scope": declaration["scope"], "declaration_sha256": runtime_materials.digest(runtime_materials.text_bytes(runtime_materials.DECLARATION))}


def boundary_reports(directory, source, tree):
    """Synthetic complete runs for testing the aggregator, never qualification evidence."""
    records = {}
    for name, folder, selection, nodeids in (
        ("python", "verification", PYTHON_SELECTION,
         [path.removeprefix("service/") + "::test_case" for path in PYTHON_SELECTION]),
        ("windows", "desktop", WINDOWS_SELECTION, sorted(WINDOWS_CASES)),
    ):
        filename = "core-ui-boundary-python" if name == "python" else "core-windows-boundary"
        junit = directory / folder / (filename + ".xml")
        inventory = junit.with_suffix(".inventory.json")
        inventory.write_text(json.dumps({"v": 1, "source_commit": source, "selection": list(selection),
                                         "nodeids": nodeids, "run_id": "boundary-" + name}))
        document = ET.Element("testsuite")
        for nodeid in nodeids:
            case = ET.SubElement(document, "testcase", name=nodeid, time="1")
            properties = ET.SubElement(case, "properties")
            for key, value in {"qualification_run": "boundary-" + name, "qualification_nodeid": nodeid}.items():
                ET.SubElement(properties, "property", name=key, value=value)
        ET.ElementTree(document).write(junit)
        records[name] = {**junit_summary(junit), "inventory_sha256": digest(inventory), "exit_code": 0}
    junit = directory / "verification/core-ui-boundary-rendered_ui.xml"
    document = ET.Element("testsuite")
    for classname, name in sorted(RENDERED_CASES):
        ET.SubElement(document, "testcase", classname=classname, name=name, time="1")
    ET.ElementTree(document).write(junit)
    ui = {"v": 1, "source_commit": source, "source_tree": tree, "passed": True,
          "evidence_level": UI_LEVEL, "suites": {"python": records["python"],
          "rendered_ui": {**junit_summary(junit), "exit_code": 0}}}
    windows = {"v": 1, "source_commit": source, "source_tree": tree, "evidence_level": WINDOWS_LEVEL,
               **records["windows"]}
    (directory / "verification/core-ui-boundary.json").write_text(json.dumps(ui))
    (directory / "desktop/core-windows-boundary.json").write_text(json.dumps(windows))


def test_gate_revalidates_policy_inventory_and_both_platform_component_reports(tmp_path):
    source, tree, _ = fixture(tmp_path)
    result = matrix.collect(tmp_path, source, tree, ["policy", "verification", "android"])
    assert result["policy_tests_executed"] == 1
    assert result["android_tests_executed"] == 50
    assert set(result["windows_transport_checks"]) == CHECKS
    assert set(result["report_sha256"]) == {"policy", "windows_transport", "windows_packaged_lifecycle",
                                          "windows_packaged_transport", "windows_packaged_pairing", "android",
                                          "core_ui_boundary", "core_windows_boundary",
                                          "windows_native_control", "windows_native_lifecycle", "windows_runtime_materials"}
    assert result["windows_packaged_lifecycle_checks"] == list(PACKAGED_CHECKS)
    assert result["core_ui_boundary_python_tests"] == len(PYTHON_SELECTION)
    assert result["core_ui_boundary_rendered_tests"] == len(RENDERED_CASES)
    assert result["core_windows_boundary_tests"] == 9


@pytest.mark.parametrize("fault", ["missing", "source", "sidecar", "build", "manifest", "package", "version",
    "notice", "dll", "owner", "license_claim", "project_license", "scope", "module", "notice_count"])
def test_required_runtime_materials_cannot_qualify_a_different_or_partial_archive(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    path = tmp_path / "desktop/native-runtime-materials.json"
    record = json.loads(path.read_text())
    inventory = record["inventory"]
    if fault == "missing":
        path.unlink()
    else:
        if fault == "source": record["source_commit"] = "f" * 40
        elif fault == "sidecar": record["sidecar_sha256"] = "1" * 64
        elif fault == "build": record["build_input_sha256"] = "1" * 64
        elif fault == "manifest": record["build_manifest_sha256"] = "1" * 64
        elif fault == "package": inventory["packages"].pop()
        elif fault == "version": inventory["packages"][0]["version"] = "99"
        elif fault == "notice":
            next(item for item in inventory["packages"] if item["name"] == "av")["notice_files"].pop()
        elif fault == "dll": inventory["native_archive_files"].clear()
        elif fault == "owner": inventory["native_archive_files"][0]["wheel_distributions"] = ["aiortc"]
        elif fault == "license_claim": inventory["release_approval"] = True
        elif fault == "project_license": inventory["project_license_sha256"] = "9" * 64
        elif fault == "scope": record["scope"] = "all licensing complete"
        elif fault == "module": inventory["required_modules_verified"].pop()
        else: inventory["notice_files_verified"] += 1
        path.write_text(json.dumps(record))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, ["verification"])


def native_interop_reports(directory, source, tree, artifacts, *, workload="full"):
    from test_ui_core_boundary_interop_controller import interop_reports
    folder = directory / "native-interop"
    folder.mkdir()
    reports = interop_reports(source, tree, artifacts, workload=workload)
    for role, report in zip(("windows", "android"), reports):
        (folder / f"native-interop-{role}.json").write_text(json.dumps(report))
    return reports


def test_required_native_interop_revalidates_both_actual_platform_roles_and_tested_images(tmp_path):
    source, tree, android = fixture(tmp_path)
    native_interop_reports(tmp_path, source, tree, android["artifacts"])
    result = matrix.collect(tmp_path, source, tree, ["verification", "android", "native_interop"])
    native = [item for item in result["suites"] if item["suite"] in {"native_windows_peer", "native_android_peer"}]
    assert len(native) == 2 and all(item["checks"] == 109 and item["cleanup"] == "passed" for item in native)
    assert result["native_interop"]["receipt_iterations_per_role"] == 100
    assert result["native_interop"]["periodic_cold_starts_per_role"] == 10
    assert set(result["report_sha256"]) >= {"native_interop_windows", "native_interop_android"}


def test_quick_native_smoke_is_required_and_cannot_satisfy_full_gate(tmp_path):
    source, tree, android = fixture(tmp_path)
    native_interop_reports(tmp_path, source, tree, android["artifacts"], workload="quick")
    required = ["verification", "android", "native_interop"]
    result = matrix.collect(tmp_path, source, tree, required, native_workload="quick")
    native = [item for item in result["suites"] if item["suite"] in {"native_windows_peer", "native_android_peer"}]
    assert len(native) == 2 and all(item["checks"] == 8 and item["evidence_level"].endswith("_quick_smoke") for item in native)
    assert result["native_interop"]["receipt_iterations_per_role"] == 5
    assert result["native_interop"]["periodic_cold_starts_per_role"] == 1
    assert result["native_interop"]["impairment"] == "not executed"
    with pytest.raises(ValueError): matrix.collect(tmp_path, source, tree, required)


@pytest.mark.parametrize("workload", ["quick", "full"])
def test_ci_native_context_accepts_exact_run_and_rejects_another_attempt(tmp_path, monkeypatch, workload):
    source, tree, android = fixture(tmp_path)
    native_interop_reports(tmp_path, source, tree, android["artifacts"], workload=workload)
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "example/mesh", "GITHUB_REPOSITORY_ID": "1",
                       "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    required = ["verification", "android", "native_interop"]
    assert matrix.collect(tmp_path, source, tree, required, native_workload=workload)["native_interop"]["workload"] == workload
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(ValueError, match="another workflow run or attempt"):
        matrix.collect(tmp_path, source, tree, required, native_workload=workload)


@pytest.mark.parametrize("fault", ["missing_windows", "missing_android", "other_windows_binary", "other_android_apk", "cross_peer_message", "prior_attempt"])
def test_gate_cannot_substitute_other_binaries_or_old_run_native_reports(tmp_path, monkeypatch, fault):
    source, tree, android = fixture(tmp_path)
    reports = native_interop_reports(tmp_path, source, tree, android["artifacts"])
    role = "windows" if fault in {"missing_windows", "other_windows_binary"} else "android"
    path = tmp_path / f"native-interop/native-interop-{role}.json"
    record = json.loads(path.read_text())
    if fault.startswith("missing_"): path.unlink()
    else:
        if fault == "other_windows_binary": record["artifacts"]["sidecar_sha256"] = "1" * 64
        elif fault == "other_android_apk": record["artifacts"][next(iter(record["artifacts"]))] = "1" * 64
        elif fault == "cross_peer_message": record["execution"]["scenarios"][0]["messages"][0]["inbound"] = "1" * 64
        else:
            for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "example/mesh", "GITHUB_REPOSITORY_ID": "1",
                               "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "2"}.items(): monkeypatch.setenv(key, value)
        path.write_text(json.dumps(record))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, ["verification", "android", "native_interop"])


def test_android_report_without_typed_app_bridge_execution_cannot_qualify(tmp_path):
    source, tree, android = fixture(tmp_path)
    suite = next(item for item in android["suites"] if item["suite"] == "core_api")
    suite["scenarios"] = [case for case in suite["scenarios"]
                          if "TypedCoreBridgeBoundaryTest" not in case["scenario_id"]]
    for key in ("tests_collected", "tests_executed", "tests_passed"):
        suite[key] = len(suite["scenarios"])
    (tmp_path / "android/android-qualification.json").write_text(json.dumps(android))
    with pytest.raises(ValueError, match="scenario execution"):
        matrix.collect(tmp_path, source, tree, ["policy", "verification", "android"])


@pytest.mark.parametrize("fault", ["missing", "not_passed", "scope_missing", "scope_overstated"])
def test_android_result_registry_execution_and_component_scope_are_required(tmp_path, fault):
    source, tree, android = fixture(tmp_path)
    suite = next(item for item in android["suites"] if item["suite"] == "core_api")
    case = next(item for item in suite["scenarios"] if "NativeProfileResultRegistrationTest" in item["scenario_id"])
    if fault == "missing":
        suite["scenarios"].remove(case)
        for key in ("tests_collected", "tests_executed", "tests_passed"):
            suite[key] = len(suite["scenarios"])
    elif fault == "not_passed":
        case["passed"] = False
    elif fault == "scope_missing":
        case.pop("scope")
    else:
        case["scope"] = "Successful OS credential confirmation"
    (tmp_path / "android/android-qualification.json").write_text(json.dumps(android))
    with pytest.raises(ValueError, match="scenario"):
        matrix.collect(tmp_path, source, tree, ["policy", "verification", "android"])


@pytest.mark.parametrize("omission", ["suite", "aar", "consumer_apk"])
def test_android_report_without_independent_consumer_evidence_cannot_qualify(tmp_path, omission):
    source, tree, android = fixture(tmp_path)
    if omission == "suite": android["suites"].pop()
    else:
        filename = "mesh-core-client.aar" if omission == "aar" else "consumer.apk"
        key = next(key for key in android["artifacts"] if key.endswith("/" + filename))
        del android["artifacts"][key]
    with pytest.raises(ValueError): matrix.android_evidence(android, source, tree)


def test_previous_android_inventory_without_native_contact_bootstrap_cannot_pass(tmp_path):
    source, tree, record = fixture(tmp_path)
    signaling = next(suite for suite in record["suites"] if suite["suite"] == "signaling")
    signaling["scenarios"] = [case for case in signaling["scenarios"]
        if "contactBootstrapUsesNativeDataChannelsAndIsolatedProcess" not in case["scenario_id"]]
    for name in ("tests_collected", "tests_executed", "tests_passed"):
        signaling[name] -= 1
    (tmp_path / "android/android-qualification.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        matrix.collect(tmp_path, source, tree, ["policy", "verification", "android"])


@pytest.mark.parametrize("fault", ["source", "tree", "skip", "missing_case", "missing_apk", "cleanup", "run", "version"])
def test_android_report_cannot_promote_partial_or_mismatched_evidence(tmp_path, fault):
    source, tree, record = fixture(tmp_path)
    if fault in {"source", "tree"}:
        record["source_commit" if fault == "source" else "source_tree"] = "c" * 40
    elif fault == "skip":
        record["suites"][0]["tests_skipped"] = 1
    elif fault == "missing_case":
        record["suites"][0]["scenarios"].pop()
    elif fault == "missing_apk":
        record["artifacts"].popitem()
    elif fault == "cleanup":
        record["platform"]["test_host_cleanup"] = "unknown"
    elif fault == "version":
        record["v"] = True
    else:
        record["suites"][1]["run_id"] = record["suites"][0]["run_id"]
    (tmp_path / "android/android-qualification.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        matrix.collect(tmp_path, source, tree, ["android"])


def test_a_missing_required_artifact_fails_but_an_explicit_exclusion_is_allowed(tmp_path):
    source, tree, _ = fixture(tmp_path)
    (tmp_path / "android/android-qualification.json").unlink()
    with pytest.raises(FileNotFoundError):
        matrix.collect(tmp_path, source, tree, ["android"])
    assert "android_tests_executed" not in matrix.collect(tmp_path, source, tree, [])


def test_a_passing_summary_cannot_hide_missing_policy_execution(tmp_path):
    source, tree, _ = fixture(tmp_path)
    (tmp_path / "policy/connection-policy.xml").write_text("<testsuite/>")
    with pytest.raises(ValueError):
        matrix.collect(tmp_path, source, tree, [])


def direct_reports(directory, source, tree):
    for platform, host in (("Linux", "posix"), ("Windows", "nt")):
        folder = directory / ("direct-" + platform)
        folder.mkdir()
        for suite, (selection, _, artifact) in DIRECT_SUITES.items():
            run = platform + "-" + suite
            inventory = {"v": 1, "source_commit": source, "selection": [selection],
                         "nodeids": ["test_native"], "run_id": run}
            path = folder / (suite + ".json")
            path.with_suffix(".inventory.json").write_text(json.dumps(inventory))
            xml = ET.Element("testsuite")
            case = ET.SubElement(xml, "testcase", name="test_native", time="1")
            properties = ET.SubElement(case, "properties")
            for name, value in {"qualification_run": run, "qualification_nodeid": "test_native"}.items():
                ET.SubElement(properties, "property", name=name, value=value)
            ET.ElementTree(xml).write(path.with_suffix(".xml"))
            record = {**execution_evidence(path.with_suffix(".xml"), source, source,
                       path.with_suffix(".inventory.json"), [selection]),
                      "suite": suite, "source_tree": tree, "passed": True, "evidence_level": LEVEL,
                      "internal_contract": 1, "platform": host, "python_version": "3.13.1",
                      "artifacts": {artifact: "c" * 64}}
            path.write_text(json.dumps(record))


def test_selected_direct_requires_complete_execution_from_both_platforms(tmp_path):
    source, tree, _ = fixture(tmp_path)
    direct_reports(tmp_path, source, tree)
    result = matrix.collect(tmp_path, source, tree, ["direct"])
    assert set(result["direct"]) == {"Linux", "Windows"}
    assert all(value["tests_executed"] == 3 for value in result["direct"].values())
    assert len(result["report_sha256"]) == 11


@pytest.mark.parametrize("fault", ["missing", "preapproved", "different_binary", "missing_receipt", "reused_run"])
def test_first_time_pairing_cannot_be_replaced_by_preapproved_execution(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    path = tmp_path / "desktop/packaged-pairing.json"
    value = json.loads(path.read_text())
    if fault == "missing": path.unlink()
    else:
        if fault == "preapproved": value = json.loads((tmp_path / "desktop/packaged-transport.json").read_text())
        elif fault == "different_binary": value["sidecar_sha256"] = "9" * 64
        elif fault == "missing_receipt": value["counts"]["authenticated_receipts"] = 1
        else: value["run_id"] = "b" * 32
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, [])


@pytest.mark.parametrize("fault", ["missing", "sidecar", "host", "build", "receipts"])
def test_packaged_transport_must_execute_against_the_same_artifacts(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    path = tmp_path / "desktop/packaged-transport.json"
    value = json.loads(path.read_text())
    if fault == "missing": path.unlink()
    else:
        if fault == "sidecar": value["sidecar_sha256"] = "9" * 64
        elif fault == "host": value["native_binary_sha256"] = "9" * 64
        elif fault == "build": value["build_input_sha256"] = "9" * 64
        else: value["counts"]["authenticated_receipts"] = 0
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, [])


@pytest.mark.parametrize("fault", ["missing", "wrong_source", "partial", "stale_binary"])
def test_windows_job_summary_cannot_hide_missing_or_incompatible_packaged_execution(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    path = tmp_path / "desktop/packaged-lifecycle.json"
    value = json.loads(path.read_text())
    if fault == "missing": path.unlink()
    else:
        if fault == "wrong_source": value["source_commit"] = "f" * 40
        elif fault == "partial": value["counts"]["clean_shutdowns"] = 2
        else: value["passed"] = False
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, [])


@pytest.mark.parametrize("fault", ["missing_platform", "wrong_platform", "different_dispatcher", "skip", "wrong_suite"])
def test_direct_component_gate_rejects_incomplete_or_inconsistent_native_runs(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    direct_reports(tmp_path, source, tree)
    path = tmp_path / "direct-Windows/setup.json"
    record = json.loads(path.read_text())
    if fault == "missing_platform":
        path.unlink()
    elif fault == "skip":
        xml = path.with_suffix(".xml")
        document = ET.parse(xml)
        ET.SubElement(document.getroot().find("testcase"), "skipped")
        document.write(xml)
    else:
        if fault == "different_dispatcher":
            record["artifacts"]["shipping_dispatcher"] = "d" * 64
        elif fault == "wrong_platform":
            record["platform"] = "posix"
        else:
            record["suite"] = "recovery"
        path.write_text(json.dumps(record))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, ["direct"])


def test_suite_manifest_is_uniform_across_every_required_component(tmp_path):
    source, tree, _ = fixture(tmp_path)
    direct_reports(tmp_path, source, tree)
    result = matrix.collect(tmp_path, source, tree, ["policy", "verification", "android", "direct"])
    records = result["suites"]
    keys = {"suite", "evidence_level", "source_commit", "source_tree",
            "tests", "checks", "artifacts", "cleanup", "report_sha256"}
    assert all(set(record) == keys for record in records)
    assert [record["suite"] for record in records] == [
        "policy", "windows_transport", "windows_packaged_lifecycle",
        "windows_packaged_transport", "windows_packaged_pairing",
        "core_ui_boundary_python", "core_ui_boundary_rendered", "core_windows_boundary",
        "windows_native_control", "windows_native_lifecycle", "windows_runtime_materials",
        "android_webrtc", "android_signaling", "android_core_api", "android_core_consumer",
        *("direct_Linux_" + name for name in DIRECT_SUITES),
        *("direct_Windows_" + name for name in DIRECT_SUITES)]
    policy = records[0]
    assert policy["tests"] == {"collected": 1, "executed": 1, "passed": 1, "failed": 0, "skipped": 0}
    assert policy["checks"] is None and policy["cleanup"] == "not_applicable"
    android = [record for record in records if record["suite"].startswith("android_")]
    assert [record["tests"]["collected"] for record in android] == [
        len(matrix.cases("webrtc")), len(matrix.cases("signaling")),
        len(matrix.cases("core_api")), len(matrix.cases("core_consumer"))]
    assert all(record["cleanup"] == "passed" for record in android)
    direct = [record for record in records if record["suite"].startswith("direct_")]
    assert all(record["tests"]["executed"] == 1 and record["checks"] is None for record in direct)
    assert all(record["report_sha256"] for record in records)
    assert all(record["source_commit"] == source and record["source_tree"] == tree for record in records)
    windows = next(record for record in records if record["suite"] == "windows_transport")
    assert windows["checks"] == len(CHECKS) and windows["artifacts"]
    boundary = [record for record in records if record["suite"].startswith("core_")]
    assert [record["tests"]["executed"] for record in boundary] == [len(PYTHON_SELECTION), len(RENDERED_CASES), len(WINDOWS_CASES)]
    assert all(record["artifacts"]["junit"] for record in boundary)
    assert all("inventory" in record["artifacts"] for record in (boundary[0], boundary[2]))


@pytest.mark.parametrize("fault", ["missing", "binary", "inputs", "manifest", "reused_run", "partial_soak"])
def test_native_packaged_runs_are_mandatory_and_bound_to_the_same_tested_artifact(tmp_path, fault):
    source, tree, _ = fixture(tmp_path)
    path = tmp_path / "desktop/native-windows-lifecycle.json"
    value = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    else:
        if fault == "binary": value["sidecar_sha256"] = "9" * 64
        elif fault == "inputs": value["build_input_sha256"] = "9" * 64
        elif fault == "manifest": value["build_manifest_sha256"] = "9" * 64
        elif fault == "reused_run": value["run_id"] = "c" * 32
        else: value["counts"]["channel_pairs"] = 99
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, ["policy", "verification"])


def test_suite_record_rejects_failed_skipped_or_unbounded_counts():
    source, tree = "a" * 40, "b" * 40
    for tests in ({"collected": 1, "executed": 1, "passed": 0, "failed": 1, "skipped": 0},
                  {"collected": 1, "executed": 1, "passed": 0, "failed": 0, "skipped": 1},
                  {"collected": 1, "executed": 1, "passed": 1, "failed": 0, "skipped": 0, "extra": 0}):
        with pytest.raises(ValueError):
            matrix.suite_record("policy", "level", source, tree, report="policy", tests=tests)
    with pytest.raises(ValueError):
        matrix.suite_record("policy", "level", source, tree, report="policy", checks=0)
    with pytest.raises(ValueError):
        matrix.suite_record("policy", "level", source, tree, report="policy",
                            artifacts={"native": "not-a-digest"})


def test_manifest_rejects_duplicate_component_identities(tmp_path):
    source, tree, _ = fixture(tmp_path)
    report = tmp_path / "policy/connection-policy.json"
    records = [matrix.suite_record("policy", "level", source, tree, report="policy"),
               matrix.suite_record("policy", "level", source, tree, report="policy")]
    with pytest.raises(ValueError):
        matrix.unique_manifest(records, {"policy": report})


def test_manifest_component_identities_match_the_shared_requirement_table(tmp_path):
    from connection_ci import COMPONENTS
    source, tree, _ = fixture(tmp_path)
    direct_reports(tmp_path, source, tree)
    required = ["policy", "verification", "android", "direct"]
    present = {record["suite"] for record in matrix.collect(tmp_path, source, tree, required)["suites"]}
    expected = set().union(*(COMPONENTS[name] for name in required))
    assert present == expected


@pytest.mark.parametrize("component", ["python", "rendered_ui", "windows"])
@pytest.mark.parametrize("fault", ["missing_report", "source", "tree", "digest", "skip", "inventory", "run"])
def test_final_gate_revalidates_every_boundary_execution(tmp_path, component, fault):
    source, tree, _ = fixture(tmp_path)
    windows = component == "windows"
    folder = tmp_path / ("desktop" if windows else "verification")
    path = folder / ("core-windows-boundary.json" if windows else "core-ui-boundary.json")
    record = json.loads(path.read_text())
    suite = record if windows else record["suites"][component]
    junit = folder / ("core-windows-boundary.xml" if windows else f"core-ui-boundary-{component}.xml")
    if fault == "missing_report":
        path.unlink()
    else:
        if fault in {"source", "tree"}:
            record["source_commit" if fault == "source" else "source_tree"] = "f" * 40
        elif fault == "digest":
            suite["sha256"] = "f" * 64
        elif fault == "skip":
            document = ET.parse(junit)
            ET.SubElement(document.getroot().find("testcase"), "skipped")
            document.write(junit)
            # Even a matching updated digest cannot qualify skipped execution.
            suite.update(junit_summary(junit))
            suite["passed"] = True
        elif component == "rendered_ui":
            document = ET.parse(junit)
            cases = document.getroot().findall("testcase")
            # Keep the passing count while substituting or duplicating one identity.
            cases[0].set("name", "unrelated case" if fault == "inventory" else cases[1].get("name"))
            document.write(junit)
            suite.update(junit_summary(junit))
        else:
            inventory = junit.with_suffix(".inventory.json")
            collected = json.loads(inventory.read_text())
            if fault == "inventory":
                collected["selection"] = ["unrelated.py"]
            else:
                collected["run_id"] = "another-run"
            inventory.write_text(json.dumps(collected))
            suite["inventory_sha256"] = digest(inventory)
        path.write_text(json.dumps(record))
    with pytest.raises((ValueError, FileNotFoundError)):
        matrix.collect(tmp_path, source, tree, ["policy", "verification"])


@pytest.mark.parametrize("component", ["python", "windows"])
def test_boundary_gate_rejects_a_consistent_but_reduced_execution_inventory(tmp_path, component):
    source, tree, _ = fixture(tmp_path)
    windows = component == "windows"
    folder = tmp_path / ("desktop" if windows else "verification")
    path = folder / ("core-windows-boundary.json" if windows else "core-ui-boundary.json")
    junit = folder / ("core-windows-boundary.xml" if windows else "core-ui-boundary-python.xml")
    inventory = junit.with_suffix(".inventory.json")
    document = ET.parse(junit)
    document.getroot().remove(document.getroot().find("testcase"))
    document.write(junit)
    collected = json.loads(inventory.read_text())
    collected["nodeids"].pop(0)
    inventory.write_text(json.dumps(collected))
    record = json.loads(path.read_text())
    suite = record if windows else record["suites"]["python"]
    suite.update(junit_summary(junit), inventory_sha256=digest(inventory))
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="inventory|collection"):
        matrix.collect(tmp_path, source, tree, ["policy", "verification"])
