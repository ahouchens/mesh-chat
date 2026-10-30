"""Fail closed on missing, skipped, or failing required connection tests."""

import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from connection_test_inventory import REQUIRED_SUITES, TestInventory


def evidence(junit: Path, source: str, expected: str, inventory: Path) -> dict:
    if source != expected:
        raise ValueError("Qualification source does not match the required commit")
    root = ET.parse(junit).getroot()
    tests = list(root.iter("testcase"))
    skipped = sum(test.find("skipped") is not None for test in tests)
    failed = sum(test.find("failure") is not None or test.find("error") is not None for test in tests)
    errors = len(list(root.iter("error")))
    if not tests or skipped or failed or errors:
        raise ValueError(f"Required connection suite did not pass: tests={len(tests)}, skipped={skipped}, failed={failed}, errors={errors}")
    collected = json.loads(inventory.read_text(encoding="utf-8"))
    if (collected.get("v") != 1 or collected.get("source_commit") != expected
            or collected.get("selection") != list(REQUIRED_SUITES)):
        raise ValueError("Required collection inventory has the wrong version, source or selection")
    nodeids = collected.get("nodeids")
    if (not isinstance(nodeids, list) or not nodeids or not all(isinstance(nodeid, str) for nodeid in nodeids)
            or len(set(nodeids)) != len(nodeids) or not collected.get("run_id")):
        raise ValueError("Required collection inventory is empty or invalid")
    executed = []
    for test in tests:
        properties = {entry.get("name"): entry.get("value")
                      for entry in test.findall("properties/property")}
        if properties.get("qualification_run") != collected["run_id"]:
            raise ValueError("Test result does not belong to this qualification run")
        executed.append(properties.get("qualification_nodeid"))
    if len(set(executed)) != len(executed) or set(executed) != set(nodeids):
        raise ValueError("Executed tests do not match the complete required collection")
    return {
        "v": 1, "suite": "connection-policy", "source_commit": source,
        "evidence_level": "simulated_and_in_process", "internal_contract": 1,
        "qualification_run": collected["run_id"],
        "tests_collected": len(nodeids), "tests_executed": len(tests),
        "tests_passed": len(tests), "tests_failed": failed, "tests_skipped": skipped,
        "required": True,
        "duration_seconds": sum(float(test.get("time", 0)) for test in tests),
        "scope": "Policy and private adapter tests; no native, packaged or physical qualification",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="Run the complete required selection before validation")
    args = parser.parse_args()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    inventory = args.junit.with_suffix(".inventory.json")
    if args.run:
        import pytest
        if source != args.expected_source:
            raise ValueError("Qualification source does not match the required commit")
        if subprocess.run(["git", "diff", "--quiet", "HEAD"]).returncode:
            raise ValueError("Commit tracked changes before recording exact-source qualification")
        # Never accept an old report when collection or execution aborts.
        for old in (args.junit, inventory, args.output):
            old.unlink(missing_ok=True)
        status = pytest.main([*REQUIRED_SUITES, "--junitxml=" + str(args.junit)],
                             plugins=[TestInventory(inventory, source)])
        if status != pytest.ExitCode.OK:
            raise SystemExit(int(status))
    result = evidence(args.junit, source, args.expected_source, inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
