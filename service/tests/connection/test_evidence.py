import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest


script = Path(__file__).resolve().parents[3] / "scripts" / "connection_evidence.py"
sys.path.insert(0, str(script.parent))
spec = importlib.util.spec_from_file_location("connection_evidence", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("body", ["", '<testcase><skipped/></testcase>',
                                  '<testcase><failure/></testcase>', '<testcase><error/></testcase>'])
def test_required_skipped_failed_or_empty_suites_fail(tmp_path, body):
    report = tmp_path / "results.xml"
    report.write_text(f"<testsuite>{body}</testsuite>")
    with pytest.raises(ValueError):
        module.evidence(report, "commit", "commit", tmp_path / "inventory.json")


def test_wrong_source_and_missing_evidence_fail(tmp_path):
    with pytest.raises(ValueError):
        module.evidence(tmp_path / "missing", "other", "required", tmp_path / "inventory.json")
    with pytest.raises(FileNotFoundError):
        module.evidence(tmp_path / "missing", "required", "required", tmp_path / "inventory.json")


def write_evidence(tmp_path, *, collected=("first", "second"), executed=("first", "second"),
                   source="commit", run="current", result_run="current"):
    report = tmp_path / "results.xml"
    suite = ET.Element("testsuite")
    for nodeid in executed:
        case = ET.SubElement(suite, "testcase", name=nodeid, time="0.5")
        properties = ET.SubElement(case, "properties")
        ET.SubElement(properties, "property", name="qualification_nodeid", value=nodeid)
        ET.SubElement(properties, "property", name="qualification_run", value=result_run)
    ET.ElementTree(suite).write(report)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"v": 1, "source_commit": source, "run_id": run,
        "selection": list(module.REQUIRED_SUITES), "nodeids": list(collected)}))
    return report, inventory


def test_passing_evidence_records_actual_execution(tmp_path):
    report, inventory = write_evidence(tmp_path)
    result = module.evidence(report, "commit", "commit", inventory)
    assert result["tests_collected"] == result["tests_executed"] == 2
    assert result["tests_skipped"] == 0
    assert result["duration_seconds"] == 1


@pytest.mark.parametrize("changes", [
    {"executed": ("first",)}, {"executed": ("first", "first")},
    {"executed": ("first", "second", "extra")}, {"source": "other"},
    {"result_run": "old-run"}, {"collected": ()}, {"collected": ("first", "first")},
])
def test_partial_duplicate_stale_and_extra_results_cannot_qualify(tmp_path, changes):
    report, inventory = write_evidence(tmp_path, **changes)
    with pytest.raises(ValueError):
        module.evidence(report, "commit", "commit", inventory)


@pytest.mark.parametrize("fault", ["keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf",
                                  "collection_error", "missing_suite", "plugin_deselected"])
def test_inventory_rejects_incomplete_or_filtered_collection(tmp_path, fault):
    from connection_test_inventory import TestInventory
    items = [SimpleNamespace(nodeid=suite.removeprefix("service/") +
             ("/test_policy.py" if not suite.endswith(".py") else "") + "::test_case", user_properties=[])
             for suite in module.REQUIRED_SUITES]
    options = SimpleNamespace(keyword="", markexpr="", deselect=[])
    if fault in {"keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf"}:
        setattr(options, fault, "some_filter")
    if fault == "missing_suite":
        items.pop()
    session = SimpleNamespace(items=items, testsfailed=int(fault == "collection_error"),
                              config=SimpleNamespace(option=options))
    plugin = TestInventory(tmp_path / "inventory.json", "commit")
    if fault == "plugin_deselected":
        plugin.pytest_deselected([items.pop()])
    with pytest.raises(ValueError):
        plugin.pytest_collection_finish(session)
    assert not (tmp_path / "inventory.json").exists()
