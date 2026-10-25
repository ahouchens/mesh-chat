"""Reject APK/AAB files whose shrinking broke the packaged WebRTC JNI ABI.

Read class *definitions*, not strings/references, from every DEX file. Native
class lookups are extracted from the packaged libjingle itself, so an updated
native dependency also updates the class set checked before publication.
Runtime instrumentation separately exercises method signatures and callbacks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import zipfile


class WebRtcArtifactError(ValueError):
    pass


def dex_classes(data: bytes) -> set[str]:
    if len(data) < 112 or data[:4] != b"dex\n" or data[4:8] not in {
        b"035\0", b"037\0", b"038\0", b"039\0", b"040\0",
    }:
        raise WebRtcArtifactError("Unsupported or truncated DEX header")

    def uint(offset: int) -> int:
        if offset < 0 or offset + 4 > len(data):
            raise WebRtcArtifactError("Truncated DEX table")
        return struct.unpack_from("<I", data, offset)[0]

    def table(offset: int, width: int) -> tuple[int, int]:
        size, start = uint(offset), uint(offset + 4)
        if start + size * width > len(data):
            raise WebRtcArtifactError("Truncated DEX table")
        return size, start

    if uint(40) != 0x12345678:
        raise WebRtcArtifactError("Unsupported DEX byte order")
    string_count, strings = table(56, 4)
    type_count, types = table(64, 4)
    class_count, classes = table(96, 32)
    result = set()
    for index in range(class_count):
        type_index = uint(classes + index * 32)
        if type_index >= type_count:
            raise WebRtcArtifactError("Invalid DEX class type")
        string_index = uint(types + type_index * 4)
        if string_index >= string_count:
            raise WebRtcArtifactError("Invalid DEX type descriptor")
        start = uint(strings + string_index * 4)
        # string_data begins with a ULEB128 UTF-16 length, followed by MUTF-8.
        for _ in range(5):
            if start >= len(data):
                raise WebRtcArtifactError("Truncated DEX string")
            byte = data[start]
            start += 1
            if byte < 0x80:
                break
        else:
            raise WebRtcArtifactError("Invalid DEX string length")
        end = data.find(b"\0", start)
        if end < 0:
            raise WebRtcArtifactError("Unterminated DEX string")
        descriptor = data[start:end].decode("utf-8", errors="replace")
        if descriptor.startswith("L") and descriptor.endswith(";"):
            result.add(descriptor[1:-1].replace("/", "."))
    return result


def verify_android_webrtc(artifact: Path) -> dict[str, int]:
    defined: set[str] = set()
    required: set[str] = {"org.webrtc.JniCommon"}
    native_count = 0
    with zipfile.ZipFile(artifact) as archive:
        for name in archive.namelist():
            if re.fullmatch(r"(?:base/dex/)?classes[0-9]*\.dex", name):
                defined.update(dex_classes(archive.read(name)))
            elif name.endswith("/libjingle_peerconnection_so.so"):
                native_count += 1
                references = {
                    value.decode("ascii") for value in re.findall(
                        rb"\borg\.webrtc\.[A-Za-z0-9_.$]+", archive.read(name)
                    )
                }
                if not {"org.webrtc.NetworkMonitor", "org.webrtc.PeerConnectionFactory"} <= references:
                    raise WebRtcArtifactError(f"WebRTC JNI class lookups not found in {name}")
                required.update(references)
    if not native_count or not defined:
        raise WebRtcArtifactError("Packaged WebRTC library or DEX definitions are missing")
    missing = required - defined
    if missing:
        raise WebRtcArtifactError(
            "WebRTC JNI classes removed or renamed by shrinking: " + ", ".join(sorted(missing))
        )
    return {"native_libraries": native_count, "jni_classes": len(required)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_android_webrtc(args.artifact), sort_keys=True))
    except (OSError, zipfile.BadZipFile, WebRtcArtifactError) as error:
        parser.exit(1, f"Android WebRTC verification failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
