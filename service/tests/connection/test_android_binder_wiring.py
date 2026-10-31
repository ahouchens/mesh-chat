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
    assert "MAX_FRAME_BYTES = 256 * 1024" in service
    assert '"core_exchange"' in service
    build = (PLUGIN / "build.gradle.kts").read_text(encoding="utf-8")
    assert "aidl = true" in build


def test_android_qualification_runs_the_instrumentation_suite():
    script = (ROOT / "scripts" / "test_android_core_api.sh").read_text(encoding="utf-8")
    assert ":tauri-plugin-mesh-runtime:connectedDebugAndroidTest" in script
    assert "MeshCoreApiServiceTest" in script
    qualification = (ROOT / "scripts" / "test_android_qualification.sh").read_text(encoding="utf-8")
    assert "bash scripts/test_android_core_api.sh" in qualification
    assert (PLUGIN / "src" / "androidTest" / "java" / "com" / "meshchat" / "runtime" /
            "MeshCoreApiServiceTest.kt").is_file()
