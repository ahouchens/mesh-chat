"""Install the independent application outside the checkout from exact SDK bytes.

Staging/import evidence only. The normal packaged host and actual peer receipts
are required separately; successful staging never establishes SC21 traffic.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from stage_core_sdk import ARTIFACTS, tools

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "examples/typescript-independent-consumer"
FILES = ("package.json", "consumer.mjs", "runtime.mjs", "bootstrap-check.mjs", "pairing-check.mjs", "README.md")
LEVEL = "independent_public_sdk_application_staging"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sdk_input(directory, report, source, tree):
    if not report.is_file() or not 0 < report.stat().st_size <= 128 * 1024:
        raise ValueError("Source-bound SDK staging report is missing")
    value = json.loads(report.read_text(encoding="utf-8"))
    artifact = directory / "typescript" / ARTIFACTS["typescript"]
    item = value.get("artifacts", {}).get("typescript", {})
    if (value.get("v") != 1 or type(value.get("v")) is not int or value.get("passed") is not True
            or value.get("source_commit") != source or value.get("source_tree") != tree
            or value.get("evidence_level") != "public_sdk_archive_and_isolated_import_staging"
            or item.get("artifact") != "typescript/" + ARTIFACTS["typescript"]
            or not artifact.is_file() or not 0 < artifact.stat().st_size <= 2 * 1024 * 1024
            or item.get("sha256") != digest(artifact)
            or type(item.get("size_bytes")) is not int or item["size_bytes"] != artifact.stat().st_size):
        raise ValueError("Independent application SDK differs from exact-source staging")
    return artifact


def outside_directory(parent):
    parent = parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_relative_to(ROOT):
        raise ValueError("Independent application must be installed outside the checkout")
    return Path(tempfile.mkdtemp(prefix="mesh-independent-application-", dir=parent)).resolve()


def cleanup(directory, parent):
    parent = parent.resolve(strict=True)
    if (directory.parent != parent or not directory.name.startswith("mesh-independent-application-")
            or directory.is_symlink() or directory.resolve(strict=True) != directory):
        raise ValueError("Independent staging cleanup ownership changed")
    target = str(directory)
    if os.name == "nt":
        target = "\\\\?\\UNC\\" + target[2:] if target.startswith("\\\\") else "\\\\?\\" + target
    shutil.rmtree(target)


def install_typescript(directory, artifact, node, npm):
    if directory.resolve().is_relative_to(ROOT):
        raise ValueError("Independent application cannot resolve checkout dependencies")
    source_files = {}
    for name in FILES:
        source = APPLICATION / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("Independent application source input is invalid")
        shutil.copyfile(source, directory / name)
        source_files[name] = digest(source)
    environment = {name: value for name, value in os.environ.items()
                   if name not in {"NODE_PATH", "NODE_OPTIONS", "PYTHONPATH"}
                   and not name.startswith(("GITHUB_", "ACTIONS_", "INPUT_"))}
    environment.update(npm_config_cache=str(directory / "npm-cache"),
                       npm_config_update_notifier="false")
    subprocess.run([node, npm, "install", str(artifact.resolve()), "--offline", "--ignore-scripts",
                    "--no-audit", "--no-fund", "--no-save", "--package-lock=false"],
                   cwd=directory, env=environment, capture_output=True, check=True, timeout=90)
    for source in (name for name in FILES if name.endswith(".mjs")):
        subprocess.run([node, "--check", source], cwd=directory, env=environment,
                       capture_output=True, check=True, timeout=15)
    probe = """
import { CoreClient, CoreError } from '@mesh-chat/core-client';
import { connectNamedPipe } from '@mesh-chat/core-client/node';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
console.log(JSON.stringify({entry:realpathSync(fileURLToPath(import.meta.resolve('@mesh-chat/core-client'))),
  client:typeof CoreClient.open==='function',errors:typeof CoreError==='function',transport:typeof connectNamedPipe==='function'}));
"""
    completed = subprocess.run([node, "--input-type=module", "-e", probe], cwd=directory,
                               env=environment, capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(completed.stdout)
    package = (directory / "node_modules/@mesh-chat/core-client").resolve(strict=True)
    entry = Path(result["entry"]).resolve(strict=True)
    if (not package.is_relative_to(directory.resolve()) or not entry.is_relative_to(package)
            or result.get("client") is not True or result.get("errors") is not True or result.get("transport") is not True
            or json.loads((package / "package.json").read_text())["version"] != "0.3.0-experimental"
            or any(digest(directory / name) != expected for name, expected in source_files.items())):
        raise ValueError("Independent application did not resolve the installed public SDK")
    return {"application_files": source_files, "installed_sdk_entry": entry.relative_to(directory).as_posix(),
            "installed_outside_checkout": True, "imports_public_package": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--sdk-directory", type=Path, default=ROOT / "dist/sdk")
    parser.add_argument("--sdk-report", type=Path, default=ROOT / "dist/reports/core-sdk-distribution-staging.json")
    parser.add_argument("--temporary-root", type=Path,
                        default=Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()))
    parser.add_argument("--report", type=Path, default=ROOT / "dist/reports/independent-consumer-staging.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL,
              "scope": "Outside-checkout application installation and SDK import only; no packaged host or SC21 receipt traffic"}
    directory = None
    phase = "source_sdk_binding"
    try:
        from test_packaged_lifecycle import source_identity
        source, tree = source_identity(args.expected_source)
        artifact = sdk_input(args.sdk_directory, args.sdk_report, source, tree)
        node, npm = tools()
        phase = "outside_checkout_installation"
        directory = outside_directory(args.temporary_root)
        installed = install_typescript(directory, artifact, node, npm)
        if source_identity(source) != (source, tree) or digest(artifact) != json.loads(
                args.sdk_report.read_text())["artifacts"]["typescript"]["sha256"]:
            raise ValueError("Source or SDK changed while staging application")
        result.update(passed=True, source_commit=source, source_tree=tree, application=installed,
                      sdk_sha256=digest(artifact), sdk_staging_report_sha256=digest(args.sdk_report))
    except Exception as error:
        result.update(phase=phase, failure_type=type(error).__name__)
    finally:
        if directory is not None:
            # Only the exact newly created, checked root is owned by this run.
            try:
                cleanup(directory, args.temporary_root)
            except OSError:
                result.update(passed=False, cleanup_failed=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "evidence_level": LEVEL}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
