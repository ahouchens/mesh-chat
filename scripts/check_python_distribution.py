"""Build/install the standalone client artifact; never package the service."""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "sdk/python"


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"SDK build/install exited {result.returncode}\n" + result.stdout[-3000:] + result.stderr[-3000:])
    return result.stdout


def verify(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or len(names) > 100
                or sum(info.file_size for info in archive.infolist()) > 2 * 1024 * 1024):
            raise ValueError("Invalid standalone archive bounds")
        for name in names:
            if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
                raise ValueError("Archive path escapes package")
            modules = {"mesh_chat_core_client/" + item + ".py" for item in
                       ("__init__", "client", "compatibility", "errors", "framing", "limits", "protocol", "types", "windows")}
            if not (name in modules or name.startswith("mesh_chat_core_client-0.3.0.dev0.dist-info/")):
                raise ValueError("Non-client payload entered standalone wheel")
            if name.endswith((".dll", ".so", ".pyc")):
                raise ValueError("Runtime/native payload entered standalone wheel")
        if "mesh_chat_core_client/client.py" not in names:
            raise ValueError("Missing standalone client")
        if "mesh_chat_core_client-0.3.0.dev0.dist-info/licenses/LICENSE" not in names:
            raise ValueError("Missing client license")
    return {"artifact": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "size_bytes": wheel.stat().st_size, "files": sorted(names)}


def stage(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mesh-core-python-distribution-") as temporary:
        work = Path(temporary)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PIP_CACHE_DIR": str(work / "cache"),
               "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
        source = work / "package"
        shutil.copytree(PACKAGE, source, ignore=shutil.ignore_patterns("build", "dist", "*.egg-info", "__pycache__", ".pytest_cache"))
        run([sys.executable, "-m", "pip", "wheel", str(source), "--no-index", "--no-deps", "--no-build-isolation",
             "--wheel-dir", str(output)], work, env)
        wheels = list(output.glob("mesh_chat_core_client-0.3.0.dev0-*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one candidate standalone wheel")
        wheel = wheels[0]
        result = verify(wheel)
        site = work / "site"
        run([sys.executable, "-m", "pip", "install", str(wheel), "--target", str(site),
             "--no-deps", "--no-index", "--no-compile"], work, env)
        smoke = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import mesh_chat_core_client as package
assert package.__version__ == '0.3.0.dev0'
assert pathlib.Path(package.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
assert not any(name == 'mesh_chat' or name.startswith('mesh_chat.') for name in sys.modules)
assert callable(package.CoreClient.enqueue_draft)
for name in ('call_operation_list','call_operation_query','call_operation_abandon',
             'pairing_begin','pairing_query','pairing_cancel'):
    assert callable(getattr(package.CoreClient, name, None)), name
print(json.dumps({'version':package.__version__,'installed_outside_checkout':True,'private_runtime_imported':False}))
"""
        result["consumer"] = json.loads(run([sys.executable, "-I", "-S", "-B", "-c", smoke, str(site)], work, env))
        result["artifact_path"] = str(wheel.resolve())
        result["qualification"] = "archive_and_isolated_import_only; real-host tests reported separately"
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/sdk/python")
    args = parser.parse_args()
    result = stage(args.output_dir.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "distribution-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
