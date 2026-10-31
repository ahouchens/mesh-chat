"""Fail closed unless staged release assets match the qualified manifest.

Publication may only proceed with the exact bytes the release qualification
aggregator hashed. This script re-hashes the staged files and refuses any name,
size or digest mismatch, an unpassed manifest, or a different release version.
"""

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_NAMES = {
    "setup": "Mesh-Chat_{version}_x64-setup.exe",
    "msi": "Mesh-Chat_{version}_x64_en-US.msi",
    "apk": "mesh-chat-{version}-android-arm64-release.apk",
}
MAX_ASSET_BYTES = 1024 * 1024 * 1024


def verify(manifest_path, assets):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("v") != 1 or manifest.get("passed") is not True:
        raise ValueError("Release qualification manifest did not pass")
    version = manifest.get("release_version")
    artifacts = manifest.get("artifacts")
    if not isinstance(version, str) or not isinstance(artifacts, dict) or set(artifacts) != set(EXPECTED_NAMES):
        raise ValueError("Release qualification manifest is incomplete")
    observed = {}
    for kind, pattern in EXPECTED_NAMES.items():
        expected = artifacts[kind]
        path = Path(assets) / pattern.format(version=version)
        if not path.is_file():
            raise ValueError(f"Qualified asset is missing: {path.name}")
        size = path.stat().st_size
        if not 0 < size <= MAX_ASSET_BYTES:
            raise ValueError(f"Qualified asset has an invalid size: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected.get("bytes") != size or expected.get("sha256") != digest:
            raise ValueError(f"Qualified asset does not match its digest: {path.name}")
        observed[kind] = {"sha256": digest, "bytes": size}
    return {"passed": True, "release_version": version, "artifacts": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.manifest, args.assets)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
