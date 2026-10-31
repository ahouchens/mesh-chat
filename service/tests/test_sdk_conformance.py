"""Cross-language conformance: compiled TypeScript client against the real facade.

This test lives outside the required policy inventory because it needs a modern
Node runtime; general verification builds the client and runs it.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest


# The connection suite owns the one real-service fixture; reuse it rather than
# maintaining a second copy. Its module is importable once its directory is on
# the path, which pytest already does for tests inside it.
_CONNECTION = Path(__file__).resolve().parent / "connection"
if str(_CONNECTION) not in sys.path:
    sys.path.insert(0, str(_CONNECTION))
from test_core_messages import host  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "sdk" / "typescript" / "conformance.mjs"
CANDIDATES = (
    os.environ.get("MESH_NODE"),
    r"C:\Users\webte\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe",
)


def modern_node():
    for candidate in (*CANDIDATES, "node"):
        if not candidate:
            continue
        try:
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        version = result.stdout.strip().lstrip("v")
        if result.returncode == 0 and version.split(".")[0].isdigit() and int(version.split(".")[0]) >= 20:
            return candidate
    return None


@pytest.mark.skipif(modern_node() is None, reason="A Node 20+ runtime is required")
def test_typescript_client_conforms_over_inherited_stdio(host):
    from mesh_chat.core_api.composition import bind_service_stream
    from mesh_chat.core_api.session import Grant

    # The child owns stdout as its request channel and stdin as the response
    # channel; the host serves the opposite ends. None of these are listening
    # sockets, so only the spawned child can reach the session.
    requests_read, requests_write = os.pipe()
    responses_read, responses_write = os.pipe()
    service = host()
    grants = [Grant("alex", frozenset({"observe", "read", "send"}), ("local",))]
    session = bind_service_stream(service, lambda: grants[0])

    def serve():
        with os.fdopen(requests_read, "rb", buffering=0) as reader:
            with os.fdopen(responses_write, "wb", buffering=0) as writer:
                session.serve(reader, writer)

    thread = threading.Thread(target=serve, name="core-api-conformance-host", daemon=True)
    thread.start()
    with os.fdopen(responses_read, "rb", buffering=0) as stdin:
        with os.fdopen(requests_write, "wb", buffering=0) as stdout:
            result = subprocess.run(
                [modern_node(), str(SCRIPT)], stdin=stdin, stdout=stdout,
                stderr=subprocess.PIPE, timeout=120, cwd=ROOT / "sdk" / "typescript")
    thread.join(5)
    assert not thread.is_alive()
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-2000:]
    payload = json.loads(result.stderr.decode("utf-8").splitlines()[-1])
    assert payload["ok"] is True, payload
    assert payload["api_major"] == 1
    assert payload["operations"] >= 10
    assert payload["peers"] == 1
    assert payload["messages"] == 0
    assert payload["events"] == 0
