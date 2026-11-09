"""Rebuild actual pinned component fixtures; no publication or platform builds."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "tests/core-sdk-upgrade/fixtures.json").read_text())


def run(args, cwd, env):
    result = subprocess.run([str(value) for value in args], cwd=cwd, env=env,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Pinned fixture build failed\n" + (result.stdout + result.stderr).decode("utf-8", "replace")[-6000:])
    return result.stdout


def stage(output, node, tsc, type_roots, npm_cli):
    source = FIXTURES["baseline_source"]
    with tempfile.TemporaryDirectory(prefix="mesh-core-pinned-upgrade-") as temporary:
        work = Path(temporary)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
               "PIP_CACHE_DIR": str(work / "pip-cache"), "npm_config_cache": str(work / "npm-cache")}
        archive = run(["git", "archive", "--format=zip", source, "service/src", "service/pyproject.toml", "sdk/typescript", "LICENSE"], ROOT, env)
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            if sum(info.file_size for info in files.infolist()) > 32 * 1024 * 1024:
                raise ValueError("Pinned source exceeds fixture bounds")
            for info in files.infolist():
                target = work / info.filename
                if not target.resolve().is_relative_to(work.resolve()) or "\\" in info.filename:
                    raise ValueError("Pinned source archive escapes fixture root")
            files.extractall(work)
        output.mkdir(parents=True, exist_ok=True)
        run([sys.executable, "-m", "pip", "wheel", work / "service", "--no-index", "--no-deps",
             "--no-build-isolation", "--wheel-dir", output], work, env)
        run([node, tsc, "-p", work / "sdk/typescript", "--typeRoots", type_roots], work, env)
        packed = json.loads(run([node, npm_cli, "pack", "--json", "--ignore-scripts", "--offline"], work / "sdk/typescript", env))[0]
        filename = packed["filename"]
        if Path(filename).name != filename:
            raise ValueError("Invalid pinned artifact name")
        shutil.copyfile(work / "sdk/typescript" / filename, output / filename)
        artifacts = {}
        for kind, name in {"python_service_carrier": "mesh_chat_service-0.9.66-py3-none-any.whl", "typescript": filename}.items():
            path = output / name
            artifacts[kind] = {"filename": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
        result = {"v": 1, "baseline_source": source,
                  "baseline_tree": run(["git", "rev-parse", source + "^{tree}"], ROOT, env).decode().strip(),
                  "provenance": FIXTURES["provenance"], "artifacts": artifacts,
                  "python": platform.python_version(), "node": run([node, "--version"], work, env).decode().strip(),
                  "os": platform.system(), "architecture": platform.machine(),
                  "qualification": "fixture_build_only; installed client/host and storage tests run separately"}
        (output / "upgrade-artifacts.json").write_text(json.dumps(result, indent=2) + "\n")
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/sdk-upgrade")
    parser.add_argument("--node", default=os.environ.get("MESH_NODE") or shutil.which("node"))
    parser.add_argument("--tsc", type=Path, default=ROOT / "node_modules/typescript/bin/tsc")
    parser.add_argument("--type-roots", type=Path, default=ROOT / "node_modules/@types")
    parser.add_argument("--npm-cli", default=os.environ.get("MESH_NPM_CLI"))
    args = parser.parse_args()
    npm = args.npm_cli
    if npm is None:
        shim = Path(shutil.which("npm.cmd" if os.name == "nt" else "npm"))
        npm = shim.parent / "node_modules/npm/bin/npm-cli.js" if os.name == "nt" else shim.resolve()
    print(json.dumps(stage(args.output_dir.resolve(), args.node, args.tsc.resolve(), args.type_roots.resolve(), npm)))


if __name__ == "__main__":
    main()
