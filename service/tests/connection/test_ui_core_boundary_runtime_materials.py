"""Archive qualification rejects notices/DLLs dropped after dependency staging."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import native_runtime_materials as materials


@pytest.fixture
def installed(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "service").mkdir()
    declaration = json.loads(materials.DECLARATION.read_text())
    (tmp_path / "scripts/native-runtime-materials-v1.json").write_text(json.dumps(declaration))
    (tmp_path / "service/requirements.lock").write_text("aiortc==1.13.0\naioice==0.10.2\nav==14.2.0\n")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("repository notice")
    distributions = {}
    for name, version in (("aiortc", "1.13.0"), ("aioice", "0.10.2"), ("av", "14.2.0")):
        files = [f"{name}-{version}.dist-info/METADATA", f"{name}-{version}.dist-info/licenses/LICENSE"]
        if name == "av":
            files += ["av.libs/avcodec-test.dll", "av.libs/libx264-test.dll", "av/_core.pyd"]
        for file in files:
            path = tmp_path / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file.encode())
        distributions[name] = SimpleNamespace(version=version, files=files,
            metadata={"License-Expression": "test-fixture"}, locate_file=lambda file: tmp_path / file)
    return tmp_path, distributions


class Archive:
    def __init__(self, data):
        self.data = data
        self.toc = {name: (0, 0, 0, 0, "x") for name in data}
        self.toc["PYZ.pyz"] = (0, 0, 0, 0, "z")
        self.modules = {"aiortc": (), "aioice": (), "av": ()}

    def extract(self, name):
        return self.data[name]

    def open_embedded_archive(self, name):
        assert name == "PYZ.pyz"
        return SimpleNamespace(toc=self.modules)


def staged(installed):
    root, distributions = installed
    expected, datas = materials.collection(root=root, distribution=distributions.__getitem__)
    data = {str(Path(target) / Path(source).name).replace("\\", "/"): Path(source).read_bytes()
            for source, target in datas}
    # The declaration is semantically identical; preserve production bytes in archive.
    data[materials.PREFIX + "/declaration.json"] = materials.DECLARATION.read_bytes()
    data[materials.EMBEDDED] = materials.canonical(expected)
    data.update({file: (root / file).read_bytes() for file in distributions["av"].files
                 if file.endswith((".dll", ".pyd"))})
    data["python313.dll"] = b"fixture python runtime"
    return expected, Archive(data), json.loads(materials.DECLARATION.read_text())


def test_complete_archive_inventories_native_bytes_and_does_not_claim_legal_approval(installed):
    expected, archive, declaration = staged(installed)
    report = materials.inspect_archive(archive, expected, declaration)
    assert report["notice_files_verified"] == 6
    assert len(report["native_archive_files"]) == 4
    assert report["native_files_without_wheel_owner"] == ["python313.dll"]
    assert next(item for item in report["native_archive_files"] if "libx264" in item["path"])["wheel_distributions"] == ["av"]
    assert report["release_approval"] is False
    assert "FFmpeg" in report["notice_limits"]


def test_reads_real_pyinstaller_archive_and_embedded_pyz_without_extraction(installed, tmp_path):
    from PyInstaller.archive.readers import CArchiveReader
    from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter
    expected, archive, declaration = staged(installed)
    directory = tmp_path / "archive-inputs"
    directory.mkdir()
    pyz = directory / "PYZ.pyz"
    entries = [(name, "fixture/__init__.py", "PYMODULE") for name in archive.modules]
    ZlibArchiveWriter(str(pyz), entries, code_dict={name: compile("", "fixture/__init__.py", "exec") for name in archive.modules})
    contents = []
    for index, (name, data) in enumerate(archive.data.items()):
        path = directory / str(index)
        path.write_bytes(data)
        contents.append((name, str(path), True, "x"))
    contents.append(("PYZ.pyz", str(pyz), False, "z"))
    packaged = directory / "fixture.pkg"
    CArchiveWriter(str(packaged), contents, "python313.dll")
    report = materials.inspect_archive(CArchiveReader(str(packaged)), expected, declaration)
    assert report["notice_files_verified"] == 6
    assert report["required_modules_verified"] == ["aiortc", "aioice", "av"]


@pytest.mark.parametrize("path", [materials.EMBEDDED, materials.PREFIX + "/declaration.json",
    materials.PREFIX + "/THIRD_PARTY_NOTICES.md",
    materials.PREFIX + "/distributions/aiortc/aiortc-1.13.0.dist-info/licenses/LICENSE",
    "av.libs/avcodec-test.dll", "av.libs/libx264-test.dll"])
@pytest.mark.parametrize("fault", ["missing", "changed"])
def test_archive_material_dropped_or_replaced_after_staging_is_fatal(installed, path, fault):
    expected, archive, declaration = staged(installed)
    if fault == "missing":
        del archive.data[path]
        del archive.toc[path]
    else:
        archive.data[path] = b"different bytes"
    with pytest.raises((ValueError, KeyError)):
        materials.inspect_archive(archive, expected, declaration)


@pytest.mark.parametrize("module", ["aiortc", "aioice", "av"])
def test_notices_alone_cannot_qualify_absent_runtime_code(installed, module):
    expected, archive, declaration = staged(installed)
    del archive.modules[module]
    with pytest.raises(ValueError, match="runtime module"):
        materials.inspect_archive(archive, expected, declaration)


def test_installed_dependency_version_must_match_pinned_lock(installed):
    root, distributions = installed
    distributions["av"].version = "99"
    with pytest.raises(ValueError, match="version differs"):
        materials.collection(root=root, distribution=distributions.__getitem__)


def test_required_notice_cannot_be_replaced_with_metadata_alone(installed):
    root, distributions = installed
    distributions["aioice"].files = distributions["aioice"].files[:1]
    with pytest.raises(ValueError, match="notice is missing"):
        materials.collection(root=root, distribution=distributions.__getitem__)


def test_unrelated_installed_entry_points_are_not_copied(installed):
    root, distributions = installed
    distributions["aioice"].files.append("../../../Scripts/unrelated.exe")
    value, datas = materials.collection(root=root, distribution=distributions.__getitem__)
    assert len(value["packages"]) == 3
    assert all(Path(source).name != "unrelated.exe" for source, _ in datas)


def test_unsafe_material_record_paths_fail_instead_of_leaving_archive_root(installed):
    root, distributions = installed
    distributions["aioice"].files.append("../foreign.dll")
    with pytest.raises(ValueError, match="Unsafe"):
        materials.collection(root=root, distribution=distributions.__getitem__)


def test_duplicate_normalized_archive_paths_are_ambiguous(installed):
    expected, archive, declaration = staged(installed)
    archive.toc["av.libs\\avcodec-test.dll"] = archive.toc["av.libs/avcodec-test.dll"]
    with pytest.raises(ValueError, match="ambiguous"):
        materials.inspect_archive(archive, expected, declaration)


@pytest.mark.parametrize("content", ["", "av>=14", "av==14\nav==14\n", "av==14 --hash=x"])
def test_unpinned_or_ambiguous_runtime_lock_fails(tmp_path, content):
    path = tmp_path / "requirements.lock"
    path.write_text(content)
    with pytest.raises(ValueError):
        materials.locked_distributions(path)
