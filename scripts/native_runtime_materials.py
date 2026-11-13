"""Inventory actual frozen archive bytes, with deliberately bounded notice claims."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = Path(__file__).with_name("native-runtime-materials-v1.json")
PREFIX = "mesh-runtime-materials"
EMBEDDED = PREFIX + "/inventory.json"
EMBEDDED_DECLARATION = PREFIX + "/native-runtime-materials-v1.json"
LEVEL = "windows_frozen_runtime_materials_inventory"


class MaterialFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def text_bytes(path):
    """Repository text must have identical archive bytes on Windows and Linux."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def archive_name(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not name or ":" in name:
        raise ValueError("Unsafe runtime material path")
    return name


def locked_distributions(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if match is None or normalized(match[1]) in result:
            raise ValueError("Runtime lock must contain unique exact versions")
        result[normalized(match[1])] = match[2]
    if not result:
        raise ValueError("Runtime lock is empty")
    return result


def collection(*, root=ROOT, distribution=importlib.metadata.distribution):
    """Use installed wheel RECORD membership; do not infer DLL licensing."""
    declaration = json.loads((root / "scripts/native-runtime-materials-v1.json").read_text())
    packages, datas = [], []
    required = set(declaration["required_notice_distributions"])
    for name, version in sorted(locked_distributions(root / "service/requirements.lock").items()):
        installed = distribution(name)
        if installed.version != version:
            raise ValueError("Installed runtime version differs from the lock: " + name)
        materials, native = [], []
        for file in installed.files or ():
            raw = str(file).replace("\\", "/")
            leaf = PurePosixPath(raw).name.lower()
            candidate_notice = (".dist-info/" in raw and not leaf.endswith((".pyc", ".pyo"))
                                and (leaf == "metadata" or any(word in leaf for word in ("license", "copying", "notice", "authors"))))
            if not candidate_notice and PurePosixPath(raw).suffix.lower() not in {".dll", ".pyd"}:
                continue
            relative = archive_name(raw)
            path = Path(installed.locate_file(file))
            if path.suffix.lower() in {".dll", ".pyd"}:
                native.append({"path": relative, "sha256": digest(path.read_bytes())})
            if not candidate_notice:
                continue
            target = f"{PREFIX}/distributions/{name}/{relative}"
            data = path.read_bytes()
            if not data or len(data) > 4 * 1024 * 1024:
                raise ValueError("Runtime notice is empty or exceeds budget")
            materials.append({"path": target, "sha256": digest(data), "kind": "metadata" if leaf == "metadata" else "notice"})
            datas.append((str(path), str(PurePosixPath(target).parent)))
        if not materials or not any(item["kind"] == "metadata" for item in materials):
            raise ValueError("Installed runtime metadata is missing: " + name)
        if name in required and not any(item["kind"] == "notice" for item in materials):
            raise ValueError("Required installed runtime notice is missing: " + name)
        packages.append({"name": name, "version": version,
                         "declared_license": installed.metadata.get("License-Expression") or installed.metadata.get("License") or "unspecified",
                         "notice_files": materials, "wheel_native_files": native})
    for source, target in ((root / "THIRD_PARTY_NOTICES.md", PREFIX + "/THIRD_PARTY_NOTICES.md"),
                           (root / "LICENSE", PREFIX + "/LICENSE"),
                           (root / "scripts/native-runtime-materials-v1.json", EMBEDDED_DECLARATION)):
        datas.append((str(source), str(PurePosixPath(target).parent)))
    return {"v": 1, "declaration_sha256": digest(canonical(declaration)), "packages": packages,
            "project_license_sha256": digest(text_bytes(root / "LICENSE")),
            "repository_notices_sha256": digest(text_bytes(root / "THIRD_PARTY_NOTICES.md"))}, datas


def pyinstaller_datas(*, root=ROOT, distribution=importlib.metadata.distribution):
    inventory, datas = collection(root=root, distribution=distribution)
    path = root / "service/build/native-runtime-materials/inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(inventory))
    repository_inputs = {root / "LICENSE", root / "THIRD_PARTY_NOTICES.md", root / "scripts/native-runtime-materials-v1.json"}
    staged = []
    for source, target in datas:
        source = Path(source)
        if source in repository_inputs:
            normalized = path.parent / "repository" / source.name
            normalized.parent.mkdir(parents=True, exist_ok=True)
            normalized.write_bytes(text_bytes(source))
            source = normalized
        staged.append((str(source), target))
    return [*staged, (str(path), PREFIX)]


def inspect_archive(archive, expected, declaration):
    names = {archive_name(name): name for name in archive.toc}
    if len(names) != len(archive.toc):
        raise ValueError("Frozen archive has ambiguous normalized paths")
    def extract(name):
        if name not in names:
            code = {EMBEDDED: "frozen_inventory_missing", EMBEDDED_DECLARATION: "frozen_declaration_missing",
                    PREFIX + "/LICENSE": "frozen_project_license_missing",
                    PREFIX + "/THIRD_PARTY_NOTICES.md": "frozen_repository_notices_missing"}.get(name, "frozen_dependency_material_missing")
            raise MaterialFailure(code)
        value = archive.extract(names[name])
        if not isinstance(value, bytes):
            raise ValueError("Required frozen material is not bytes")
        return value
    if extract(EMBEDDED) != canonical(expected):
        raise ValueError("Frozen inventory differs from the installed locked materials")
    if digest(extract(EMBEDDED_DECLARATION)) != digest(text_bytes(DECLARATION)):
        raise MaterialFailure("frozen_declaration_changed")
    if digest(extract(PREFIX + "/THIRD_PARTY_NOTICES.md")) != expected["repository_notices_sha256"]:
        raise ValueError("Frozen repository notice differs")
    if digest(extract(PREFIX + "/LICENSE")) != expected["project_license_sha256"]:
        raise ValueError("Frozen project license differs")
    owners = {}
    notice_count = 0
    for package in expected["packages"]:
        for item in package["notice_files"]:
            if digest(extract(item["path"])) != item["sha256"]:
                raise ValueError("Frozen dependency notice bytes differ")
            notice_count += 1
        for item in package["wheel_native_files"]:
            owners.setdefault(item["sha256"], []).append(package["name"])
    modules = set()
    for name, entry in archive.toc.items():
        if entry[-1] == "z":
            modules.update(archive.open_embedded_archive(name).toc)
    for name in declaration["required_modules"]:
        if name not in modules:
            raise ValueError("Required runtime module is absent from the frozen PYZ: " + name)
    binaries = []
    for name in sorted(names):
        if PurePosixPath(name).suffix.lower() not in declaration["native_suffixes"]:
            continue
        sha = digest(extract(name))
        binaries.append({"path": name, "sha256": sha, "wheel_distributions": sorted(owners.get(sha, []))})
    by_hash = {item["sha256"] for item in binaries}
    # av wheel DLLs (including FFmpeg and codec dependencies) must all survive staging.
    av = next(item for item in expected["packages"] if item["name"] == "av")
    av_dlls = [item for item in av["wheel_native_files"] if item["path"].lower().endswith(".dll")]
    if not av_dlls or any(item["sha256"] not in by_hash for item in av_dlls):
        raise ValueError("Frozen archive omits native DLLs shipped in the locked PyAV wheel")
    return {"packages": expected["packages"], "native_archive_files": binaries,
            "project_license_sha256": expected["project_license_sha256"],
            "notice_files_verified": notice_count, "required_modules_verified": declaration["required_modules"],
            "notice_limits": declaration["wheel_native_notice_limit"],
            "native_files_without_wheel_owner": [item["path"] for item in binaries if not item["wheel_distributions"]],
            "release_approval": False}


def verify_report(record, source, tree):
    declaration = json.loads(DECLARATION.read_text())
    fields = {"v", "passed", "evidence_level", "source_commit", "source_tree", "sidecar_sha256",
              "build_input_sha256", "build_manifest_sha256", "inventory", "scope", "declaration_sha256"}
    if (not isinstance(record, dict) or set(record) != fields or type(record["v"]) is not int
            or record["v"] != 1 or record["passed"] is not True or record["evidence_level"] != LEVEL
            or record["source_commit"] != source or record["source_tree"] != tree
            or record["scope"] != declaration["scope"]
            or record["declaration_sha256"] != digest(text_bytes(DECLARATION))):
        raise ValueError("Runtime materials report source, declaration or outcome differs")
    def sha(value):
        if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
            raise ValueError("Invalid runtime material digest")
    for key in ("sidecar_sha256", "build_input_sha256", "build_manifest_sha256"):
        sha(record[key])
    value = record["inventory"]
    if (not isinstance(value, dict) or set(value) != {"packages", "native_archive_files", "notice_files_verified", "project_license_sha256",
            "required_modules_verified", "notice_limits", "native_files_without_wheel_owner", "release_approval"}
            or value["required_modules_verified"] != declaration["required_modules"]
            or value["notice_limits"] != declaration["wheel_native_notice_limit"] or value["release_approval"] is not False
            or value["project_license_sha256"] != digest(text_bytes(ROOT / "LICENSE"))):
        raise ValueError("Runtime material scope or inventory is incomplete")
    packages = value["packages"]
    locked = locked_distributions(ROOT / "service/requirements.lock")
    if (not isinstance(packages, list) or len(packages) != len(locked)
            or {item.get("name"): item.get("version") for item in packages if isinstance(item, dict)} != locked):
        raise ValueError("Runtime distribution inventory differs from the lock")
    owners, notice_paths, av_dlls = {}, set(), set()
    for package in packages:
        if (set(package) != {"name", "version", "declared_license", "notice_files", "wheel_native_files"}
                or not isinstance(package["declared_license"], str) or not package["declared_license"]
                or not isinstance(package["notice_files"], list) or not 0 < len(package["notice_files"]) <= 100
                or not isinstance(package["wheel_native_files"], list) or len(package["wheel_native_files"]) > 512):
            raise ValueError("Malformed locked package materials")
        kinds = set()
        for item in package["notice_files"]:
            if (not isinstance(item, dict) or set(item) != {"path", "sha256", "kind"}
                    or item["kind"] not in {"metadata", "notice"}
                    or not archive_name(item["path"]).startswith(f"{PREFIX}/distributions/{package['name']}/")
                    or item["path"] in notice_paths):
                raise ValueError("Missing or ambiguous package notice")
            sha(item["sha256"])
            notice_paths.add(item["path"])
            kinds.add(item["kind"])
        if "metadata" not in kinds or (package["name"] in declaration["required_notice_distributions"] and "notice" not in kinds):
            raise ValueError("Required package metadata or notice is missing")
        for item in package["wheel_native_files"]:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise ValueError("Malformed native wheel file")
            archive_name(item["path"])
            sha(item["sha256"])
            owners.setdefault(item["sha256"], set()).add(package["name"])
            if package["name"] == "av" and item["path"].lower().endswith(".dll"):
                av_dlls.add(item["sha256"])
    files = value["native_archive_files"]
    if not isinstance(files, list) or not 0 < len(files) <= 2048:
        raise ValueError("Native archive inventory is empty or unbounded")
    paths, hashes, unknown = set(), set(), []
    for item in files:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256", "wheel_distributions"}
                or PurePosixPath(archive_name(item["path"])).suffix.lower() not in declaration["native_suffixes"]
                or item["path"] in paths):
            raise ValueError("Malformed or duplicated native archive file")
        sha(item["sha256"])
        if item["wheel_distributions"] != sorted(owners.get(item["sha256"], [])):
            raise ValueError("Native archive owner does not match wheel bytes")
        paths.add(item["path"])
        hashes.add(item["sha256"])
        if not item["wheel_distributions"]:
            unknown.append(item["path"])
    if (not av_dlls or not av_dlls <= hashes or value["native_files_without_wheel_owner"] != unknown
            or type(value["notice_files_verified"]) is not int or value["notice_files_verified"] != len(notice_paths)):
        raise ValueError("Native DLL or notice coverage is incomplete")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/reports/native-runtime-materials.json")
    args = parser.parse_args()
    result = {"v": 1, "passed": False, "evidence_level": LEVEL}
    phase = "source_artifact_binding"
    try:
        from native_windows_evidence import artifact_binding, require_unchanged
        from PyInstaller.archive.readers import CArchiveReader
        binary, binding = artifact_binding(args.expected_source)
        phase = "locked_installed_materials"
        expected, _ = collection()
        declaration = json.loads(DECLARATION.read_text())
        phase = "frozen_archive_open"
        archive = CArchiveReader(str(binary))
        phase = "frozen_archive_validation"
        inspected = inspect_archive(archive, expected, declaration)
        phase = "unchanged_artifact_binding"
        require_unchanged(binary, binding)
        result.update(binding, inventory=inspected, passed=True,
                      scope=declaration["scope"], declaration_sha256=digest(text_bytes(DECLARATION)))
        verify_report(result, binding["source_commit"], binding["source_tree"])
    except Exception as error:
        result["passed"] = False
        result["failure_type"] = type(error).__name__
        result["phase"] = phase
        result["error_code"] = error.code if isinstance(error, MaterialFailure) else {
            KeyError: "archive_member_missing", FileNotFoundError: "required_file_missing",
            ValueError: "material_validation_failed", RuntimeError: "artifact_binding_failed",
        }.get(type(error), "materials_verification_failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "phase", "error_code", "failure_type") if key in result}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
