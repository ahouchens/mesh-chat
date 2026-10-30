import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import connection_matrix as matrix
from connection_evidence import execution_evidence
from direct_qualification import LEVEL, SUITES as DIRECT_SUITES
from connection_test_inventory import REQUIRED_SUITES
from test_desktop_transport import CHECKS
from test_packaged_lifecycle import CHECKS as PACKAGED_CHECKS, COUNTS as PACKAGED_COUNTS, LEVEL as PACKAGED_LEVEL
from test_packaged_transport import CHECKS as TRANSPORT_CHECKS, COUNTS as TRANSPORT_COUNTS, LEVEL as TRANSPORT_LEVEL
from test_packaged_transport import PAIRING_CHECKS, PAIRING_COUNTS, PAIRING_LEVEL


def fixture(directory):
    source, tree = "a" * 40, "b" * 40
    for name in ("policy", "desktop", "android"):
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
               "artifacts": {str(path.relative_to(matrix.ROOT)).replace("\\", "/"): "e" * 64 for path in matrix.APKS},
               "platform": {"emulated": True, "test_host_cleanup": "passed"}, "suites": []}
    for suite, run in (("webrtc", "f"), ("signaling", "a")):
        cases = matrix.cases(suite)
        android["suites"].append({"suite": suite, "run_id": run * 32, "tests_collected": len(cases),
            "tests_executed": len(cases), "tests_passed": len(cases), "tests_failed": 0, "tests_skipped": 0,
            "duration_seconds": 1, "scenarios": [{"scenario_id": case["id"], "passed": True,
                "report_sha256": "b" * 64} for case in cases]})
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
    return source, tree, android


def test_gate_revalidates_policy_inventory_and_both_platform_component_reports(tmp_path):
    source, tree, _ = fixture(tmp_path)
    result = matrix.collect(tmp_path, source, tree, ["policy", "verification", "android"])
    assert result["policy_tests_executed"] == 1
    assert result["android_tests_executed"] == 26
    assert set(result["windows_transport_checks"]) == CHECKS
    assert set(result["report_sha256"]) == {"policy", "windows_transport", "windows_packaged_lifecycle",
                                          "windows_packaged_transport", "windows_packaged_pairing", "android"}
    assert result["windows_packaged_lifecycle_checks"] == list(PACKAGED_CHECKS)


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
