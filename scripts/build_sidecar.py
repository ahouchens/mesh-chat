from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SERVICE = REPOSITORY / "service"
BINARIES = REPOSITORY / "src-tauri" / "binaries"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _build_fingerprint(target: str) -> str:
    """Hash every source/configuration input which affects the sidecar bytes."""
    inputs = [
        REPOSITORY / "scripts" / "build_sidecar.py",
        SERVICE / "entrypoint.py",
        SERVICE / "mesh-chat-service.spec",
        SERVICE / "pyproject.toml",
        SERVICE / "requirements.lock",
        SERVICE / "requirements-dev.lock",
    ]
    inputs.extend(sorted((SERVICE / "src").rglob("*.py")))
    digest = hashlib.sha256()
    digest.update(f"target={target}\0".encode())
    digest.update(f"python={sys.version}\0executable={Path(sys.executable).resolve()}\0".encode())
    try:
        digest.update(f"pyinstaller={importlib.metadata.version('pyinstaller')}\0".encode())
    except importlib.metadata.PackageNotFoundError:
        digest.update(b"pyinstaller=missing\0")
    for path in inputs:
        relative = path.relative_to(REPOSITORY).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _cache_is_current(manifest_path: Path, destination: Path, fingerprint: str) -> bool:
    if not manifest_path.is_file() or not destination.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        manifest.get("schema_version") == 1
        and manifest.get("input_sha256") == fingerprint
        and manifest.get("output_sha256") == _sha256(destination)
    )


def _write_cache_manifest(
    manifest_path: Path,
    *,
    fingerprint: str,
    destination: Path,
) -> None:
    value = {
        "schema_version": 1,
        "input_sha256": fingerprint,
        "output_sha256": _sha256(destination),
        "output": destination.name,
    }
    temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)


def rust_host_triple(*, required: bool = True) -> str | None:
    rustc = os.environ.get("MESH_CHAT_RUSTC") or shutil.which("rustc")
    if rustc is None:
        candidate = Path.home() / ".cargo" / "bin" / ("rustc.exe" if os.name == "nt" else "rustc")
        if candidate.is_file():
            rustc = str(candidate)
    if rustc is None:
        if required:
            raise SystemExit("rustc is required to determine the native Tauri target triple")
        return None
    result = subprocess.run(
        [rustc, "-vV"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    for line in result.stdout.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise SystemExit("rustc did not report a host target triple")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the native Mesh Chat Python sidecar for this host"
    )
    parser.add_argument(
        "--target-triple",
        help="Native Rust target triple (defaults to the rustc host triple)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="discard the verified sidecar cache and perform a clean PyInstaller build",
    )
    args = parser.parse_args()
    host = rust_host_triple(required=args.target_triple is None)
    target = args.target_triple or host
    assert target is not None
    if host is not None and target != host:
        raise SystemExit(
            "PyInstaller cannot cross-compile the sidecar; run this build on the target host"
        )

    extension = ".exe" if sys.platform == "win32" else ""
    BINARIES.mkdir(parents=True, exist_ok=True)
    destination = BINARIES / f"mesh-chat-service-{target}{extension}"
    manifest_path = BINARIES / f".mesh-chat-service-{target}.build.json"
    fingerprint = _build_fingerprint(target)
    if not args.force and _cache_is_current(manifest_path, destination, fingerprint):
        print(f"Reusing verified sidecar: {destination}")
        print(f"SHA256 {_sha256(destination)}")
        return 0

    pyinstaller = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
    ]
    if args.force:
        pyinstaller.append("--clean")
    pyinstaller.append("mesh-chat-service.spec")
    subprocess.run(
        pyinstaller,
        cwd=SERVICE,
        check=True,
    )
    source = SERVICE / "dist" / f"mesh-chat-service{extension}"
    if not source.is_file():
        raise SystemExit(f"Sidecar output is missing: {source}")
    shutil.copy2(source, destination)
    _write_cache_manifest(
        manifest_path,
        fingerprint=fingerprint,
        destination=destination,
    )
    digest = _sha256(destination)
    print(f"{destination}\nSHA256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
