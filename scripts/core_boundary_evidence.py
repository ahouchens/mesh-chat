"""Revalidate retained boundary execution without importing pytest or running apps."""

import hashlib
import json

from check_core_ui_boundary import PYTHON_SELECTION, junit_summary, rendered_inventory
from check_core_windows_boundary import CASES, SELECTION as WINDOWS_SELECTION
from connection_evidence import execution_evidence

UI_LEVEL = "rendered_ui_and_in_process_service"
WINDOWS_LEVEL = "windows_named_pipe_and_inprocess_domain"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_report(record, source, tree, level):
    if (type(record.get("v")) is not int or record["v"] != 1
            or record.get("source_commit") != source or record.get("source_tree") != tree
            or record.get("passed") is not True or record.get("evidence_level") != level):
        raise ValueError("Boundary evidence has the wrong source, type or outcome")


def require_summary(record, junit):
    actual = junit_summary(junit)
    if not actual["passed"] or any(record.get(key) != value for key, value in actual.items()):
        raise ValueError("Boundary report does not match its retained JUnit execution and digest")
    return actual


def python_execution(record, junit, source, selection):
    require_summary(record, junit)
    inventory = junit.with_suffix(".inventory.json")
    if record.get("inventory_sha256") != digest(inventory):
        raise ValueError("Boundary collection inventory digest does not match its report")
    executed = execution_evidence(junit, source, source, inventory, selection)
    nodeids = json.loads(inventory.read_text(encoding="utf-8"))["nodeids"]
    # The service pytest root omits service/; the Windows runner uses repo root.
    files = {nodeid.split("::")[0].removeprefix("service/") for nodeid in nodeids}
    if files != {path.removeprefix("service/") for path in selection}:
        raise ValueError("Boundary collection omits or substitutes a required test file")
    return {"execution": executed, "artifacts": {"junit": digest(junit), "inventory": digest(inventory)}}


def ui_evidence(record, directory, source, tree):
    require_report(record, source, tree, UI_LEVEL)
    suites = record.get("suites")
    if not isinstance(suites, dict) or set(suites) != {"python", "rendered_ui"}:
        raise ValueError("Boundary suite inventory is incomplete")
    if any(suite.get("exit_code") != 0 for suite in suites.values()):
        raise ValueError("Boundary subprocess did not pass")
    python = python_execution(suites["python"], directory / "core-ui-boundary-python.xml", source, PYTHON_SELECTION)
    junit = directory / "core-ui-boundary-rendered_ui.xml"
    actual = require_summary(suites["rendered_ui"], junit)
    if not rendered_inventory(junit):
        raise ValueError("Rendered boundary case inventory is incomplete or duplicated")
    rendered = {"execution": {"tests_collected": actual["tests_executed"],
                              "tests_executed": actual["tests_executed"],
                              "tests_passed": actual["tests_executed"], "tests_failed": 0, "tests_skipped": 0},
                "artifacts": {"junit": digest(junit)}}
    return {"core_ui_boundary_python": python, "core_ui_boundary_rendered": rendered}


def windows_evidence(record, directory, source, tree):
    require_report(record, source, tree, WINDOWS_LEVEL)
    junit = directory / "core-windows-boundary.xml"
    executed = python_execution(record, junit, source, WINDOWS_SELECTION)
    inventory = json.loads(junit.with_suffix(".inventory.json").read_text(encoding="utf-8"))
    if set(inventory["nodeids"]) != CASES:
        raise ValueError("Windows boundary case inventory is incomplete")
    return executed
