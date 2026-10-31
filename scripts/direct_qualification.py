"""Required Direct Fabric native execution, bound to source and tested binaries.

The ordinary service suite may skip native environments. These CI entry points
must collect and execute their entire selection with no skips or filters.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess

from connection_evidence import execution_evidence
from connection_test_inventory import TestInventory


SUITES = {
    "recovery": ("service/tests/test_direct_recovery_pipeline.py", "MESH_DIRECT_APP_HOST_BINARY", "shipping_dispatcher"),
    "fabric": ("service/tests/test_direct_fabric_harness.py", "MESH_DIRECT_PROOF_BINARY", "packet_carrier"),
    "setup": ("service/tests/test_direct_setup_pipeline.py", "MESH_DIRECT_APP_HOST_BINARY", "shipping_dispatcher"),
}
LEVEL = "controlled_native_quic_and_python_components"


def git(root, revision):
    return subprocess.check_output(["git", "rev-parse", revision], cwd=root, text=True).strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_suite(path, source, tree, host):
    record = json.loads(path.read_text(encoding="utf-8"))
    suite = record.get("suite")
    if (suite not in SUITES or record.get("passed") is not True or record.get("source_tree") != tree
            or record.get("platform") != host or record.get("evidence_level") != LEVEL
            or record.get("internal_contract") != 1 or not record.get("python_version")):
        raise ValueError("Direct component report has the wrong identity or outcome")
    selection, _, artifact = SUITES[suite]
    binaries = record.get("artifacts")
    if (not isinstance(binaries, dict) or set(binaries) != {artifact}
            or not isinstance(binaries[artifact], str) or not re.fullmatch(r"[a-f0-9]{64}", binaries[artifact])):
        raise ValueError("Direct native artifact identity is missing")
    executed = execution_evidence(path.with_suffix(".xml"), source, source,
                                  path.with_suffix(".inventory.json"), [selection])
    if any(type(record.get(key)) is not type(value) or record[key] != value
           for key, value in executed.items()):
        raise ValueError("Direct report does not match its complete execution inventory")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--expected-source", required=True)
    args = parser.parse_args()
    root = Path.cwd()
    path = root / "dist/reports/direct" / (args.suite + ".json")
    junit, inventory = path.with_suffix(".xml"), path.with_suffix(".inventory.json")
    for old in (path, junit, inventory):
        old.unlink(missing_ok=True)
    source, tree = git(root, "HEAD"), git(root, "HEAD^{tree}")
    if source != args.expected_source or subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root).returncode:
        raise ValueError("Commit tracked changes before exact-source qualification")
    selection, variable, artifact = SUITES[args.suite]
    binary = Path(os.environ.get(variable, ""))
    if not binary.is_file():
        raise ValueError("Required native binary is missing: " + variable)
    artifacts = {artifact: digest(binary)}
    import pytest
    status = pytest.main([selection, "-q", "--junitxml=" + str(junit)],
                         plugins=[TestInventory(inventory, source, [selection])])
    if status != pytest.ExitCode.OK:
        raise SystemExit(int(status))
    if artifacts[artifact] != digest(binary):
        raise ValueError("Native binary changed during qualification")
    if git(root, "HEAD") != source or subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root).returncode:
        raise ValueError("Source changed during qualification")
    record = {
        **execution_evidence(junit, source, source, inventory, [selection]),
        "suite": args.suite, "source_tree": tree, "passed": True, "evidence_level": LEVEL,
        "internal_contract": 1, "platform": os.name, "python_version": platform.python_version(),
        "artifacts": artifacts,
        "scope": "Controlled native transport and service scenarios; not packaged or physical qualification",
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
