"""Stage CPython 3.13 and pure-Python Mesh Chat packages for an iOS build."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "ios" / "Frameworks"
STAGING = ROOT / "service" / "build" / "ios"
PACKAGES = STAGING / "app_packages"
SUPPORT_URL = (
    "https://github.com/beeware/Python-Apple-support/releases/download/3.13-b14/"
    "Python-3.13-iOS-support.b14.tar.gz"
)
SUPPORT_SHA256 = "8b5cb76ef8d8a2946052479358eeec9d54b4496cb60920e175ec1489b5cf7963"
PURE_REQUIREMENTS = ("rns==1.5.5", "lxmf==1.2.0", "pyserial==3.5")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_wheel_extract(wheel: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"Unsafe wheel member: {member.filename}")
            if target.suffix in {".so", ".dylib"}:
                raise RuntimeError(f"Unexpected binary dependency in iOS wheel: {member.filename}")
        archive.extractall(destination)


def main() -> int:
    FRAMEWORKS.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    archive = STAGING / "Python-3.13-iOS-support.b14.tar.gz"
    if not archive.is_file() or sha256(archive) != SUPPORT_SHA256:
        print(f"Downloading {SUPPORT_URL}")
        with urllib.request.urlopen(SUPPORT_URL, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    if sha256(archive) != SUPPORT_SHA256:
        raise RuntimeError("Python iOS support package checksum mismatch")

    with tempfile.TemporaryDirectory(prefix="mesh-chat-ios-") as temporary:
        extracted = Path(temporary) / "support"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(extracted, filter="data")
        matches = list(extracted.rglob("Python.xcframework"))
        if len(matches) != 1:
            raise RuntimeError("Python.xcframework was not found in the verified support package")
        target = FRAMEWORKS / "Python.xcframework"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(matches[0], target, symlinks=True)

        wheels = Path(temporary) / "wheels"
        wheels.mkdir()
        subprocess.run(
            [
                __import__("sys").executable,
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--no-deps",
                "--dest",
                str(wheels),
                *PURE_REQUIREMENTS,
            ],
            check=True,
        )
        if PACKAGES.exists():
            shutil.rmtree(PACKAGES)
        PACKAGES.mkdir(parents=True)
        for wheel in sorted(wheels.glob("*.whl")):
            safe_wheel_extract(wheel, PACKAGES)

    shutil.copytree(
        ROOT / "service" / "src" / "mesh_chat",
        PACKAGES / "mesh_chat",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    if (PACKAGES / "cryptography").exists():
        raise RuntimeError("A host cryptography binary was accidentally staged for iOS")
    (STAGING / "runtime.json").write_text(
        json.dumps(
            {
                "python_support": "3.13-b14",
                "python_support_sha256": SUPPORT_SHA256,
                "requirements": PURE_REQUIREMENTS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Python framework: {FRAMEWORKS / 'Python.xcframework'}")
    print(f"Application packages: {PACKAGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
