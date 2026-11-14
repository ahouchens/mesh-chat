"""Offline published-release intake controls; synthetic bytes do not qualify a release."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "stage_core_release_baseline", ROOT / "scripts/stage_core_release_baseline.py"
)
assert SPEC and SPEC.loader
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def synthetic_case(tmp_path):
    pins = copy.deepcopy(intake.pinned_fixture())
    directory = tmp_path / "assets"
    directory.mkdir()
    for index, (name, item) in enumerate(pins["assets"].items()):
        data = bytes([65 + index]) * (9 + index)
        (directory / name).write_bytes(data)
        item["size_bytes"] = len(data)
        item["sha256"] = sha(data)
    checksum_data = "".join(
        f"{item['sha256']}  {name}\n" for name, item in pins["assets"].items()
    ).encode("ascii")
    (directory / intake.CHECKSUMS).write_bytes(checksum_data)
    pins["checksums_sha256"] = sha(checksum_data)
    metadata = {
        "id": pins["release_id"], "tag_name": pins["tag"],
        "target_commitish": "main", "published_at": pins["published_at"],
        "draft": False, "prerelease": False,
        "assets": [
            {"name": name, "id": item["id"], "size": item["size_bytes"],
             "digest": "sha256:" + item["sha256"], "state": "uploaded"}
            for name, item in pins["assets"].items()
        ] + [{"name": intake.CHECKSUMS, "id": 689437204,
              "size": 303, "digest": "sha256:" + pins["checksums_sha256"],
              "state": "uploaded"}],
    }
    metadata_path = tmp_path / "release-metadata.json"
    metadata_data = json.dumps(metadata).encode("utf-8")
    metadata_path.write_bytes(metadata_data)
    pins["metadata_sha256"] = sha(metadata_data)
    identity = (pins["tag_object"], pins["source_commit"], pins["source_tree"])
    return metadata_path, directory, pins, identity


def test_retained_published_snapshot_and_annotated_tag():
    pins = intake.pinned_fixture()
    assert intake.git_tag_identity(ROOT, pins["tag"]) == (
        pins["tag_object"], pins["source_commit"], pins["source_tree"]
    )
    fixture_dir = ROOT / "tests/core-release-upgrade"
    intake.verify_metadata(fixture_dir / "release-metadata.json", pins)
    intake.verify_checksums((fixture_dir / "SHA256SUMS.txt").read_bytes(), pins)
    assert pins["source_commit"] != pins["excluded_sdk_fixture_source"]


def test_synthetic_intake_reports_narrow_scope(tmp_path):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    result = intake.inspect(metadata, assets, pins, identity)
    assert result["passed"] is True
    assert result["evidence_level"] == "published_release_byte_intake_only"
    assert result["native_upgrade_qualified"] is False
    assert result["installed_pair_qualified"] is False
    assert result["physical_device_bytes_verified"] is False


@pytest.mark.parametrize("change", ["missing", "swapped", "rebuilt", "extra", "checksum", "metadata"])
def test_synthetic_intake_rejects_bad_bytes_or_inventory(tmp_path, change):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    first, second = list(pins["assets"])[:2]
    if change == "missing":
        (assets / first).unlink()
    elif change == "swapped":
        a, b = (assets / first).read_bytes(), (assets / second).read_bytes()
        (assets / first).write_bytes(b)
        (assets / second).write_bytes(a)
    elif change == "rebuilt":
        (assets / first).write_bytes(b"Z" * pins["assets"][first]["size_bytes"])
    elif change == "extra":
        (assets / "surprise.bin").write_bytes(b"extra")
    elif change == "checksum":
        (assets / intake.CHECKSUMS).write_bytes(b"tampered\n")
    else:
        metadata.write_bytes(metadata.read_bytes() + b" ")
    with pytest.raises(ValueError):
        intake.inspect(metadata, assets, pins, identity)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_synthetic_intake_rejects_wrong_tag_source_or_tree(tmp_path, index):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    changed = list(identity)
    changed[index] = "0" * 40
    with pytest.raises(ValueError, match="source or tree"):
        intake.inspect(metadata, assets, pins, tuple(changed))


def test_sdk_fixture_source_cannot_stand_in_for_release_tag(tmp_path):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    pins["source_commit"] = pins["excluded_sdk_fixture_source"]
    with pytest.raises(ValueError, match="source or tree"):
        intake.inspect(metadata, assets, pins, identity)


@pytest.mark.parametrize("field", ["id", "state", "digest"])
def test_synthetic_intake_rejects_semantic_metadata_change(tmp_path, field):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    value = json.loads(metadata.read_text(encoding="utf-8"))
    if field == "id":
        value["id"] += 1
    elif field == "state":
        value["assets"][0]["state"] = "pending"
    else:
        value["assets"][0]["digest"] = "sha256:" + "0" * 64
    data = json.dumps(value).encode("utf-8")
    metadata.write_bytes(data)
    pins["metadata_sha256"] = sha(data)
    with pytest.raises(ValueError, match="metadata"):
        intake.inspect(metadata, assets, pins, identity)


def test_synthetic_intake_rejects_rehashed_wrong_checksum_inventory(tmp_path):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    data = (assets / intake.CHECKSUMS).read_bytes().replace(b"  ", b" *", 1)
    (assets / intake.CHECKSUMS).write_bytes(data)
    pins["checksums_sha256"] = sha(data)
    value = json.loads(metadata.read_text(encoding="utf-8"))
    value["assets"][-1]["digest"] = "sha256:" + pins["checksums_sha256"]
    metadata_data = json.dumps(value).encode("utf-8")
    metadata.write_bytes(metadata_data)
    pins["metadata_sha256"] = sha(metadata_data)
    with pytest.raises(ValueError, match="checksum inventory"):
        intake.inspect(metadata, assets, pins, identity)


def test_report_is_bounded_and_contains_no_local_paths(tmp_path):
    metadata, assets, pins, identity = synthetic_case(tmp_path)
    output = tmp_path / "report.json"
    intake.write_report(output, intake.inspect(metadata, assets, pins, identity))
    data = output.read_bytes()
    assert len(data) <= intake.MAX_REPORT_BYTES
    assert str(tmp_path).encode() not in data
    with pytest.raises(ValueError, match="unbounded"):
        intake.write_report(output, {"leak": "x" * intake.MAX_REPORT_BYTES})


def test_cli_missing_published_binaries_writes_bounded_failure(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / intake.CHECKSUMS).write_bytes(
        (ROOT / "tests/core-release-upgrade/SHA256SUMS.txt").read_bytes()
    )
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["stage_core_release_baseline.py",
        "--release-metadata", str(ROOT / "tests/core-release-upgrade/release-metadata.json"),
        "--assets-dir", str(assets), "--output", str(report)])
    assert intake.main() == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result == {"v": 1, "passed": False,
                      "evidence_level": "published_release_byte_intake_only",
                      "failure_kind": "ValueError"}


@pytest.mark.parametrize("target", ["metadata", "asset", "fixture"])
def test_cli_unsafe_output_does_not_mutate_any_input(tmp_path, monkeypatch, capsys, target):
    metadata, assets, _, _ = synthetic_case(tmp_path)
    asset = assets / next(iter(intake.pinned_fixture()["assets"]))
    fixture = tmp_path / "fixtures.json"
    fixture.write_bytes(intake.FIXTURES.read_bytes())
    monkeypatch.setattr(intake, "FIXTURES", fixture)
    before = {path: sha(path.read_bytes()) for path in (metadata, asset, fixture)}
    output = {"metadata": metadata, "asset": asset, "fixture": fixture}[target]
    monkeypatch.setattr(sys, "argv", ["stage_core_release_baseline.py",
        "--release-metadata", str(metadata), "--assets-dir", str(assets),
        "--output", str(output)])

    assert intake.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "passed": False, "evidence_level": "published_release_byte_intake_only",
        "failure_kind": "UnsafeOutput"
    }
    assert {path: sha(path.read_bytes()) for path in before} == before


def test_cli_rejects_new_report_inside_asset_inventory(tmp_path, monkeypatch, capsys):
    metadata, assets, _, _ = synthetic_case(tmp_path)
    output = assets / "report.json"
    monkeypatch.setattr(sys, "argv", ["stage_core_release_baseline.py",
        "--release-metadata", str(metadata), "--assets-dir", str(assets),
        "--output", str(output)])
    assert intake.main() == 1
    assert json.loads(capsys.readouterr().out)["failure_kind"] == "UnsafeOutput"
    assert not output.exists()
