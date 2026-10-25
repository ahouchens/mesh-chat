from __future__ import annotations

from pathlib import Path
import struct
import zipfile

import pytest

from scripts.verify_android_webrtc import WebRtcArtifactError, dex_classes, verify_android_webrtc


CORE = {"org.webrtc.NetworkMonitor", "org.webrtc.PeerConnectionFactory", "org.webrtc.JniCommon"}


def dex(defined: set[str], referenced: set[str] | None = None) -> bytes:
    """Minimal DEX tables, including unused descriptors to expose string-only checks."""
    names = sorted(defined | (referenced or set()))
    result = bytearray(112)
    result[:8] = b"dex\n039\0"
    struct.pack_into("<I", result, 40, 0x12345678)
    strings = len(result)
    result.extend(bytes(4 * len(names)))
    types = len(result)
    result.extend(b"".join(struct.pack("<I", i) for i in range(len(names))))
    classes = len(result)
    for name in sorted(defined):
        result.extend(struct.pack("<8I", names.index(name), 0, 0, 0, 0, 0, 0, 0))
    for index, name in enumerate(names):
        descriptor = ("L" + name.replace(".", "/") + ";").encode()
        assert len(descriptor) < 128
        struct.pack_into("<I", result, strings + 4 * index, len(result))
        result.extend(bytes([len(descriptor)]) + descriptor + b"\0")
    struct.pack_into("<II", result, 56, len(names), strings)
    struct.pack_into("<II", result, 64, len(names), types)
    struct.pack_into("<II", result, 96, len(defined), classes)
    return bytes(result)


def artifact(path: Path, files: dict[str, bytes], native: bool = True) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        if native:
            prefix = "base/" if path.suffix == ".aab" else ""
            archive.writestr(prefix + "lib/arm64-v8a/libjingle_peerconnection_so.so",
                b"\0org.webrtc.NetworkMonitor\0org.webrtc.PeerConnectionFactory\0")
    return path


def test_native_class_reference_is_not_a_class_definition(tmp_path: Path) -> None:
    apk = artifact(tmp_path / "broken.apk", {
        "classes.dex": dex(CORE - {"org.webrtc.NetworkMonitor"}, {"org.webrtc.NetworkMonitor"}),
    })
    with pytest.raises(WebRtcArtifactError, match="org.webrtc.NetworkMonitor"):
        verify_android_webrtc(apk)


@pytest.mark.parametrize("suffix,prefix", [("apk", ""), ("aab", "base/dex/")])
def test_jni_classes_can_span_multiple_dex_files(tmp_path: Path, suffix: str, prefix: str) -> None:
    apk = artifact(tmp_path / f"working.{suffix}", {
        prefix + "classes.dex": dex({"org.webrtc.JniCommon"}),
        prefix + "classes10.dex": dex(CORE - {"org.webrtc.JniCommon"}),
    })
    assert verify_android_webrtc(apk) == {"native_libraries": 1, "jni_classes": 3}


def test_absent_native_library_is_rejected(tmp_path: Path) -> None:
    apk = artifact(tmp_path / "broken.apk", {"classes.dex": dex(CORE)}, native=False)
    with pytest.raises(WebRtcArtifactError, match="missing"):
        verify_android_webrtc(apk)


@pytest.mark.parametrize("data", [b"", b"dex\n039\0", dex(CORE)[:115]])
def test_truncated_dex_is_rejected(data: bytes) -> None:
    with pytest.raises(WebRtcArtifactError, match="truncated|Truncated"):
        dex_classes(data)
