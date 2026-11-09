import io
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_kotlin_distribution import verify


def artifact(tmp_path, extra=None):
    classes = io.BytesIO()
    with zipfile.ZipFile(classes, "w") as jar:
        jar.writestr("META-INF/LICENSE", (Path(__file__).resolve().parents[3] / "LICENSE").read_bytes())
        for name in ("com/meshchat/runtime/core/CoreClient.class", "com/meshchat/runtime/IMeshCoreApi.class"):
            jar.writestr(name, b"fixture")
        if extra: jar.writestr(extra, b"fixture")
    path = tmp_path / "client.aar"
    with zipfile.ZipFile(path, "w") as aar:
        aar.writestr("classes.jar", classes.getvalue())
        aar.writestr("AndroidManifest.xml", b"fixture")
    return path


def test_distribution_contains_only_public_client_and_binder_interface(tmp_path):
    assert len(verify(artifact(tmp_path))["sha256"]) == 64


@pytest.mark.parametrize("name", ["com/meshchat/runtime/MeshCoreApiService.class",
    "com/meshchat/runtime/NativeWebRtcHost.class", "com/chaquo/python/Python.class",
    "com/meshchat/core/client/Runtime.class"])
def test_host_and_private_runtime_classes_cannot_enter_client_distribution(tmp_path, name):
    with pytest.raises(ValueError): verify(artifact(tmp_path, name))


def test_missing_client_and_native_payloads_fail_distribution_validation(tmp_path):
    path = artifact(tmp_path)
    with zipfile.ZipFile(path, "a") as aar: aar.writestr("jni/x86_64/libsecret.so", b"native")
    with pytest.raises(ValueError): verify(path)
    with zipfile.ZipFile(path, "w") as aar: aar.writestr("AndroidManifest.xml", b"fixture")
    with pytest.raises(ValueError): verify(path)
