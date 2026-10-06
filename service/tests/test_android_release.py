from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_android_release import AndroidReleaseError, publish_android_release


VERSION = "7.8.9"


def _write_repository(root: Path) -> Path:
    (root / "src-tauri" / "gen" / "android" / "app").mkdir(parents=True)
    (root / "service").mkdir()
    (root / "package.json").write_text(
        json.dumps({"version": VERSION}), encoding="utf-8"
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
    (root / "src-tauri" / "gen" / "android" / "app" / "tauri.properties").write_text(
        f"tauri.android.versionName={VERSION}\ntauri.android.versionCode=7008009\n",
        encoding="utf-8",
    )
    apk = root / "source.apk"
    apk.write_bytes(b"signed-apk-fixture")
    return apk


def test_android_release_is_immutable_and_updates_verified_alias(tmp_path: Path) -> None:
    apk = _write_repository(tmp_path)

    manifest_path = publish_android_release(apk, repository=tmp_path)
    second_manifest = publish_android_release(apk, repository=tmp_path)

    assert second_manifest == manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION
    assert manifest["version_code"] == 7_008_009
    alias = tmp_path / "dist" / "mobile" / f"mesh-chat-{VERSION}-android-arm64-debug.apk"
    assert alias.read_bytes() == apk.read_bytes()
    current = json.loads(
        (tmp_path / "dist" / "mobile" / "current.json").read_text(encoding="utf-8")
    )
    assert current["manifest"] == f"releases/{VERSION}/android-arm64-debug/manifest.json"
    assert not list((tmp_path / "dist" / "mobile").glob(".publish-*"))


def test_same_version_with_different_apk_is_rejected(tmp_path: Path) -> None:
    apk = _write_repository(tmp_path)
    publish_android_release(apk, repository=tmp_path)
    current_path = tmp_path / "dist" / "mobile" / "current.json"
    original_current = current_path.read_bytes()
    apk.write_bytes(b"different-build-with-same-version")

    with pytest.raises(AndroidReleaseError, match="different bytes"):
        publish_android_release(apk, repository=tmp_path)

    assert current_path.read_bytes() == original_current


def test_generated_android_version_must_match_source(tmp_path: Path) -> None:
    apk = _write_repository(tmp_path)
    properties = tmp_path / "src-tauri" / "gen" / "android" / "app" / "tauri.properties"
    properties.write_text(
        "tauri.android.versionName=7.8.8\ntauri.android.versionCode=7008008\n",
        encoding="utf-8",
    )

    with pytest.raises(AndroidReleaseError, match="versionName"):
        publish_android_release(apk, repository=tmp_path)
