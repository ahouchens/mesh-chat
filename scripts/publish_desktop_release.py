from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1


class ReleaseValidationError(RuntimeError):
    """The build output is not one coherent, publishable desktop release."""


@dataclass(frozen=True)
class WindowsVersion:
    file_version: str
    product_version: str


@dataclass(frozen=True)
class ReleaseSource:
    source: Path
    destination: Path
    role: str
    metadata: Mapping[str, str]


VersionReader = Callable[[Path], WindowsVersion]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_atomic(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(contents)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _configured_versions(repository: Path) -> dict[str, str]:
    package = json.loads((repository / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads(
        (repository / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    cargo = tomllib.loads(
        (repository / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    )
    service = tomllib.loads(
        (repository / "service" / "pyproject.toml").read_text(encoding="utf-8")
    )
    versions = {
        "package.json": str(package["version"]),
        "src-tauri/tauri.conf.json": str(tauri["version"]),
        "src-tauri/Cargo.toml": str(cargo["package"]["version"]),
        "service/pyproject.toml": str(service["project"]["version"]),
    }
    cargo_lock_path = repository / "src-tauri" / "Cargo.lock"
    if cargo_lock_path.is_file():
        cargo_lock = tomllib.loads(cargo_lock_path.read_text(encoding="utf-8"))
        root_packages = [
            item
            for item in cargo_lock.get("package", [])
            if isinstance(item, dict) and item.get("name") == "mesh-chat"
        ]
        if len(root_packages) != 1:
            raise ReleaseValidationError(
                "src-tauri/Cargo.lock must contain exactly one mesh-chat package"
            )
        versions["src-tauri/Cargo.lock"] = str(root_packages[0]["version"])
    return versions


def expected_version(repository: Path = REPOSITORY) -> str:
    versions = _configured_versions(repository)
    expected = versions["package.json"]
    mismatches = {path: version for path, version in versions.items() if version != expected}
    if mismatches:
        details = ", ".join(f"{path}={version}" for path, version in mismatches.items())
        raise ReleaseValidationError(
            f"Desktop release version metadata is inconsistent with {expected}: {details}"
        )
    return expected


def resolve_target_dir(
    repository: Path = REPOSITORY,
    environment: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if environment is None else environment
    configured = values.get("CARGO_TARGET_DIR")
    if not configured:
        return (repository / "src-tauri" / "target").resolve()
    path = Path(configured)
    if path.is_absolute():
        return path.resolve()
    # Tauri invokes Cargo from the Rust project directory. Resolve a relative
    # CARGO_TARGET_DIR the same way instead of silently inspecting the default
    # target directory after an isolated build.
    return (repository / "src-tauri" / path).resolve()


def _host_target_triple(repository: Path) -> str:
    rustc = os.environ.get("MESH_CHAT_RUSTC") or shutil.which("rustc")
    if rustc is None:
        raise ReleaseValidationError("rustc is required to determine the desktop target triple")
    result = subprocess.run(
        [rustc, "-vV"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    for line in result.stdout.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise ReleaseValidationError("rustc did not report a host target triple")


def _platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise ReleaseValidationError(f"Unsupported desktop build platform: {sys.platform}")


def _canonical_version(value: str) -> str:
    match = re.search(r"\d+\.\d+\.\d+(?:\.\d+)?", value.replace(",", "."))
    if match is None:
        return value.strip()
    parts = match.group(0).split(".")
    while len(parts) > 3 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _read_windows_version(executable: Path) -> WindowsVersion:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        system_root = os.environ.get("SystemRoot")
        if system_root:
            candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            if candidate.is_file():
                powershell = str(candidate)
    if powershell is None:
        raise ReleaseValidationError("PowerShell is required to inspect Windows executable versions")
    environment = os.environ.copy()
    environment["MESH_CHAT_RELEASE_EXE"] = str(executable)
    command = (
        "$v=(Get-Item -LiteralPath $env:MESH_CHAT_RELEASE_EXE).VersionInfo;"
        "@{file_version=$v.FileVersion;product_version=$v.ProductVersion}"
        "|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        env=environment,
    )
    try:
        value = json.loads(result.stdout)
        return WindowsVersion(str(value["file_version"]), str(value["product_version"]))
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(
            "PowerShell did not return Windows executable version metadata"
        ) from exc


def _windows_bundle_files(bundle_dir: Path, version: str) -> list[tuple[Path, Path]]:
    matching_msi = sorted(
        path for path in bundle_dir.rglob("*.msi") if version in path.name
    )
    matching_nsis = sorted(
        path
        for path in bundle_dir.rglob("*.exe")
        if version in path.name and "setup" in path.name.casefold()
    )
    if len(matching_msi) != 1 or len(matching_nsis) != 1:
        raise ReleaseValidationError(
            "The Windows stage must contain exactly one version-matched MSI and NSIS installer"
        )
    return [(path, Path("bundle") / path.relative_to(bundle_dir)) for path in [*matching_msi, *matching_nsis]]


def _other_bundle_files(bundle_dir: Path) -> list[tuple[Path, Path]]:
    files = sorted(path for path in bundle_dir.rglob("*") if path.is_file())
    if not files:
        raise ReleaseValidationError("The desktop stage does not contain any bundle artifacts")
    return [(path, Path("bundle") / path.relative_to(bundle_dir)) for path in files]


def _release_sources(
    repository: Path,
    target_dir: Path,
    target_triple: str,
    platform_name: str,
    version: str,
    version_reader: VersionReader,
) -> list[ReleaseSource]:
    extension = ".exe" if platform_name == "windows" else ""
    executable = target_dir / "release" / f"mesh-chat{extension}"
    staged_sidecar = target_dir / "release" / f"mesh-chat-service{extension}"
    source_sidecar = (
        repository
        / "src-tauri"
        / "binaries"
        / f"mesh-chat-service-{target_triple}{extension}"
    )
    bundle_dir = target_dir / "release" / "bundle"
    third_party_notices = repository / "THIRD_PARTY_NOTICES.md"
    required = [
        executable,
        staged_sidecar,
        source_sidecar,
        bundle_dir,
        third_party_notices,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ReleaseValidationError(f"Desktop release output is incomplete: {', '.join(missing)}")

    application_metadata: dict[str, str] = {}
    if platform_name == "windows":
        windows_version = version_reader(executable)
        application_metadata = {
            "file_version": windows_version.file_version,
            "product_version": windows_version.product_version,
        }
        if _canonical_version(windows_version.file_version) != version:
            raise ReleaseValidationError(
                f"Staged executable FileVersion is {windows_version.file_version}, expected {version}"
            )
        if _canonical_version(windows_version.product_version) != version:
            raise ReleaseValidationError(
                f"Staged executable ProductVersion is {windows_version.product_version}, expected {version}"
            )

    expected_sidecar_hash = _sha256(source_sidecar)
    staged_sidecar_hash = _sha256(staged_sidecar)
    if staged_sidecar_hash != expected_sidecar_hash:
        raise ReleaseValidationError(
            "The staged desktop sidecar does not match the freshly built external binary"
        )

    bundle_files = (
        _windows_bundle_files(bundle_dir, version)
        if platform_name == "windows"
        else _other_bundle_files(bundle_dir)
    )
    sources = [
        ReleaseSource(executable, Path(executable.name), "application", application_metadata),
        ReleaseSource(
            staged_sidecar,
            Path(staged_sidecar.name),
            "sidecar",
            {"source_sha256": expected_sidecar_hash},
        ),
        ReleaseSource(
            third_party_notices,
            Path(third_party_notices.name),
            "notice",
            {},
        ),
    ]
    sources.extend(
        ReleaseSource(source, destination, "installer", {})
        for source, destination in bundle_files
    )
    return sources


def _manifest(
    *,
    version: str,
    platform_name: str,
    target_triple: str,
    release_directory: Path,
    sources: list[ReleaseSource],
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for item in sources:
        artifact: dict[str, Any] = {
            "path": item.destination.as_posix(),
            "role": item.role,
            "sha256": _sha256(item.source),
            "size": item.source.stat().st_size,
        }
        artifact.update(item.metadata)
        artifacts.append(artifact)
    artifacts.sort(key=lambda item: item["path"])
    return {
        "schema_version": SCHEMA_VERSION,
        "product": "Mesh Chat",
        "version": version,
        "platform": platform_name,
        "target_triple": target_triple,
        "release_directory": release_directory.as_posix(),
        "artifacts": artifacts,
    }


def _verify_published_directory(release_dir: Path, manifest: Mapping[str, Any]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReleaseValidationError("Published release manifest has no artifact list")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise ReleaseValidationError("Published release manifest contains an invalid artifact")
        relative = Path(artifact["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ReleaseValidationError("Published release manifest contains an unsafe path")
        path = release_dir / relative
        if not path.is_file():
            raise ReleaseValidationError(f"Published release artifact is missing: {relative}")
        if path.stat().st_size != artifact.get("size") or _sha256(path) != artifact.get("sha256"):
            raise ReleaseValidationError(f"Published release artifact was modified: {relative}")


def publish_desktop_release(
    *,
    repository: Path = REPOSITORY,
    target_dir: Path | None = None,
    target_triple: str | None = None,
    platform_name: str | None = None,
    version_reader: VersionReader | None = None,
) -> Path:
    repository = repository.resolve()
    target_dir = (target_dir or resolve_target_dir(repository)).resolve()
    target_triple = target_triple or _host_target_triple(repository)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", target_triple) is None:
        raise ReleaseValidationError("Desktop target triple contains unsafe characters")
    platform_name = platform_name or _platform_name()
    version_reader = version_reader or _read_windows_version
    version = expected_version(repository)

    sources = _release_sources(
        repository,
        target_dir,
        target_triple,
        platform_name,
        version,
        version_reader,
    )
    desktop_root = repository / "dist" / "desktop"
    relative_release = Path("releases") / version / target_triple
    release_dir = desktop_root / relative_release
    manifest = _manifest(
        version=version,
        platform_name=platform_name,
        target_triple=target_triple,
        release_directory=relative_release,
        sources=sources,
    )
    manifest_bytes = _json_bytes(manifest)

    temporary = desktop_root / f".publish-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for item in sources:
            destination = temporary / item.destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, destination)
            if _sha256(destination) != _sha256(item.source):
                raise ReleaseValidationError(
                    f"Copied release artifact failed verification: {item.destination}"
                )
        (temporary / "manifest.json").write_bytes(manifest_bytes)

        if release_dir.exists():
            existing_manifest = release_dir / "manifest.json"
            if not existing_manifest.is_file() or existing_manifest.read_bytes() != manifest_bytes:
                raise ReleaseValidationError(
                    f"Release {version} for {target_triple} is already published with different bytes; bump the version"
                )
            _verify_published_directory(release_dir, manifest)
            shutil.rmtree(temporary)
        else:
            release_dir.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(release_dir)

        current = {
            "schema_version": SCHEMA_VERSION,
            "version": version,
            "platform": platform_name,
            "target_triple": target_triple,
            "manifest": (relative_release / "manifest.json").as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest().upper(),
        }
        _write_atomic(desktop_root / "current.json", _json_bytes(current))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return release_dir / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and publish one coherent Mesh Chat desktop release set"
    )
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--target-triple")
    args = parser.parse_args()
    try:
        manifest = publish_desktop_release(
            target_dir=args.target_dir,
            target_triple=args.target_triple,
        )
    except (OSError, KeyError, ValueError, subprocess.SubprocessError, ReleaseValidationError) as exc:
        print(f"desktop release verification failed: {exc}", file=sys.stderr)
        return 1
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
