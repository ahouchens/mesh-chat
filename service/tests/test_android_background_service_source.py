from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANDROID = (
    ROOT
    / "plugins"
    / "tauri-plugin-mesh-runtime"
    / "android"
    / "src"
    / "main"
    / "java"
    / "com"
    / "meshchat"
    / "runtime"
)


def test_availability_service_is_declared_private_and_foreground() -> None:
    manifest = (
        ROOT
        / "plugins"
        / "tauri-plugin-mesh-runtime"
        / "android"
        / "src"
        / "main"
        / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    assert "android.permission.WAKE_LOCK" in manifest
    assert "android.permission.FOREGROUND_SERVICE_REMOTE_MESSAGING" in manifest
    assert 'android:name="com.meshchat.runtime.MeshAvailabilityService"' in manifest
    assert 'android:foregroundServiceType="remoteMessaging"' in manifest
    assert 'android:exported="false"' in manifest
    assert 'android:stopWithTask="false"' in manifest

    service = (ANDROID / "MeshAvailabilityService.kt").read_text(encoding="utf-8")
    assert "ServiceCompat.startForeground" in service
    assert "FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING" in service
    assert "PARTIAL_WAKE_LOCK" in service
    assert "WIFI_MODE_FULL_HIGH_PERF" in service
    assert "START_STICKY" in service
    assert "START_NOT_STICKY" in service
    assert "onTaskRemoved" in service

    runtime = (ANDROID / "BackgroundRuntime.kt").read_text(encoding="utf-8")
    assert 'mesh_chat_availability_v1' in runtime
    assert 'mesh-chat-vault-key-v1' in runtime
    assert '"mobile_lifecycle_transition"' in runtime
    assert '"background_available"' in runtime
    assert '"drain_native_notification_work"' in runtime
    assert "Firebase" not in runtime


def test_native_webrtc_host_is_pinned_and_isolated() -> None:
    gradle = (
        ROOT
        / "plugins"
        / "tauri-plugin-mesh-runtime"
        / "android"
        / "build.gradle.kts"
    ).read_text(encoding="utf-8")
    assert 'io.github.webrtc-sdk:android:150.7871.01' in gradle
    host = (ANDROID / "NativeWebRtcHost.kt").read_text(encoding="utf-8")
    assert "PeerConnectionFactory" in host
    assert 'DataChannel' in host
    assert '"mesh-reticulum"' in host
    assert '"meshchat-reconnect"' in host
    assert "native_webrtc_event" in host
    assert "media" not in host.lower() or "data-only" in host.lower()
    assert "CONTROL_LIMIT = 65_536" in host
    assert 'val limit = if (label == "mesh-reticulum")' in host
    assert "16_384" not in host
    assert 'specs.none { it.label == "mesh-reticulum" && it.binary }' in host
    assert "label !in session.expectedChannels" in host

    context = (ANDROID / "NativeWebRtcContext.kt").read_text(encoding="utf-8")
    assert "PeerConnection" not in context
    assert "PeerConnectionFactory" not in context
    bridge = (ANDROID / "NativeWebRtcBridge.kt").read_text(encoding="utf-8")
    assert "import org.webrtc" not in bridge
    assert "PeerConnection" not in bridge
    plugin = (ANDROID / "MeshRuntimePlugin.kt").read_text(encoding="utf-8")
    # Normal app startup must not reference the native WebRTC class at all.
    assert "NativeWebRtcHost" not in plugin
    assert "NativeWebRtcBridge.attach" in plugin
    proguard = (
        ROOT / "src-tauri" / "gen" / "android" / "app" / "proguard-rules.pro"
    ).read_text(encoding="utf-8")
    assert "-keep class com.meshchat.runtime.NativeWebRtcHost { *; }" in proguard
    assert "-keep class com.meshchat.runtime.NativeWebRtcBridge { *; }" in proguard


def test_plugin_does_not_suspend_when_availability_is_enabled() -> None:
    plugin = (ANDROID / "MeshRuntimePlugin.kt").read_text(encoding="utf-8")
    assert "availabilityActive()" in plugin
    assert "MeshAvailabilityService.isRunning()" in plugin
    assert "MeshAvailabilityService.isEnabled(activity)" in plugin
    assert 'lifecycle("background_available", "activity_stopped")' in plugin
    assert 'lifecycle("background_available", "activity_destroyed")' in plugin
    assert "fun setBackgroundAvailability(invoke: Invoke)" in plugin


def test_native_command_and_renderer_command_are_wired() -> None:
    mobile = (
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "src" / "mobile.rs"
    ).read_text(encoding="utf-8")
    models = (
        ROOT / "plugins" / "tauri-plugin-mesh-runtime" / "src" / "models.rs"
    ).read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    api = (ROOT / "src" / "api.ts").read_text(encoding="utf-8")
    assert "set_background_availability" in mobile
    assert "BackgroundAvailabilityRequest" in models
    assert "set_background_availability" in rust
    assert 'invoke<{ enabled: boolean }>("set_background_availability"' in api
    assert "open_battery_settings" in mobile
    assert "open_battery_settings" in rust
    assert 'invoke<{ opened: boolean }>("open_battery_settings")' in api
    plugin = (ANDROID / "MeshRuntimePlugin.kt").read_text(encoding="utf-8")
    assert "ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS" in plugin
    assert "ACTION_APPLICATION_DETAILS_SETTINGS" in plugin
