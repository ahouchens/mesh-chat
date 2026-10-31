"""Staged release assets must equal the qualified manifest bytes."""

import json
from pathlib import Path

import pytest

from test_release_qualification import VERSION, fixture

import release_qualification
import verify_release_assets as verify


def qualified(tmp_path):
    manifest_path, artifacts, repository = fixture(tmp_path)
    manifest = release_qualification.aggregate(
        qualification_path=manifest_path, artifacts=artifacts, source="a" * 40,
        tree="b" * 40, version=VERSION, repository=repository)
    path = tmp_path / "release-qualification.json"
    path.write_text(json.dumps(manifest))
    assets = tmp_path / "assets"
    assets.mkdir()
    for kind, source in artifacts.items():
        (assets / release_qualification.expected_name(kind, VERSION)).write_bytes(source.read_bytes())
    return path, assets, manifest


def test_matching_assets_pass_and_report_their_digests(tmp_path):
    path, assets, manifest = qualified(tmp_path)
    result = verify.verify(path, assets)
    assert result["passed"] is True and result["release_version"] == VERSION
    assert set(result["artifacts"]) == {"setup", "msi", "apk"}
    for kind, value in result["artifacts"].items():
        assert value == manifest["artifacts"][kind]


def test_a_changed_byte_fails_closed(tmp_path):
    path, assets, _ = qualified(tmp_path)
    target = assets / release_qualification.expected_name("msi", VERSION)
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(ValueError):
        verify.verify(path, assets)


@pytest.mark.parametrize("fault", ["missing", "unpassed", "wrong_version", "incomplete"])
def test_incomplete_or_unpassed_evidence_is_refused(tmp_path, fault):
    path, assets, manifest = qualified(tmp_path)
    if fault == "missing":
        (assets / release_qualification.expected_name("apk", VERSION)).unlink()
    else:
        if fault == "unpassed":
            manifest["passed"] = False
        elif fault == "wrong_version":
            manifest["release_version"] = "9.9.9"
        else:
            manifest["artifacts"].pop("setup")
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify.verify(path, assets)
