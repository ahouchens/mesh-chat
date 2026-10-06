from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, verify, and immutably publish a desktop release"
    )
    parser.add_argument(
        "--force-sidecar",
        action="store_true",
        help="discard the verified PyInstaller sidecar cache",
    )
    args = parser.parse_args()
    sidecar_command = [
        sys.executable,
        str(REPOSITORY / "scripts" / "build_sidecar.py"),
    ]
    if args.force_sidecar:
        sidecar_command.append("--force")
    subprocess.run(
        sidecar_command,
        cwd=REPOSITORY,
        check=True,
    )
    pnpm = os.environ.get("MESH_CHAT_PNPM") or shutil.which("pnpm") or shutil.which("pnpm.cmd")
    if pnpm is None:
        raise SystemExit("pnpm is required to build the Tauri desktop package")
    environment = os.environ.copy()
    tool_directories: list[str] = []
    if node := environment.get("MESH_CHAT_NODE"):
        tool_directories.append(str(Path(node).resolve().parent))
    if rustc := environment.get("MESH_CHAT_RUSTC"):
        # Cargo and rustc normally live together. Keeping this behind the
        # Mesh Chat-specific override lets release builds use an explicit
        # toolchain without relying on or permanently changing the user PATH.
        tool_directories.append(str(Path(rustc).resolve().parent))
    if tool_directories:
        environment["PATH"] = os.pathsep.join(
            [*tool_directories, environment["PATH"]]
        )
    pnpm_command = [pnpm]
    if os.name == "nt" and Path(pnpm).suffix.lower() in {".bat", ".cmd"}:
        pnpm_command = [
            environment.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            pnpm,
        ]
    subprocess.run(
        [*pnpm_command, "tauri", "build", "--ci"],
        cwd=REPOSITORY,
        check=True,
        env=environment,
    )
    # Publishing is deliberately a separate, mandatory phase. It inspects the
    # actual Cargo target selected for this build and stages the executable,
    # sidecar, and installers as one immutable release set. This prevents an
    # isolated build from leaving an older executable beside newer installers.
    subprocess.run(
        [sys.executable, str(REPOSITORY / "scripts" / "publish_desktop_release.py")],
        cwd=REPOSITORY,
        check=True,
        env=environment,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
