"""Fail closed on missing, skipped, or failing required connection tests."""

import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def evidence(junit: Path, source: str, expected: str) -> dict:
    if source != expected:
        raise ValueError("Qualification source does not match the required commit")
    root = ET.parse(junit).getroot()
    tests = list(root.iter("testcase"))
    skipped = sum(test.find("skipped") is not None for test in tests)
    failed = sum(test.find("failure") is not None or test.find("error") is not None for test in tests)
    errors = len(list(root.iter("error")))
    if not tests or skipped or failed or errors:
        raise ValueError(f"Required connection suite did not pass: tests={len(tests)}, skipped={skipped}, failed={failed}, errors={errors}")
    return {
        "v": 1, "suite": "connection-policy", "source_commit": source,
        "evidence_level": "simulated_and_in_process", "internal_contract": 1,
        "tests_collected": len(tests), "tests_executed": len(tests),
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
    args = parser.parse_args()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = evidence(args.junit, source, args.expected_source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
