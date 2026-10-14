from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_android import stage_native_library
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


def test_release_aab_is_immutable_and_declares_external_signing(tmp_path: Path) -> None:
    aab = _write_repository(tmp_path).with_suffix(".aab")
    aab.write_bytes(b"externally-signed-aab-fixture")

    manifest_path = publish_android_release(
        aab,
        repository=tmp_path,
        variant="release",
        artifact_format="aab",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["signing"] == "release"
    assert manifest["artifacts"][0]["role"] == "android-release-aab"
    assert manifest_path.parent.name == "android-arm64-release-aab"
    alias = tmp_path / "dist" / "mobile" / f"mesh-chat-{VERSION}-android-arm64-release.aab"
    assert alias.read_bytes() == b"externally-signed-aab-fixture"


def test_checked_in_release_configuration_requires_external_secrets() -> None:
    root = Path(__file__).resolve().parents[2]
    gradle = (root / "src-tauri" / "gen" / "android" / "app" / "build.gradle.kts").read_text(
        encoding="utf-8"
    )
    builder = (root / "scripts" / "build_android.py").read_text(encoding="utf-8")

    for variable in (
        "MESH_CHAT_ANDROID_KEYSTORE_PATH",
        "MESH_CHAT_ANDROID_KEYSTORE_PASSWORD",
        "MESH_CHAT_ANDROID_KEY_ALIAS",
        "MESH_CHAT_ANDROID_KEY_PASSWORD",
    ):
        assert variable in gradle
    assert "release signing is not configured" in gradle
    assert "validateReleaseSigning" in gradle
    assert "dependsOn(validateReleaseSigning)" in gradle
    assert 'signingConfig = signingConfigs.getByName("meshChatRelease")' in gradle
    assert '"--aab"' in builder
    assert "publish_android_release" in builder
    assert not list(root.glob("**/*.jks"))
    assert not list(root.glob("**/*.keystore"))


def test_android_build_template_preserves_the_native_theme_bootstrap() -> None:
    root = Path(__file__).resolve().parents[2]
    builder = (root / "scripts" / "build_android.py").read_text(encoding="utf-8")
    activity = (
        root
        / "src-tauri"
        / "gen"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "MainActivity.kt"
    ).read_text(encoding="utf-8")

    for snippet in (
        'private const val THEME_PREFERENCES = "mesh-chat-vault"',
        'private const val UI_THEME = "ui-theme"',
        'getString(UI_THEME, "dark")',
        "R.style.Theme_mesh_chat_Light",
        "applyStoredTheme()",
    ):
        assert snippet in builder
        assert snippet in activity


def test_android_gradle_launcher_uses_the_portable_pnpm_command() -> None:
    root = Path(__file__).resolve().parents[2]
    builder = (root / "scripts" / "build_android.py").read_text(encoding="utf-8")
    build_task = (
        root
        / "src-tauri"
        / "gen"
        / "android"
        / "buildSrc"
        / "src"
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "kotlin"
        / "BuildTask.kt"
    ).read_text(encoding="utf-8")

    launcher = 'System.getenv("MESH_CHAT_PNPM") ?: "pnpm"'
    assert launcher in builder
    assert launcher in build_task
    assert 'System.getenv("MESH_CHAT_NODE") ?: "node"' not in build_task


def test_android_native_staging_accepts_an_existing_link(tmp_path: Path) -> None:
    native_library = tmp_path / "target" / "libmesh_chat_lib.so"
    destination = tmp_path / "jniLibs" / "arm64-v8a"
    native_library.parent.mkdir()
    destination.mkdir(parents=True)
    native_library.write_bytes(b"native-library")
    staged = destination / native_library.name
    try:
        staged.hardlink_to(native_library)
    except OSError as exc:
        pytest.skip(f"hard links are unavailable: {exc}")

    assert stage_native_library(native_library, destination) == staged
    assert staged.samefile(native_library)
