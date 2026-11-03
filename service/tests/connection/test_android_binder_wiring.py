"""Narrow packaging guards for the Android Binder endpoint.

Compilation and Binder behaviour are proven by the plugin's instrumentation
suite in the Android qualification job; these checks keep the security-relevant
wiring from disappearing.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "android"


def test_the_endpoint_is_exported_only_behind_a_signature_permission():
    manifest = (PLUGIN / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:protectionLevel="signature"' in manifest
    assert "com.meshchat.runtime.permission.CORE_API" in manifest
    service = manifest[manifest.index("MeshCoreApiService"):]
    assert 'android:exported="true"' in service[:400]
    assert 'android:permission="com.meshchat.runtime.permission.CORE_API"' in service[:400]


def test_the_interface_and_caller_derivation_stay_bounded():
    aidl = (PLUGIN / "src" / "main" / "aidl" / "com" / "meshchat" / "runtime" /
            "IMeshCoreApi.aidl").read_text(encoding="utf-8")
    assert "byte[] exchange(in byte[] frame);" in aidl
    service = (PLUGIN / "src" / "main" / "java" / "com" / "meshchat" / "runtime" /
               "MeshCoreApiService.kt").read_text(encoding="utf-8")
    assert "Binder.getCallingUid()" in service
    assert "checkCallingPermission(PERMISSION)" in service
    assert "Process.myUid()" in service
    dispatch = (PLUGIN / "src/main/java/com/meshchat/runtime/CoreDispatch.kt").read_text(encoding="utf-8")
    assert "MAX_FRAME_BYTES = 256 * 1024" in dispatch
    assert service.count("Binder.getCallingUid()") == 1
    assert "CoreCaller.fromUid(uid, hostUid, name)" in service
    assert '"core_exchange"' in service
    build = (PLUGIN / "build.gradle.kts").read_text(encoding="utf-8")
    assert "aidl = true" in build


def test_android_qualification_runs_the_instrumentation_suite():
    path = ROOT / "scripts" / "test_android_core_api.sh"
    assert path.read_bytes().startswith(b"#!/usr/bin/env bash")  # no BOM before the shebang
    script = path.read_text(encoding="utf-8")
    assert ":tauri-plugin-mesh-runtime:assembleDebugAndroidTest" in script
    assert "testDebugUnitTest" in script
    assert "prepare --suite core_api" in script
    assert "androidx.test.runner.AndroidJUnitRunner" in script
    qualification = (ROOT / "scripts" / "test_android_qualification.sh").read_text(encoding="utf-8")
    assert "bash scripts/test_android_core_api.sh" in qualification
    assert (PLUGIN / "src" / "androidTest" / "java" / "com" / "meshchat" / "runtime" /
            "MeshCoreApiServiceTest.kt").is_file()


def test_the_kotlin_client_wraps_the_same_contract():
    client = (PLUGIN / "src" / "main" / "java" / "com" / "meshchat" / "runtime" / "core" /
              "CoreClient.kt").read_text(encoding="utf-8")
    for operation in ("peer.pairing_accept", "peer.pairing_create", "runtime.stop",
                      "message.enqueue", "events.ack"):
        assert operation in client
    assert (PLUGIN / "src" / "test" / "java" / "com" / "meshchat" / "runtime" / "core" /
            "CoreClientTest.kt").is_file()


def test_binder_rebinding_cannot_create_a_new_dispatcher_for_a_wedged_host():
    service = (PLUGIN / "src/main/java/com/meshchat/runtime/MeshCoreApiService.kt").read_text()
    # The instrumentation detach/reattach check exercises this service; this
    # wiring guard also prevents reconnects from bypassing process-wide admission.
    assert service.count("CoreDispatch(") == 1
    assert "CoreDispatch(" in service.split("companion object {", 1)[1]
    assert "dispatcher.close()" not in service
