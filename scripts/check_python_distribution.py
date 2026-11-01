"""Build the Python wheel, install it into an empty target and import it.

This qualifies the packaged Python artifact without publishing anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service"


def run(arguments: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        arguments, cwd=cwd, env=env, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mesh-chat-wheel-") as temporary:
        work = Path(temporary)
        wheels = work / "wheels"
        wheels.mkdir()
        run([sys.executable, "-m", "pip", "wheel", str(SERVICE), "--no-deps",
             "--no-build-isolation", "--wheel-dir", str(wheels)], cwd=work)
        artifacts = sorted(wheels.glob("mesh_chat_service-*.whl"))
        if len(artifacts) != 1:
            raise SystemExit(f"expected one wheel, found {artifacts}")
        target = work / "site"
        run([sys.executable, "-m", "pip", "install", str(artifacts[0]), "--no-deps",
             "--target", str(target)], cwd=work)
        environment = {**os.environ, "PYTHONPATH": str(target)}
        code = (
            "import json, importlib.metadata as metadata, os, pathlib, tempfile\n"
            "import mesh_chat.core_api as api\n"
            "from mesh_chat.core_api.client import CoreClient\n"
            "from mesh_chat.core_api.composition import bind_service_session\n"
            "from mesh_chat.core_api.session import Grant\n"
            "from mesh_chat.service import MeshChatService\n"
            "from mesh_chat.vault import VaultStore\n"
            "distribution = metadata.distribution('mesh-chat-service')\n"
            "scripts = {entry.name for entry in distribution.entry_points}\n"
            "assert scripts >= {'mesh-chat-service', 'mesh-chat-core'}, scripts\n"
            "assert api.__version__ == '0.2.0-experimental', api.__version__\n"
            "assert CoreClient.__name__ == 'CoreClient'\n"
            "root = pathlib.Path(tempfile.mkdtemp(prefix='mesh-chat-consumer-'))\n"
            "MeshChatService._start_network = lambda *_: None\n"
            "MeshChatService._prepare_lan_fallback = lambda *_: None\n"
            "store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)\n"
            "service = MeshChatService(store, root, lambda _: None)\n"
            "service.create_profile('Packaged consumer')\n"
            "try:\n"
            "    grant = Grant('packaged-consumer', frozenset({'observe', 'read'}), ('local',))\n"
            "    session = bind_service_session(service, lambda: grant)\n"
            "    caps = session.request({'api_version': 1, 'request_id': 'consumer:1',\n"
            "                            'operation': 'runtime.capabilities', 'params': {}})\n"
            "    assert caps['ok'], caps\n"
            "    profile = caps['result']['profiles'][0]\n"
            "    listed = session.request({'api_version': 1, 'request_id': 'consumer:2',\n"
            "                              'operation': 'workspace.query',\n"
            "                              'params': {'profile': profile}})\n"
            "    assert listed['ok'], listed\n"
            "finally:\n"
            "    service.close()\n"
            "print(json.dumps({'version': api.__version__, 'scripts': sorted(scripts),\n"
            "                  'facade': 'capabilities+workspace.query'}))\n"
        )
        output = run([sys.executable, "-c", code], cwd=work, env=environment)
        script = target / "bin" / ("mesh-chat-core.exe" if os.name == "nt"
                                    else "mesh-chat-core")
        if not script.is_file():
            raise SystemExit(f"console entry point not installed: {script}")
        version_output = run([str(script), "--version"], cwd=work, env=environment)
        if version_output.strip() != "0.2.0-experimental":
            raise SystemExit(f"unexpected console version: {version_output!r}")
        print(json.dumps({"passed": True, "wheel": artifacts[0].name,
                          "console": version_output.strip(),
                          "smoke": output.strip()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
