"""Reject private runtime/native payloads in the public Android client AAR."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile


def entries(archive):
    values = archive.infolist()
    if (len(values) > 1024 or sum(item.file_size for item in values) > 16 * 1024 * 1024
            or len({item.filename for item in values}) != len(values)):
        raise ValueError("Distribution archive exceeds bounds or repeats entries")
    return {item.filename for item in values}


def verify(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Client distribution exceeds bounds")
    with zipfile.ZipFile(path) as aar:
        names = entries(aar)
        if not {"classes.jar", "AndroidManifest.xml"} <= names or any(
                name.endswith((".so", ".py", ".pyc")) or (name.endswith(".jar") and name != "classes.jar")
                for name in names):
            raise ValueError("Distribution has missing client or unexpected runtime payloads")
        with zipfile.ZipFile(io.BytesIO(aar.read("classes.jar"))) as jar:
            jar_entries = entries(jar)
            if "META-INF/LICENSE" not in jar_entries:
                raise ValueError("Client distribution omits license")
            if jar.read("META-INF/LICENSE") != (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes():
                raise ValueError("Client distribution license differs from the project license")
            classes = {name for name in jar_entries if name.endswith(".class")}
            if not {"com/meshchat/runtime/core/CoreClient.class", "com/meshchat/runtime/IMeshCoreApi.class"} <= classes:
                raise ValueError("Distribution lacks the public client or Binder interface")
            for name in classes:
                public_class = name.removesuffix(".class").split("$")[0]
                if not (public_class in {"com/meshchat/runtime/core/" + kind for kind in
                        ("CoreClient", "CoreTransport", "CoreExchangeTransport", "CoreException")}
                        or name == "com/meshchat/runtime/IMeshCoreApi.class"
                        or name.startswith("com/meshchat/runtime/IMeshCoreApi$")
                        or name == "com/meshchat/core/client/R.class"
                        or name.startswith("com/meshchat/core/client/R$")):
                    raise ValueError("Private implementation entered client distribution")
    return {"artifact": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]))))
