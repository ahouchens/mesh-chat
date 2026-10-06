"""Prepare and build the signed iOS application on macOS with Xcode."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, env=os.environ.copy())


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("iOS builds require macOS with a full Xcode installation.")
    if shutil.which("xcodebuild") is None:
        raise SystemExit("Xcode is required; Command Line Tools alone are not sufficient.")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("pnpm 11 is required. Run pnpm install before this script.")

    run([sys.executable, str(ROOT / "scripts" / "prepare_ios_runtime.py")])
    apple_project = ROOT / "src-tauri" / "gen" / "apple" / "project.yml"
    if not apple_project.is_file():
        run([pnpm, "tauri", "ios", "init", "--ci"])
    run([pnpm, "tauri", "ios", "build", "--ci"])

    artifacts = sorted(
        (ROOT / "src-tauri" / "gen" / "apple" / "build").rglob("*.ipa"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not artifacts:
        raise RuntimeError("The iOS build completed without producing an IPA")
    print(f"IPA: {artifacts[0]}")
    print(f"SHA-256: {digest(artifacts[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
