"""Aggregate exact release artifacts against a qualified source and component matrix.

This is the release-gating step: a signing/publishing workflow must run it on the
exact files it intends to publish, for the exact source the qualification matrix
covered. It performs no build, no network access and no publication. Missing,
stale, partial or mismatched evidence fails closed.

Usage:
    python scripts/release_qualification.py --qualification dist/reports/connection-qualification.json \
        --source <commit> --tree <tree> --version 1.2.3 \
        --artifact setup=path/Mesh-Chat_1.2.3_x64-setup.exe \
        --artifact msi=path/Mesh-Chat_1.2.3_x64_en-US.msi \
        --artifact apk=path/mesh-chat-1.2.3-android-arm64-release.apk \
        --output dist/reports/release-qualification.json
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from connection_ci import SUITES


MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
SUITE_KEYS = {"suite", "evidence_level", "source_commit", "source_tree",
              "tests", "checks", "artifacts", "cleanup", "report_sha256"}
COUNT_KEYS = {"collected", "executed", "passed", "failed", "skipped"}
# Component records a required suite must contribute to the uniform manifest.
REQUIRED_COMPONENTS = {
    "policy": {"policy"},
    "verification": {"windows_transport", "windows_packaged_lifecycle",
                     "windows_packaged_transport", "windows_packaged_pairing"},
    "android": {"android_webrtc", "android_signaling"},
    "direct": {"direct_Linux_recovery", "direct_Linux_setup", "direct_Linux_fabric",
               "direct_Windows_recovery", "direct_Windows_setup", "direct_Windows_fabric"},
    "layout": set(),
}
ARTIFACT_KINDS = ("setup", "msi", "apk")


def digest(path):
    if not path.is_file():
        raise ValueError(f"Release artifact is missing: {path.name}")
    size = path.stat().st_size
    if not 0 < size <= MAX_ARTIFACT_BYTES:
        raise ValueError(f"Release artifact has an invalid size: {path.name}")
    with path.open("rb") as stream:
        return {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "bytes": size}


def expected_name(kind, version):
    names = {"setup": f"Mesh-Chat_{version}_x64-setup.exe",
             "msi": f"Mesh-Chat_{version}_x64_en-US.msi",
             "apk": f"mesh-chat-{version}-android-arm64-release.apk"}
    return names[kind]


def records(manifest):
    """Select the uniform per-suite records from a qualification manifest."""
    suites = manifest.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ValueError("Qualification manifest has no uniform suite evidence")
    for record in suites:
        if not isinstance(record, dict) or set(record) != SUITE_KEYS:
            raise ValueError("Qualification suite record is not uniform")
        tests, checks = record["tests"], record["checks"]
        if tests is not None and (set(tests) != COUNT_KEYS
                                  or any(type(value) is not int or value < 0 for value in tests.values())
                                  or tests["failed"] or tests["skipped"]):
            raise ValueError("Required suite evidence failed, skipped or is incomplete")
        if checks is not None and (type(checks) is not int or checks <= 0):
            raise ValueError("Required suite check count is incomplete")
        if tests is None and checks is None:
            raise ValueError("Required suite reported no executed work")
        if not isinstance(record["report_sha256"], str) or not re.fullmatch(
                r"[a-f0-9]{64}", record["report_sha256"]):
            raise ValueError("Required suite report digest is missing")
    names = [record["suite"] for record in suites]
    if len(set(names)) != len(names):
        raise ValueError("Qualification suite identities are duplicated")
    return suites


def qualification(path, source, tree):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (type(manifest.get("version")) is not int or manifest["version"] != 1
            or manifest.get("passed") is not True
            or manifest.get("source_commit") != source or manifest.get("source_tree") != tree):
        raise ValueError("Qualification manifest does not cover this exact source")
    required = manifest.get("required")
    if not isinstance(required, list) or not required or not set(required) <= set(SUITES):
        raise ValueError("Qualification manifest has an invalid suite selection")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != set(SUITES):
        raise ValueError("Qualification manifest has an incomplete job inventory")
    if any(jobs[name] != "success" for name in required):
        raise ValueError("A required qualification suite did not succeed")
    suites = records(manifest)
    present = {record["suite"] for record in suites}
    for name in required:
        if not REQUIRED_COMPONENTS[name] <= present:
            raise ValueError(f"Qualification is missing component evidence for {name}")
    components = manifest.get("components")
    if not isinstance(components, dict) or "policy_tests_executed" not in components:
        raise ValueError("Qualification component summary is missing")
    return suites


def contract(repository):
    value = json.loads((repository / "contracts/core-api/operations-v1.json").read_text(encoding="utf-8"))
    if (value.get("api_major"), value.get("api_minor")) != (1, 0):
        raise ValueError("Unsupported public API contract version")
    if value.get("status") != "experimental_design":
        raise ValueError("Public API stability is not declared experimental")
    return {"major": value["api_major"], "minor": value["api_minor"], "stability": "experimental"}


def aggregate(*, qualification_path, artifacts, source, tree, version, repository):
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Release version is not semantic")
    suites = qualification(qualification_path, source, tree)
    if set(artifacts) != set(ARTIFACT_KINDS):
        raise ValueError("Release artifact inventory is incomplete")
    digests = {}
    for kind, path in artifacts.items():
        if path.name != expected_name(kind, version):
            raise ValueError(f"Release artifact name does not bind the version: {path.name}")
        digests[kind] = digest(path)
    return {
        "v": 1,
        "passed": True,
        "release_version": version,
        "source_commit": source,
        "source_tree": tree,
        "qualification_sha256": hashlib.sha256(qualification_path.read_bytes()).hexdigest(),
        "api": contract(repository),
        "internal_contract": 1,
        "evidence_level": "release_artifacts_with_component_qualification",
        "scope": "Exact release binaries bound to the qualified source and component matrix; "
                 "packaged Windows-Android interoperability and physical acceptance remain unqualified",
        "suites": suites,
        "artifacts": digests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--artifact", action="append", default=[], metavar="KIND=PATH")
    parser.add_argument("--source", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifacts = {}
    for value in args.artifact:
        kind, _, path = value.partition("=")
        if kind in artifacts or not path:
            raise SystemExit("Release artifact arguments must be unique KIND=PATH pairs")
        artifacts[kind] = Path(path)
    result = aggregate(qualification_path=args.qualification, artifacts=artifacts,
                       source=args.source, tree=args.tree, version=args.version,
                       repository=Path.cwd())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "artifacts": sorted(result["artifacts"])}))


if __name__ == "__main__":
    main()
