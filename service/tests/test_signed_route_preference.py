from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mesh_chat.reticulum_config import SIGNED_TCP_ROUTE_GRAVITY


def test_later_signed_tcp_announce_replaces_earlier_nearby_route() -> None:
    service_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    python_path = [str(service_root / "src"), str(service_root)]
    if environment.get("PYTHONPATH"):
        python_path.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path)

    result = subprocess.run(
        [
            sys.executable,
            str(service_root / "tools" / "signed_route_preference_probe.py"),
        ],
        cwd=service_root.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    probe = json.loads(result.stdout)
    assert probe == {
        "first_route": "Nearby devices",
        "equal_gravity_route": "Nearby devices",
        "preferred_route": "Private TCP peer 1",
        "signed_tcp_gravity": SIGNED_TCP_ROUTE_GRAVITY,
    }
