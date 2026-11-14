"""Synthetic SDK boundary checks for the installed Windows image fixture.

These tests exercise fail-closed probe classification, not Windows admission.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "examples/typescript-independent-consumer/image-admission-check.mjs"
NODE = shutil.which("node")
PIPE = r"\\.\pipe\mesh-chat-image-test"


@pytest.fixture
def synthetic_probe(tmp_path):
    if NODE is None:
        pytest.skip("Node is required for the fixture classifier")
    work = tmp_path / "application"
    work.mkdir()
    shutil.copyfile(SOURCE, work / SOURCE.name)
    package = work / "node_modules/@mesh-chat/core-client"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "name": "@mesh-chat/core-client", "version": "0.3.0-experimental", "type": "module",
        "exports": {".": "./index.mjs", "./node": "./node.mjs"},
    }), encoding="utf-8")
    (package / "index.mjs").write_text("""
export class TransportClosedError extends Error {}
export class CoreClient {
  static async open(transport) {
    if (process.env.IMAGE_CASE === 'closed' || process.env.IMAGE_CASE === 'bytes') {
      throw new TransportClosedError();
    }
    if (process.env.IMAGE_CASE === 'timeout') throw new Error('timeout');
    return {capabilities:{profiles:['local'],operations:['profile.query']},
      request:async()=>({destination:'fixture'}),close(){}};
  }
}
""", encoding="utf-8")
    (package / "node.mjs").write_text("""
export async function connectNamedPipe() {
  if (process.env.IMAGE_CASE === 'unreachable') throw new Error('unreachable');
  return {socket:{bytesRead:process.env.IMAGE_CASE === 'bytes' ? 1 : 0},close(){}};
}
""", encoding="utf-8")
    image = subprocess.check_output([NODE, "-p", "process.execPath"], text=True).strip()
    return work, image


@pytest.mark.parametrize("mode,case,passed,detail", [
    ("preflight", "closed", True, "ready"),
    ("allow", "positive", True, "negotiated"),
    ("deny", "closed", True, "closed_before_core_reply"),
    ("deny", "unreachable", False, None),
    ("deny", "timeout", False, None),
    ("deny", "bytes", False, None),
    ("deny", "positive", False, None),
])
def test_probe_requires_connected_zero_reply_closure(synthetic_probe, mode, case, passed, detail):
    work, image = synthetic_probe
    env = {**os.environ, "IMAGE_CASE": case}
    completed = subprocess.run([NODE, SOURCE.name, "--probe", mode, PIPE, image],
                               cwd=work, env=env, capture_output=True, text=True, timeout=10)
    assert completed.stderr == ""
    value = json.loads(completed.stdout)
    if passed:
        assert completed.returncode == 0
        assert value[detail] is True
        assert "passed" not in value
    else:
        assert completed.returncode == 1
        assert value == {"v": 1, "mode": mode, "passed": False}


def test_probe_rejects_wrong_executable_identity(synthetic_probe):
    work, image = synthetic_probe
    completed = subprocess.run([NODE, SOURCE.name, "--probe", "deny", PIPE, image + ".other"],
                               cwd=work, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {"v": 1, "mode": "deny", "passed": False}
