"""Verify local published 0.9.66 bytes without installing or downloading them."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/core-release-upgrade/fixtures.json"
LEVEL = "published_release_byte_intake_only"
CHECKSUMS = "SHA256SUMS.txt"
MAX_REPORT_BYTES = 16 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_fixture():
    pins = json.loads(FIXTURES.read_text(encoding="utf-8"))
    fields = {"v", "tag", "tag_object", "source_commit", "source_tree",
              "excluded_sdk_fixture_source", "release_id", "published_at",
              "metadata_sha256", "checksums_sha256", "assets"}
    asset_names = {"Mesh-Chat_0.9.66_x64-setup.exe", "Mesh-Chat_0.9.66_x64_en-US.msi",
                   "mesh-chat-0.9.66-android-arm64-release.apk"}
    if (type(pins) is not dict or set(pins) != fields or type(pins["v"]) is not int
            or pins["v"] != 1
            or pins["tag"] != "v0.9.66" or type(pins["release_id"]) is not int
            or pins["release_id"] <= 0 or type(pins["assets"]) is not dict
            or set(pins["assets"]) != asset_names
            or any(type(pins[key]) is not str or re.fullmatch(r"[a-f0-9]{40}", pins[key]) is None
                   for key in ("tag_object", "source_commit", "source_tree",
                               "excluded_sdk_fixture_source"))
            or pins["source_commit"] == pins["excluded_sdk_fixture_source"]
            or any(type(pins[key]) is not str or re.fullmatch(r"[a-f0-9]{64}", pins[key]) is None
                   for key in ("metadata_sha256", "checksums_sha256"))
            or type(pins["published_at"]) is not str
            or any(type(item) is not dict or set(item) != {"id", "size_bytes", "sha256"}
                   or type(item["id"]) is not int or item["id"] <= 0
                   or type(item["size_bytes"]) is not int or item["size_bytes"] <= 0
                   or type(item["sha256"]) is not str
                   or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None
                   for item in pins["assets"].values())):
        raise ValueError("Published release fixture is invalid")
    return pins


def git_tag_identity(root, tag):
    reference = "refs/tags/" + tag
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root,
                                       stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    if git("cat-file", "-t", reference) != "tag":
        raise ValueError("Published release tag is not annotated")
    return (git("rev-parse", reference), git("rev-parse", reference + "^{commit}"),
            git("rev-parse", reference + "^{tree}"))


def require_tag(pins, identity):
    if identity != (pins["tag_object"], pins["source_commit"], pins["source_tree"]):
        raise ValueError("Published release source or tree differs from tag")


def bounded_file(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("Published release input is missing or unbounded")
    data = path.read_bytes()
    if not 0 < len(data) <= limit or len(data) != path.stat().st_size:
        raise ValueError("Published release input changed during read")
    return data


def verify_metadata(path, pins):
    data = bounded_file(path, 16 * 1024)
    if digest(data) != pins["metadata_sha256"]:
        raise ValueError("Published release metadata bytes differ")
    value = json.loads(data)
    if (type(value) is not dict or value.get("id") != pins["release_id"]
            or value.get("tag_name") != pins["tag"] or value.get("target_commitish") != "main"
            or value.get("published_at") != pins["published_at"]
            or value.get("draft") is not False or value.get("prerelease") is not False
            or type(value.get("assets")) is not list):
        raise ValueError("Published release metadata identity differs")
    expected = {**pins["assets"], CHECKSUMS: {"id": 689437204,
        "size_bytes": 303, "sha256": pins["checksums_sha256"]}}
    observed = value["assets"]
    if (len(observed) != len(expected) or any(type(item) is not dict for item in observed)
            or {item.get("name") for item in observed} != set(expected)):
        raise ValueError("Published release asset inventory differs")
    for item in observed:
        pinned = expected[item["name"]]
        if (item.get("id") != pinned["id"] or item.get("size") != pinned["size_bytes"]
                or item.get("digest") != "sha256:" + pinned["sha256"]
                or item.get("state") != "uploaded"):
            raise ValueError("Published release asset metadata differs")


def verify_checksums(data, pins):
    if digest(data) != pins["checksums_sha256"]:
        raise ValueError("Published checksum text differs")
    expected = "".join(f"{item['sha256']}  {name}\n"
                       for name, item in pins["assets"].items()).encode("ascii")
    if data != expected:
        raise ValueError("Published checksum inventory differs")


def verify_asset(path, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["size_bytes"]:
        raise ValueError("Published release asset is missing or changed")
    before = path.stat()
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (actual != expected["sha256"] or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError("Published release asset bytes differ")


def verify_assets(directory, pins):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Published release asset directory is invalid")
    expected = set(pins["assets"]) | {CHECKSUMS}
    if {item.name for item in directory.iterdir()} != expected:
        raise ValueError("Published release asset directory inventory differs")
    verify_checksums(bounded_file(directory / CHECKSUMS, 4096), pins)
    for name, item in pins["assets"].items():
        verify_asset(directory / name, item)


def inspect(metadata_path, assets_dir, pins, tag_identity):
    require_tag(pins, tag_identity)
    verify_metadata(metadata_path, pins)
    verify_assets(assets_dir, pins)
    return {"v": 1, "passed": True, "evidence_level": LEVEL,
            "scope": "Published 0.9.66 release bytes verified offline; no installation, native upgrade, physical-device identity or supported-pair claim",
            "tag": pins["tag"], "tag_object": pins["tag_object"],
            "baseline_source": pins["source_commit"], "baseline_tree": pins["source_tree"],
            "release_id": pins["release_id"], "metadata_sha256": pins["metadata_sha256"],
            "checksums_sha256": pins["checksums_sha256"],
            "assets": pins["assets"], "native_upgrade_qualified": False,
            "installed_pair_qualified": False, "physical_device_bytes_verified": False}


def write_report(path, value):
    encoded = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("Published release intake report is unbounded")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def output_overlaps_inputs(output, metadata, assets_dir):
    output_path = output.resolve()
    asset_root = assets_dir.resolve()
    return (output_path in {metadata.resolve(), FIXTURES.resolve()}
            or output_path.is_relative_to(asset_root)
            or output.parent.resolve().is_relative_to(asset_root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-metadata", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        unsafe_output = output_overlaps_inputs(
            args.output, args.release_metadata, args.assets_dir
        )
    except Exception:
        unsafe_output = True
    if unsafe_output:
        print(json.dumps({"passed": False, "evidence_level": LEVEL,
                          "failure_kind": "UnsafeOutput"}))
        return 1
    try:
        pins = pinned_fixture()
        result = inspect(args.release_metadata, args.assets_dir, pins,
                         git_tag_identity(ROOT, pins["tag"]))
    except Exception as error:
        result = {"v": 1, "passed": False, "evidence_level": LEVEL,
                  "failure_kind": type(error).__name__}
    write_report(args.output, result)
    print(json.dumps({"passed": result["passed"], "evidence_level": LEVEL}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
