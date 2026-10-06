from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_version import (
    VersionError,
    android_version_code,
    check_versions,
    set_version,
    validate_version,
)


def _write_version_tree(root: Path, version: str = "1.2.3") -> None:
    (root / "src-tauri").mkdir(parents=True)
    (root / "service").mkdir()
    (root / "package.json").write_text(
        json.dumps({"name": "mesh-chat", "version": version}), encoding="utf-8"
    )
    (root / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": version, "plugins": {"example": {"version": "keep"}}}),
        encoding="utf-8",
    )
    (root / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "mesh-chat"\nversion = "{version}"\n\n'
        '[dependencies]\nserde = "1"\n',
        encoding="utf-8",
    )
    (root / "src-tauri" / "Cargo.lock").write_text(
        'version = 3\n\n[[package]]\nname = "dependency"\nversion = "7.7.7"\n'
        'source = "registry+example"\n\n[[package]]\nname = "mesh-chat"\n'
        f'version = "{version}"\ndependencies = ["dependency"]\n',
        encoding="utf-8",
    )
    (root / "service" / "pyproject.toml").write_text(
        f'[project]\nname = "mesh-chat-service"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def test_android_version_code_is_derived_from_semver() -> None:
    assert android_version_code("2.34.567") == 2_034_567


@pytest.mark.parametrize("value", ["v1.2.3", "1.2", "1.2.3-beta.1", "01.2.3", "1.1000.0"])
def test_invalid_release_versions_are_rejected(value: str) -> None:
    with pytest.raises(VersionError):
        validate_version(value)


def test_check_reports_inconsistent_metadata(tmp_path: Path) -> None:
    _write_version_tree(tmp_path)
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    package["version"] = "1.2.4"
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")

    with pytest.raises(VersionError, match="does not match package.json 1.2.4"):
        check_versions(tmp_path)


def test_set_version_synchronizes_only_application_metadata(tmp_path: Path) -> None:
    _write_version_tree(tmp_path)

    state = set_version("4.5.6", tmp_path)

    assert state.version == "4.5.6"
    assert state.android_version_code == 4_005_006
    assert set(state.configured.values()) == {"4.5.6"}
    lock = (tmp_path / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    assert 'name = "dependency"\nversion = "7.7.7"' in lock
    tauri = json.loads(
        (tmp_path / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert tauri["plugins"]["example"]["version"] == "keep"


def test_expected_version_accepts_tag_prefix(tmp_path: Path) -> None:
    _write_version_tree(tmp_path, "3.2.1")

    assert check_versions(tmp_path, expected="v3.2.1").version == "3.2.1"
