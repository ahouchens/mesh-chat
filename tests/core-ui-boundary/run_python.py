"""Collect and run every Python boundary case with the existing inventory gate."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import pytest
from connection_evidence import execution_evidence
from connection_test_inventory import TestInventory


SELECTION = (
    "service/tests/connection/test_ui_core_boundary_requests.py",
    "service/tests/connection/test_ui_core_boundary_ci.py",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--junit", required=True, type=Path)
    args = parser.parse_args()
    inventory = args.junit.with_suffix(".inventory.json")
    inventory.unlink(missing_ok=True)
    status = pytest.main([*SELECTION, "-q", f"--junitxml={args.junit}"],
                         plugins=[TestInventory(inventory, args.source, SELECTION)])
    if status != pytest.ExitCode.OK:
        return int(status)
    execution_evidence(args.junit, args.source, args.source, inventory, SELECTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
