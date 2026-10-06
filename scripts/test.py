from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=REPOSITORY, check=True)


def current_node() -> str:
    candidates = [os.environ.get("MESH_CHAT_NODE"), shutil.which("node")]
    candidates.append(
        str(
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / ("node.exe" if os.name == "nt" else "node")
        )
    )
    for node in candidates:
        if not node or not Path(node).is_file():
            continue
        try:
            major = int(
                subprocess.run(
                    [node, "--version"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout.lstrip("v").split(".", 1)[0]
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if major >= 20:
            return node
    raise SystemExit("Node.js 20 or newer is required")


def main() -> int:
    node = current_node()

    # Use an OS-managed unique directory so a prior run under a different
    # Windows sandbox identity cannot leave an ACL that blocks later runs.
    with tempfile.TemporaryDirectory(prefix="mesh-chat-pytest-") as pytest_temp:
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "service/tests",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                pytest_temp,
            ]
        )
    run([node, "scripts/run-frontend-tests.mjs"])
    run([node, "--test", "scripts/verify_packaged_emoji_artwork.test.mjs"])
    run([node, "node_modules/typescript/bin/tsc", "-b"])
    run([node, "scripts/run-frontend-build.mjs"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
