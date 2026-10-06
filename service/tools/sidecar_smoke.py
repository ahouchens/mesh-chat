from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from mesh_chat.invitations import verify_invitation
from mesh_chat.ipc import encode_frame, read_frame


def response(stream: BinaryIO, request_id: str) -> dict[str, Any]:
    while True:
        frame = read_frame(stream)
        if frame.get("type") == "response" and frame.get("id") == request_id:
            return frame


def send(process: subprocess.Popen[bytes], value: dict[str, Any]) -> dict[str, Any]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(encode_frame(value))
    process.stdin.flush()
    return response(process.stdout, value["id"])


def native_sidecar() -> Path:
    binary_root = Path(__file__).resolve().parents[2] / "src-tauri" / "binaries"
    extension = ".exe" if sys.platform == "win32" else ""
    candidates = list(binary_root.glob(f"mesh-chat-service-*{extension}"))
    if len(candidates) == 1:
        return candidates[0]
    rustc = shutil.which("rustc")
    if rustc is None:
        raise RuntimeError("Pass the native sidecar path or make rustc available")
    version = subprocess.run(
        [rustc, "-vV"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        timeout=15,
    ).stdout
    host = next(line.removeprefix("host: ") for line in version.splitlines() if line.startswith("host: "))
    return binary_root / f"mesh-chat-service-{host}{extension}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "binary",
        nargs="?",
        type=Path,
    )
    args = parser.parse_args()
    binary = args.binary or native_sidecar()
    with tempfile.TemporaryDirectory(prefix="mesh-chat-sidecar-") as temporary:
        profile = Path(temporary) / "profile"
        process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            initialized = send(
                process,
                {
                    "v": 1,
                    "id": "initialize-smoke",
                    "command": "initialize",
                    "payload": {
                        "profile_dir": str(profile),
                        "vault_key": base64.b64encode(os.urandom(32)).decode("ascii"),
                        "display_name": "Packaging Test",
                        "parent_pid": os.getpid(),
                    },
                },
            )
            if initialized.get("ok") is not True:
                raise RuntimeError(
                    "Packaged sidecar initialization failed: "
                    f"{initialized.get('error', {}).get('code', 'unknown_error')}"
                )
            invitation = send(
                process,
                {
                    "v": 1,
                    "id": "invitation-smoke",
                    "command": "create_invitation",
                    "payload": {},
                },
            )
            stopped = send(
                process,
                {
                    "v": 1,
                    "id": "shutdown-smoke",
                    "command": "shutdown",
                    "payload": {},
                },
            )
            process.wait(timeout=20)
        except Exception as exc:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            stderr = process.stderr.read() if process.stderr else b""
            detail = stderr.decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(
                f"Packaged sidecar exited during smoke test "
                f"(code {process.returncode}): {detail}"
            ) from exc
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        invitation_text = invitation.get("result", {}).get("file", "")
        verified_invitation = verify_invitation(invitation_text)
        result = {
            "initialized": initialized.get("ok") is True,
            "profile_created": initialized.get("result", {}).get("profile") is not None,
            "invitation_created": invitation.get("ok") is True
            and invitation.get("result", {}).get("link", "").startswith("meshchat://invite/"),
            "direct_lan_hint_created": bool(verified_invitation.hints),
            "graceful_shutdown": stopped.get("ok") is True and process.returncode == 0,
            "stderr_redacted": b"Packaging Test" not in (process.stderr.read() if process.stderr else b""),
        }
        print(json.dumps(result, indent=2))
        return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
