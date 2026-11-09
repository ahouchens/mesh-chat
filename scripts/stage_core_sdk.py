"""Stage exact-source public SDK artifacts before tests collect installed consumers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"python": "mesh_chat_core_client-0.3.0.dev0-py3-none-any.whl",
             "typescript": "mesh-chat-core-client-0.3.0-experimental.tgz"}


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/sdk")
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
        phase = "artifact_binding"
        version = subprocess.check_output([node, "--version"], text=True, timeout=15).strip()
        result = verify_artifacts(directory, source, tree, version)
        if source_identity(source) != (source, tree):
            raise RuntimeError("Source changed while staging SDK artifacts")
        if path := os.environ.get("GITHUB_ENV"):
            values = {"MESH_CORE_SDK_ARTIFACTS": str(directory), "MESH_NODE": node, "MESH_NPM_CLI": npm}
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
