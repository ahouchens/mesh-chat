"""Required Windows app pipe qualification; wrong environments fail explicitly."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from tempfile import TemporaryDirectory

from check_core_ui_boundary import junit_summary
from connection_evidence import execution_evidence
from connection_test_inventory import TestInventory

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ("tests/core-ui-boundary/test_windows_pipe.py", "service/tests/test_app_owned_windows.py")
CASES = {SELECTION[0] + "::" + name for name in (
    "test_windows_pipe_settings_mutations_read_back_from_vault",
    "test_windows_pipe_call_control_signs_and_retires_a_real_call",
    "test_windows_pipe_creates_a_fresh_profile_with_one_durable_key",
)}
CASES |= {SELECTION[1] + "::" + name for name in (
    "test_actual_dpapi_key_reopens_and_is_bound_to_its_own_app_directory",
    "test_corrupted_key_is_never_silently_replaced[]",
    "test_corrupted_key_is_never_silently_replaced[unknown-key-format]",
    r"test_corrupted_key_is_never_silently_replaced[mesh-core-app-key-v1\x00broken]",
    "test_missing_original_app_key_does_not_generate_a_replacement_for_an_existing_vault",
    "test_ordinary_host_uses_real_dpapi_and_pipe_without_private_core_commands",
)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    args = parser.parse_args()
    reports = ROOT / "dist/reports"
    reports.mkdir(parents=True, exist_ok=True)
    output = reports / "core-windows-boundary.json"
    output.unlink(missing_ok=True)
    if os.name != "nt":
        raise RuntimeError("Required Windows app boundary environment is unavailable")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if source != args.expected_source or dirty:
        raise ValueError("Commit the exact required source before Windows boundary qualification")
    import pytest
    junit = reports / "core-windows-boundary.xml"
    inventory = junit.with_suffix(".inventory.json")
    for path in (junit, inventory):
        path.unlink(missing_ok=True)
    scratch = ROOT / ".test-tmp/core-windows-boundary"
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with TemporaryDirectory(prefix="pytest-", dir=scratch) as temporary:
        status = pytest.main([*SELECTION, "-q", "--rootdir=" + str(ROOT), "--junitxml=" + str(junit),
                             "--basetemp=" + temporary, "-o", "cache_dir=" + str(scratch / "cache")],
                            plugins=[TestInventory(inventory, source, SELECTION)])
    summary = junit_summary(junit) if junit.exists() else {"passed": False, "missing_junit": True}
    if status == pytest.ExitCode.OK:
        execution_evidence(junit, source, source, inventory, SELECTION)
        if set(json.loads(inventory.read_text(encoding="utf-8"))["nodeids"]) != CASES:
            raise ValueError("Required Windows boundary case inventory is incomplete")
    result = {"v": 1, "source_commit": source,
              "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
              **summary, "passed": summary["passed"] and status == pytest.ExitCode.OK,
              "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest() if inventory.exists() else None,
              "scope": "Production Windows app pipe and DPAPI host components; explicit test-only Vault storage; no EFS, packaged, media or physical qualification",
              "evidence_level": "windows_named_pipe_and_inprocess_domain", "wall_seconds": time.monotonic() - started}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
