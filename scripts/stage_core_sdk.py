"""Stage exact-source public SDK artifacts before tests collect installed consumers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"python": "mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl",
             "typescript": "mesh-chat-core-client-0.3.0-experimental.tgz"}
BASELINE = "174728edad62aae6ef16e95b075183d06c5cdda3"
BASELINE_TREE = "239d041f87b26f50879008ac947481464dcf4551"
UPGRADE_FILES = {"python_service_carrier": "mesh_chat_service-0.9.66-py3-none-any.whl",
                 "typescript": "mesh-chat-core-client-0.2.0-experimental.tgz"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tools(environment=os.environ):
    node = environment.get("MESH_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("Node >=22 is required for installed SDK consumers")
    node = str(Path(shutil.which(node) or node).resolve())
    version = subprocess.check_output([node, "--version"], text=True, timeout=15).strip()
    if not version.startswith("v") or int(version[1:].split(".")[0]) < 22:
        raise RuntimeError("Node >=22 is required for installed SDK consumers")
    npm = environment.get("MESH_NPM_CLI")
    if not npm:
        shim = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not shim:
            raise RuntimeError("Local npm CLI is required")
        npm = str(Path(shim).parent / "node_modules/npm/bin/npm-cli.js" if os.name == "nt" else Path(shim).resolve())
    npm = str(Path(npm).resolve())
    if not Path(npm).is_file():
        raise RuntimeError("Local npm CLI is required")
    return node, npm


def verify_artifacts(directory, source, tree, node_version):
    records = {}
    for language, filename in ARTIFACTS.items():
        artifact = directory / language / filename
        report = directory / language / "distribution-report.json"
        if (not artifact.is_file() or not 0 < artifact.stat().st_size <= 2 * 1024 * 1024
                or not report.is_file() or not 0 < report.stat().st_size <= 128 * 1024):
            raise ValueError("Required candidate SDK artifact or report is missing")
        value = json.loads(report.read_text())
        digest = sha256(artifact)
        if (value.get("artifact") != filename or value.get("sha256") != digest
                or Path(value.get("artifact_path", "")).resolve() != artifact.resolve()
                or not isinstance(value.get("consumer"), dict)
                or value["consumer"].get("installed_outside_checkout") is not True):
            raise ValueError("Candidate SDK artifact does not match its isolated consumer report")
        if language == "python":
            if value["consumer"].get("version") != "0.3.0.dev0" or value["consumer"].get("private_runtime_imported") is not False:
                raise ValueError("Python candidate isolated consumer did not establish SDK-only imports")
        elif value.get("version") != "0.3.0-experimental" or value["consumer"].get("imports_public_package") is not True:
            raise ValueError("TypeScript candidate isolated consumer did not import the public package")
        records[language] = {"artifact": f"{language}/{filename}", "sha256": digest,
                             "report_sha256": sha256(report), "size_bytes": artifact.stat().st_size}
    return {"v": 1, "passed": True, "source_commit": source, "source_tree": tree,
            "evidence_level": "public_sdk_archive_and_isolated_import_staging",
            "scope": "Prerequisite staging only; real host execution is reported by installed-consumer tests",
            "node_version": node_version, "artifacts": records}


def stage(directory, node, npm):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MESH_NODE": node, "MESH_NPM_CLI": npm}
    commands = ([node, str(ROOT / "node_modules/typescript/bin/tsc"), "-p", str(ROOT / "sdk/typescript")],
                [sys.executable, str(ROOT / "scripts/check_python_distribution.py"), "--output-dir", str(directory / "python")],
                [node, str(ROOT / "scripts/check_typescript_distribution.mjs"), "--output-dir", str(directory / "typescript")])
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=environment, check=True, capture_output=True, text=True, timeout=180)


def stage_upgrade(directory, node, npm):
    # Exact source is mandatory. A shallow checkout must fetch it; never use HEAD
    # or substitute candidate code when the historical commit is unavailable.
    actual = subprocess.check_output(["git", "rev-parse", BASELINE + "^{tree}"], cwd=ROOT, text=True, timeout=15).strip()
    if actual != BASELINE_TREE:
        raise ValueError("Pinned upgrade baseline tree is unavailable")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MESH_NODE": node, "MESH_NPM_CLI": npm}
    subprocess.run([sys.executable, str(ROOT / "scripts/check_core_sdk_upgrade.py"), "--output-dir", str(directory),
                    "--node", node, "--npm-cli", npm], cwd=ROOT, env=environment,
                   check=True, capture_output=True, text=True, timeout=300)


def verify_upgrade(directory):
    path = directory / "upgrade-artifacts.json"
    if not path.is_file() or not 0 < path.stat().st_size <= 128 * 1024:
        raise ValueError("Pinned upgrade build report is missing")
    value = json.loads(path.read_text())
    if (type(value.get("v")) is not int or value["v"] != 1 or value.get("baseline_source") != BASELINE
            or value.get("baseline_tree") != BASELINE_TREE
            or value.get("provenance") != "Component artifacts rebuilt from exact Git source; not retained platform binaries"
            or not isinstance(value.get("artifacts"), dict) or set(value["artifacts"]) != set(UPGRADE_FILES)):
        raise ValueError("Pinned upgrade build has incorrect source or provenance")
    records = {}
    for kind, name in UPGRADE_FILES.items():
        artifact = directory / name
        item = value["artifacts"][kind]
        if (not artifact.is_file() or not 0 < artifact.stat().st_size <= 4 * 1024 * 1024
                or not isinstance(item, dict) or item.get("filename") != name
                or type(item.get("size_bytes")) is not int or item["size_bytes"] != artifact.stat().st_size
                or item.get("sha256") != sha256(artifact)):
            raise ValueError("Pinned upgrade artifact differs from its build report")
        records[kind] = dict(item)
    return {"baseline_source": BASELINE, "baseline_tree": BASELINE_TREE,
            "provenance": value["provenance"], "report_sha256": sha256(path), "artifacts": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/sdk")
    parser.add_argument("--upgrade-dir", type=Path, default=ROOT / "dist/sdk-upgrade")
    parser.add_argument("--report", type=Path, default=ROOT / "dist/reports/core-sdk-distribution-staging.json")
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.unlink(missing_ok=True)
    result = {"v": 1, "passed": False, "evidence_level": "public_sdk_archive_and_isolated_import_staging"}
    phase = "source_tools"
    try:
        from test_packaged_lifecycle import source_identity
        source, tree = source_identity(args.expected_source)
        node, npm = tools()
        directory = args.output_dir.resolve()
        phase = "candidate_staging"
        stage(directory, node, npm)
        phase = "pinned_upgrade_staging"
        upgrade_directory = args.upgrade_dir.resolve()
        stage_upgrade(upgrade_directory, node, npm)
        phase = "artifact_binding"
        version = subprocess.check_output([node, "--version"], text=True, timeout=15).strip()
        result = verify_artifacts(directory, source, tree, version)
        result["pinned_upgrade"] = verify_upgrade(upgrade_directory)
        if source_identity(source) != (source, tree):
            raise RuntimeError("Source changed while staging SDK artifacts")
        if path := os.environ.get("GITHUB_ENV"):
            consumer_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()).resolve()
            if not consumer_temp.is_dir() or consumer_temp.is_relative_to(ROOT):
                raise ValueError("Installed SDK consumer temporary directory must be outside the checkout")
            values = {"MESH_CORE_SDK_ARTIFACTS": str(directory), "MESH_NODE": node, "MESH_NPM_CLI": npm,
                      "MESH_CORE_SDK_UPGRADE_ARTIFACTS": str(upgrade_directory),
                      "MESH_CORE_CONSUMER_TMP": str(consumer_temp)}
            if any("\n" in value or "\r" in value for value in values.values()):
                raise ValueError("Invalid SDK staging environment path")
            with open(path, "a", encoding="utf-8") as stream:
                for key, value in values.items():
                    stream.write(f"{key}={value}\n")
    except Exception as error:
        result.update(passed=False, phase=phase, failure_type=type(error).__name__)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"artifacts"}}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
