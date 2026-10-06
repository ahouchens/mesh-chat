from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

try:
    from .release_version import REPOSITORY, VersionError, check_versions
except ImportError:  # Direct execution from the scripts directory on sys.path.
    from release_version import REPOSITORY, VersionError, check_versions


SCHEMA_VERSION = 1


class AndroidReleaseError(RuntimeError):
    """The APK is not one coherent, immutable Android release."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(contents)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_release(release_dir: Path, manifest: dict[str, Any]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise AndroidReleaseError("Android manifest must contain exactly one APK")
    artifact = artifacts[0]
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise AndroidReleaseError("Android manifest contains an invalid artifact")
    relative = Path(artifact["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise AndroidReleaseError("Android manifest contains an unsafe path")
    apk = release_dir / relative
    if (
        not apk.is_file()
        or apk.stat().st_size != artifact.get("size")
        or _sha256(apk) != artifact.get("sha256")
    ):
        raise AndroidReleaseError("published Android APK was modified")


def publish_android_release(
    apk: Path,
    *,
    repository: Path = REPOSITORY,
) -> Path:
    repository = repository.resolve()
    apk = apk.resolve()
    if not apk.is_file():
        raise AndroidReleaseError(f"Android APK is missing: {apk}")
    try:
        state = check_versions(repository)
    except VersionError as exc:
        raise AndroidReleaseError(str(exc)) from exc
    generated_properties = (
        repository / "src-tauri" / "gen" / "android" / "app" / "tauri.properties"
    )
    try:
        properties = generated_properties.read_text(encoding="utf-8")
    except OSError as exc:
        raise AndroidReleaseError(f"generated Android metadata is missing: {exc}") from exc
    if f"tauri.android.versionName={state.version}" not in properties:
        raise AndroidReleaseError("generated Android versionName does not match source metadata")
    if f"tauri.android.versionCode={state.android_version_code}" not in properties:
        raise AndroidReleaseError("generated Android versionCode does not match source metadata")

    filename = f"mesh-chat-{state.version}-android-arm64-debug.apk"
    mobile_root = repository / "dist" / "mobile"
    relative_release = Path("releases") / state.version / "android-arm64-debug"
    release_dir = mobile_root / relative_release
    apk_digest = _sha256(apk)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product": "Mesh Chat",
        "version": state.version,
        "version_code": state.android_version_code,
        "platform": "android",
        "architecture": "arm64-v8a",
        "signing": "debug",
        "release_directory": relative_release.as_posix(),
        "artifacts": [
            {
                "path": filename,
                "role": "android-debug-apk",
                "sha256": apk_digest,
                "size": apk.stat().st_size,
            }
        ],
    }
    manifest_bytes = _json_bytes(manifest)
    temporary = mobile_root / f".publish-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        destination = temporary / filename
        shutil.copy2(apk, destination)
        if _sha256(destination) != apk_digest:
            raise AndroidReleaseError("copied Android APK failed verification")
        (temporary / f"{filename}.sha256").write_text(
            f"{apk_digest.lower()}  {filename}\n", encoding="ascii", newline="\n"
        )
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        if release_dir.exists():
            existing_manifest = release_dir / "manifest.json"
            if not existing_manifest.is_file() or existing_manifest.read_bytes() != manifest_bytes:
                raise AndroidReleaseError(
                    f"Android release {state.version} already exists with different bytes; bump the version"
                )
            _verify_release(release_dir, manifest)
            shutil.rmtree(temporary)
        else:
            release_dir.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(release_dir)

        # Preserve the documented convenience path as a verified alias of the
        # immutable release; it is never the source of truth.
        alias = mobile_root / filename
        alias_checksum = alias.with_suffix(alias.suffix + ".sha256")
        alias_temporary = alias.with_name(f".{alias.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(release_dir / filename, alias_temporary)
        os.replace(alias_temporary, alias)
        _atomic_write(
            alias_checksum,
            f"{apk_digest.lower()}  {filename}\n".encode("ascii"),
        )
        current = {
            "schema_version": SCHEMA_VERSION,
            "version": state.version,
            "version_code": state.android_version_code,
            "platform": "android",
            "architecture": "arm64-v8a",
            "manifest": (relative_release / "manifest.json").as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest().upper(),
        }
        _atomic_write(mobile_root / "current.json", _json_bytes(current))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return release_dir / "manifest.json"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Immutably publish a verified Android APK")
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    try:
        manifest = publish_android_release(args.apk)
    except (OSError, ValueError, AndroidReleaseError) as exc:
        print(f"Android release verification failed: {exc}", file=sys.stderr)
        return 1
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
