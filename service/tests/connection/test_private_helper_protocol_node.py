"""Run the private owner/helper Node subprocess protocol in connection evidence."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/typescript-independent-consumer/private-helper-protocol.test.mjs"


def node_runtime():
    selected = (os.environ.get("MESH_CHAT_TEST_NODE") or os.environ.get("MESH_CHAT_NODE")
                or os.environ.get("MESH_NODE") or shutil.which("node"))
    if not selected or not Path(selected).is_file():
        pytest.skip("Node >=22 runtime unavailable")
    version = subprocess.run([selected, "--version"], capture_output=True, text=True, timeout=5)
    if version.returncode != 0 or not re.fullmatch(r"v\d+\.\d+\.\d+\s*", version.stdout):
        pytest.skip("Node >=22 runtime unavailable")
    if int(version.stdout.removeprefix("v").split(".")[0]) < 22:
        pytest.skip("Node >=22 runtime unavailable")
    return selected


def test_private_owner_helper_subprocess_protocol():
    completed = subprocess.run([node_runtime(), "--test", "--test-reporter=tap", str(SCRIPT)],
                               cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = dict(re.findall(r"^# (tests|pass|fail|skipped) (\d+)$", completed.stdout, re.MULTILINE))
    assert summary == {"tests": "13", "pass": "13", "fail": "0", "skipped": "0"}
