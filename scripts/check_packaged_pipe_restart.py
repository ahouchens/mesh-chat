"""Windows-only: the installed-wheel consumer's message survives a host restart.

The host runs from the installed wheel, writes to a stable vault, exits and is
started again with the same vault and a new named pipe. The consumer then queries
the saved opaque handle. This is component evidence, not a GUI or physical run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_packaged_pipe_consumer as packaged  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def server_source() -> str:
    source = packaged.SERVER
    source = source.replace(
        'root = Path(tempfile.mkdtemp(prefix="mesh-chat-pipe-host-"))',
        "root = Path(sys.argv[2])",
    )
    source = source.replace(
        "store = VaultStore(root, os.urandom(32), allow_unprotected_for_tests=True)",
        "store = VaultStore(root, bytes.fromhex(sys.argv[3]), allow_unprotected_for_tests=True)",
    )
    source = source.replace(
        'service.create_profile("Pipe host")',
        'if service.store.get("profile", "local") is None: service.create_profile("Pipe host")',
    )
    source = source.replace(
        'service.create_workspace(str(uuid.uuid4()), "Pipe workspace", "")',
        'if not service.snapshot()["workspaces"]:\n'
        '    service.create_workspace(str(uuid.uuid4()), "Pipe workspace", "")',
    )
    source = source.replace(
        'permissions=("observe", "read")',
        'permissions=("observe", "read", "send")',
    )
    return source


PREFIX = packaged.CONSUMER.split("\nconnection = connect(sys.argv[1])")[0]

FIRST = PREFIX + r"""
connection = connect(sys.argv[1])
try:
    client = CoreClient.open(connection.readline, connection.write)
    profile = client.capabilities["profiles"][0]
    peer = client.profile(profile)["peers"][0]
    accepted = client.enqueue(profile, peer, "Restart-surviving Windows message",
                              "restart-enqueue-key".ljust(16, "x"))
    print(json.dumps({"api_major": client.capabilities["api_major"],
                      "message_handle": accepted["message"]}))
finally:
    connection.close()
"""

RESTORE = PREFIX + r"""
connection = connect(sys.argv[1])
try:
    client = CoreClient.open(connection.readline, connection.write)
    profile = client.capabilities["profiles"][0]
    view = client.message_query(profile, sys.argv[2])
    print(json.dumps({"api_major": client.capabilities["api_major"],
                      "restored_text": view["text"],
                      "state": view["state"]}))
finally:
    connection.close()
"""


def start_host(root: Path, key: str):
    pipe = rf"\\.\pipe\mesh-chat-restart-{uuid.uuid4().hex[:16]}"
    process = subprocess.Popen(
        [sys.executable, "-c", server_source(), pipe, str(root), key],
        text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ready = process.stdout.readline().strip() if process.stdout else ""
    if not ready:
        raise SystemExit(f"restart host did not start: {process.stderr.read() if process.stderr else ''}")
    if not json.loads(ready).get("ready"):
        raise SystemExit(f"unexpected host handshake: {ready}")
    return process, pipe


def stop_host(process) -> None:
    if process.stdin:
        process.stdin.write("\n")
        process.stdin.flush()
        process.stdin.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)


def consume(source: str, pipe: str, *arguments: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", source, pipe, *arguments], text=True,
        capture_output=True, timeout=60,
    )
    if completed.returncode != 0:
        raise SystemExit(f"consumer failed: {completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    if os.name != "nt":
        print(json.dumps({"passed": True, "skipped": "requires Windows named pipes"}))
        return 0
    with tempfile.TemporaryDirectory(prefix="mesh-chat-pipe-restart-") as temporary:
        work = Path(temporary)
        wheel, target = packaged.install_wheel(work)
        os.environ["PYTHONPATH"] = str(target)
        root = work / "vault"
        root.mkdir()
        key = os.urandom(32).hex()
        first, first_pipe = start_host(root, key)
        try:
            accepted = consume(FIRST, first_pipe)
        finally:
            stop_host(first)
        second, second_pipe = start_host(root, key)
        try:
            restored = consume(RESTORE, second_pipe, accepted["message_handle"])
        finally:
            stop_host(second)
        expected = "Restart-surviving Windows message"
        if restored.get("restored_text") != expected:
            raise SystemExit(f"restored message mismatch: {restored}")
        print(json.dumps({
            "passed": True,
            "wheel": wheel.name,
            "scope": "consumer",
            "transport": "windows_named_pipe",
            "host_restart": True,
            "restored_text": restored["restored_text"],
            "state": restored["state"],
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
