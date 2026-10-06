from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_desktop_release import (
    ReleaseValidationError,
    WindowsVersion,
    publish_desktop_release,
    resolve_target_dir,
)


# This is fixture metadata, not the application's current release. Keeping it
# generic means a routine version bump does not require editing packaging tests.
VERSION = "9.8.7"
TARGET = "x86_64-pc-windows-msvc"


def _write_release_tree(root: Path) -> Path:
    (root / "src-tauri" / "binaries").mkdir(parents=True)
    (root / "service").mkdir()
    (root / "THIRD_PARTY_NOTICES.md").write_text(
        "Unicode data license notice\n", encoding="utf-8"
    )
    (root / "package.json").write_text(
        json.dumps({"name": "mesh-chat", "version": VERSION}), encoding="utf-8"
    )
    (root / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": VERSION}), encoding="utf-8"
    )
    (root / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "mesh-chat"\nversion = "{VERSION}"\n', encoding="utf-8"
    )
    (root / "src-tauri" / "Cargo.lock").write_text(
        f'[[package]]\nname = "mesh-chat"\nversion = "{VERSION}"\n', encoding="utf-8"
    )
    (root / "service" / "pyproject.toml").write_text(
        f'[project]\nname = "mesh-chat-service"\nversion = "{VERSION}"\n',
        encoding="utf-8",
    )
    source_sidecar = (
        root / "src-tauri" / "binaries" / f"mesh-chat-service-{TARGET}.exe"
    )
    source_sidecar.write_bytes(b"current-sidecar")

    target = root / "isolated-target"
    release = target / "release"
    (release / "bundle" / "msi").mkdir(parents=True)
    (release / "bundle" / "nsis").mkdir(parents=True)
    (release / "mesh-chat.exe").write_bytes(b"current-app")
    (release / "mesh-chat-service.exe").write_bytes(b"current-sidecar")
    (release / "bundle" / "msi" / f"Mesh Chat_{VERSION}_x64_en-US.msi").write_bytes(
        b"msi"
    )
    (
        release / "bundle" / "nsis" / f"Mesh Chat_{VERSION}_x64-setup.exe"
    ).write_bytes(b"nsis")
    return target


def _current_version(_path: Path) -> WindowsVersion:
    return WindowsVersion(VERSION, VERSION)


def test_relative_cargo_target_dir_resolves_from_rust_project(tmp_path: Path) -> None:
    assert resolve_target_dir(tmp_path, {"CARGO_TARGET_DIR": "../isolated"}) == (
        tmp_path / "isolated"
    ).resolve()


def test_stale_windows_executable_is_rejected_before_publish(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)

    with pytest.raises(ReleaseValidationError, match="FileVersion is 0.2.6"):
        publish_desktop_release(
            repository=tmp_path,
            target_dir=target,
            target_triple=TARGET,
            platform_name="windows",
            version_reader=lambda _path: WindowsVersion("0.2.6", "0.2.6"),
        )

    assert not (tmp_path / "dist" / "desktop").exists()


def test_unsafe_target_triple_is_rejected(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)

    with pytest.raises(ReleaseValidationError, match="unsafe characters"):
        publish_desktop_release(
            repository=tmp_path,
            target_dir=target,
            target_triple="../../outside",
            platform_name="windows",
            version_reader=_current_version,
        )


def test_sidecar_mismatch_is_rejected_before_publish(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)
    (target / "release" / "mesh-chat-service.exe").write_bytes(b"stale-sidecar")

    with pytest.raises(ReleaseValidationError, match="sidecar does not match"):
        publish_desktop_release(
            repository=tmp_path,
            target_dir=target,
            target_triple=TARGET,
            platform_name="windows",
            version_reader=_current_version,
        )

    assert not (tmp_path / "dist" / "desktop").exists()


def test_coherent_release_is_staged_and_current_manifest_is_atomic(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)

    manifest_path = publish_desktop_release(
        repository=tmp_path,
        target_dir=target,
        target_triple=TARGET,
        platform_name="windows",
        version_reader=_current_version,
    )

    release_dir = tmp_path / "dist" / "desktop" / "releases" / VERSION / TARGET
    assert manifest_path == release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION
    assert manifest["target_triple"] == TARGET
    assert {item["role"] for item in manifest["artifacts"]} == {
        "application",
        "sidecar",
        "installer",
        "notice",
    }
    assert (release_dir / "mesh-chat.exe").read_bytes() == b"current-app"
    assert (release_dir / "mesh-chat-service.exe").read_bytes() == b"current-sidecar"
    assert (release_dir / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8") == (
        "Unicode data license notice\n"
    )
    current = json.loads(
        (tmp_path / "dist" / "desktop" / "current.json").read_text(encoding="utf-8")
    )
    assert current["version"] == VERSION
    assert current["manifest"] == f"releases/{VERSION}/{TARGET}/manifest.json"
    assert not list((tmp_path / "dist" / "desktop").glob(".publish-*"))


def test_published_version_is_immutable_and_current_is_not_repointed(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)
    publish_desktop_release(
        repository=tmp_path,
        target_dir=target,
        target_triple=TARGET,
        platform_name="windows",
        version_reader=_current_version,
    )
    current_path = tmp_path / "dist" / "desktop" / "current.json"
    original_current = current_path.read_bytes()
    (target / "release" / "mesh-chat.exe").write_bytes(b"different-app-same-version")

    with pytest.raises(ReleaseValidationError, match="already published with different bytes"):
        publish_desktop_release(
            repository=tmp_path,
            target_dir=target,
            target_triple=TARGET,
            platform_name="windows",
            version_reader=_current_version,
        )

    assert current_path.read_bytes() == original_current
    assert not list((tmp_path / "dist" / "desktop").glob(".publish-*"))


def test_existing_release_artifact_tampering_is_detected(tmp_path: Path) -> None:
    target = _write_release_tree(tmp_path)
    manifest_path = publish_desktop_release(
        repository=tmp_path,
        target_dir=target,
        target_triple=TARGET,
        platform_name="windows",
        version_reader=_current_version,
    )
    (manifest_path.parent / "mesh-chat.exe").write_bytes(b"tampered")

    with pytest.raises(ReleaseValidationError, match="artifact was modified"):
        publish_desktop_release(
            repository=tmp_path,
            target_dir=target,
            target_triple=TARGET,
            platform_name="windows",
            version_reader=_current_version,
        )
