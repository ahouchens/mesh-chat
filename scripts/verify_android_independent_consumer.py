"""Verify the published ordinary host, installed dependency payload and exact staging inputs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0-experimental"
APP_ID = "com.meshchat.core.independent"
APPLICATION_FILES = ("settings.gradle.kts", "build.gradle.kts", "gradle.properties", "README.md",
    "app/build.gradle.kts", "app/src/main/AndroidManifest.xml",
    "app/src/main/java/com/meshchat/core/independent/ConsumerApplication.kt",
    "app/src/androidTest/java/com/meshchat/core/independent/IndependentConsumerTest.kt")
PUBLICATIONS = {
    f"repository/com/meshchat/{artifact}/{VERSION}/{artifact}-{VERSION}{suffix}":
        ROOT / producer / f"build/repository/com/meshchat/{artifact}/{VERSION}/{artifact}-{VERSION}{suffix}"
    for artifact, producer in (("core-runtime-host", "plugins/tauri-plugin-mesh-runtime/android/runtime-host"),
                               ("core-client", "sdk/kotlin"))
    for suffix in (".aar", ".pom", ".module", "-sources.jar")}
OUTPUT = ROOT / "dist/android-independent-consumer"
ARTIFACTS = tuple(OUTPUT / name for name in (*PUBLICATIONS, "consumer.apk", "consumer-test.apk"))
CHECKS = {"outside_checkout": True, "versioned_maven_only": True,
          "host_and_sdk_publications": True, "host_python_and_native_payload": True,
          "merged_own_uid_service_manifest": True, "application_inputs_unchanged": True}
SCOPE = "Ordinary app-owned Android host and public SDK; fresh lifecycle and cold locked process restart only; no successful OS credential UI, peer receipts, media or physical qualification"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publication_path(directory, artifact, extension):
    return directory / f"repository/com/meshchat/{artifact}/{VERSION}/{artifact}-{VERSION}.{extension}"


def verify_publications(directory):
    from verify_kotlin_distribution import verify as verify_sdk
    verify_sdk(publication_path(directory, "core-client", "aar"))
    for artifact in ("core-client", "core-runtime-host"):
        pom = ET.parse(publication_path(directory, artifact, "pom")).getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        if tuple(pom.findtext("m:" + name, namespaces=ns) for name in
                 ("groupId", "artifactId", "version")) != ("com.meshchat", artifact, VERSION):
            raise ValueError("Maven publication identity differs from requested coordinate")
        dependencies = {(item.findtext("m:groupId", namespaces=ns), item.findtext("m:artifactId", namespaces=ns),
                         item.findtext("m:version", namespaces=ns), item.findtext("m:scope", namespaces=ns))
                        for item in pom.findall("m:dependencies/m:dependency", ns)}
        if artifact == "core-runtime-host" and not {
                ("com.meshchat", "core-client", VERSION, "compile"),
                ("androidx.activity", "activity-ktx", "1.10.1", "compile"),
                ("io.github.webrtc-sdk", "android", "150.7871.01", "runtime")} <= dependencies:
            raise ValueError("Host Maven API or native runtime dependencies are missing")
        module = json.loads(publication_path(directory, artifact, "module").read_text())
        component = module.get("component", {})
        if (component.get("group"), component.get("module"), component.get("version")) != (
                "com.meshchat", artifact, VERSION):
            raise ValueError("Gradle publication has the wrong identity")
        aar = publication_path(directory, artifact, "aar")
        published = [item for variant in module.get("variants", []) for item in variant.get("files", [])
                     if item.get("name") == aar.name]
        if not published or any(item.get("sha256") != digest(aar) or item.get("size") != aar.stat().st_size
                                or item.get("url") != aar.name for item in published):
            raise ValueError("Gradle module does not bind the exact AAR")
        sources = aar.with_name(f"{artifact}-{VERSION}-sources.jar")
        advertised_sources = [item for variant in module.get("variants", []) for item in variant.get("files", [])
                              if item.get("name") == sources.name]
        if not advertised_sources:
            raise ValueError("Published module omits its advertised source distribution")
        for variant in module.get("variants", []):
            for item in variant.get("files", []):
                path = aar if item.get("name") == aar.name else sources if item.get("name") == sources.name else None
                if (path is None or item.get("url") != path.name or item.get("sha256") != digest(path)
                        or item.get("size") != path.stat().st_size):
                    raise ValueError("Gradle module references missing or substituted publication files")
        with zipfile.ZipFile(sources) as archive:
            expected = "CoreClient.kt" if artifact == "core-client" else "MeshCoreRuntime.kt"
            if not any(name.endswith("/" + expected) or name == expected for name in archive.namelist()):
                raise ValueError("Published source archive omits its public API")
        if artifact == "core-runtime-host":
            for usage, required in (("java-api", {("com.meshchat", "core-client", VERSION),
                                               ("androidx.activity", "activity-ktx", "1.10.1")}),
                                    ("java-runtime", {("com.meshchat", "core-client", VERSION),
                                                   ("androidx.activity", "activity-ktx", "1.10.1"),
                                                   ("io.github.webrtc-sdk", "android", "150.7871.01")})):
                variants = [variant for variant in module.get("variants", [])
                            if variant.get("attributes", {}).get("org.gradle.usage") == usage
                            and variant.get("attributes", {}).get("org.gradle.category") == "library"
                            and any(item.get("name") == aar.name for item in variant.get("files", []))]
                if not variants or any(not required <= {(item.get("group"), item.get("module"),
                        item.get("version", {}).get("requires")) for item in variant.get("dependencies", [])}
                        or "available-at" in variant for variant in variants):
                    raise ValueError("Gradle-selected host variant omits public API or native runtime dependencies")
    with zipfile.ZipFile(publication_path(directory, "core-runtime-host", "aar")) as aar:
        with zipfile.ZipFile(io.BytesIO(aar.read("classes.jar"))) as jar:
            names = set(jar.namelist())
            if not {f"com/meshchat/runtime/{name}.class" for name in
                    ("MeshCoreRuntime", "MeshCoreApiService", "BootstrapService", "NativeWebRtcBridge")} <= names:
                raise ValueError("Host AAR is missing its normal runtime API")
            if any("tauri" in name.lower() or "MeshRuntimePlugin" in name or "BackgroundRuntime" in name for name in names):
                raise ValueError("Standalone host contains Tauri or legacy application runtime")
            if jar.read("META-INF/LICENSE") != (ROOT / "LICENSE").read_bytes():
                raise ValueError("Runtime host distribution license differs from project license")
        verify_python_payload(aar)


def verify_python_payload(archive):
    with zipfile.ZipFile(io.BytesIO(archive.read("assets/chaquopy/app.imy"))) as python:
        if not any(name in python.namelist() for name in
                   ("mesh_chat/mobile_bridge.pyc", "mesh_chat/mobile_bridge.py")):
            raise ValueError("Normal host Python service is absent")


def verify_record(record, identity, artifacts):
    if (type(record.get("v")) is not int or record["v"] != 1 or record.get("passed") is not True
            or any(record.get(key) != value for key, value in identity.items())
            or record.get("checks") != CHECKS or record.get("scope") != SCOPE
            or any(type(record["checks"].get(key)) is not bool for key in CHECKS)
            or set(record.get("application_files", {})) != set(APPLICATION_FILES)
            or set(record.get("artifacts", {})) != {str(path.relative_to(ROOT)).replace("\\", "/") for path in ARTIFACTS}
            or record.get("artifacts") != {key: artifacts.get(key) for key in record["artifacts"]}
            or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
                   for value in (*record["application_files"].values(), *record["artifacts"].values()))):
        raise ValueError("Independent Android distribution/source/payload scope is incomplete")
    return record


def verify_source_inputs(record):
    for name, expected in record["application_files"].items():
        if digest(ROOT / "examples/android-independent-consumer" / name) != expected:
            raise ValueError("Independent Android source inputs changed after staging")


def signature_only(value):
    # apkanalyzer prints compiled protection flags numerically (signature = 2).
    # Compare the complete value: masking base bits could admit extra flags.
    if value == "signature":
        return True
    if not isinstance(value, str) or re.fullmatch(r"(?:0[xX][0-9a-fA-F]{1,8}|[0-9]{1,10})", value) is None:
        return False
    return int(value, 16 if value.lower().startswith("0x") else 10) == 2


def verify_manifest(manifest):
    ns = "{http://schemas.android.com/apk/res/android}"
    applications = manifest.findall("application")
    if manifest.tag != "manifest" or manifest.get("package") != APP_ID or len(applications) != 1:
        raise ValueError("Installed manifest lacks the ordinary app-owned service authority")
    application = applications[0]
    services = application.findall("service")
    core = [node for node in services if node.get(ns + "name") == "com.meshchat.runtime.MeshCoreApiService"]
    bootstrap = [node for node in services if node.get(ns + "name") == "com.meshchat.runtime.BootstrapService"]
    permission = APP_ID + ".permission.MESH_CORE_API"
    declarations = [node for node in manifest.findall("permission") if node.get(ns + "name") == permission]
    if (application.get(ns + "name") != APP_ID + ".ConsumerApplication"
            or application.get(ns + "allowBackup") != "false" or application.get(ns + "process") is not None
            or len(core) != 1 or len(bootstrap) != 1 or len(declarations) != 1
            or not signature_only(declarations[0].get(ns + "protectionLevel"))
            or not any(node.get(ns + "name") == permission for node in manifest.findall("uses-permission"))):
        raise ValueError("Installed manifest lacks the ordinary app-owned service authority")
    if (core[0].get(ns + "permission") != permission or core[0].get(ns + "exported") != "true"
            or core[0].get(ns + "process") is not None or core[0].get(ns + "isolatedProcess") not in {None, "false"}
            or bootstrap[0].get(ns + "exported") != "false" or bootstrap[0].get(ns + "process") != ":mesh_bootstrap"
            or bootstrap[0].get(ns + "isolatedProcess") not in {None, "false"}):
        raise ValueError("Installed manifest lacks the ordinary app-owned service authority")


def verify_stage(directory):
    from android_qualification import source
    identity = source()
    staged = json.loads((directory / "staging.json").read_text())
    if (directory.resolve().is_relative_to(ROOT) or any(staged.get(key) != value for key, value in identity.items())
            or set(staged.get("application_files", {})) != set(APPLICATION_FILES)
            or set(staged.get("publications", {})) != set(PUBLICATIONS)):
        raise ValueError("Android staging is not exact-source and outside checkout")
    for name, expected in staged["application_files"].items():
        if digest(directory / name) != expected or digest(ROOT / "examples/android-independent-consumer" / name) != expected:
            raise ValueError("Independent Android application inputs changed")
    for name, expected in staged["publications"].items():
        if any(digest(path) != expected for path in (directory / name, OUTPUT / name, PUBLICATIONS[name])):
            raise ValueError("Android consumer did not use the exact published artifacts")
    verify_publications(OUTPUT)
    for original, name in (("app/build/outputs/apk/debug/app-debug.apk", "consumer.apk"),
                           ("app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk", "consumer-test.apk")):
        shutil.copyfile(directory / original, OUTPUT / name)
    apk = OUTPUT / "consumer.apk"
    with zipfile.ZipFile(apk) as archive:
        verify_python_payload(archive)
        if not {"lib/x86_64/libpython3.13.so", "lib/x86_64/libchaquopy_java.so",
                "lib/x86_64/libjingle_peerconnection_so.so"} <= set(archive.namelist()):
            raise ValueError("Installed dependency graph omits Python or native WebRTC")
    from verify_android_webrtc import verify_android_webrtc
    verify_android_webrtc(apk)
    verify_manifest(ET.fromstring(subprocess.check_output(["apkanalyzer", "manifest", "print", str(apk)], timeout=60)))
    result = {"v": 1, "passed": True, **identity, "scope": SCOPE, "checks": dict(CHECKS),
              "application_files": staged["application_files"],
              "artifacts": {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in ARTIFACTS}}
    verify_record(result, identity, result["artifacts"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    report = verify_stage(args.stage)
    destination = ROOT / "dist/reports/android-independent-distribution.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
