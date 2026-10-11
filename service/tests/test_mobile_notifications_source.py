from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANDROID_PLUGIN = (
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
    / "MeshRuntimePlugin.kt"
)
IOS_PLUGIN = (
    ROOT
    / "plugins"
    / "tauri-plugin-mesh-runtime"
    / "ios"
    / "Sources"
    / "MeshRuntimePlugin"
    / "MeshRuntimePlugin.swift"
)


def test_android_notification_permission_channels_and_runtime_path_are_frozen() -> None:
    source = ANDROID_PLUGIN.read_text(encoding="utf-8")
    manifest = (
        ROOT / "src-tauri" / "gen" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    plugin_manifest = (
        ROOT
        / "plugins"
        / "tauri-plugin-mesh-runtime"
        / "android"
        / "src"
        / "main"
        / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")

    assert "android.permission.POST_NOTIFICATIONS" in manifest
    assert "android.permission.POST_NOTIFICATIONS" in plugin_manifest
    assert 'android:allowBackup="false"' in plugin_manifest
    assert 'android:usesCleartextTraffic="${usesCleartextTraffic}"' in manifest
    gradle = (ROOT / "src-tauri" / "gen" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'manifestPlaceholders["usesCleartextTraffic"] = "false"' in gradle
    assert 'MESSAGE_CHANNEL = "mesh_chat_messages_v1"' in source
    assert 'MENTION_CHANNEL = "mesh_chat_mentions_v1"' in source
    assert "NotificationManager.IMPORTANCE_DEFAULT" in source
    assert "NotificationManager.IMPORTANCE_HIGH" in source
    assert 'requestPermissionForAlias("postNotification"' in source
    assert 'getBoolean("notification-permission-requested", false)' in source
    assert 'putBoolean("notification-permission-requested", true)' in source
    assert "Settings.ACTION_APP_NOTIFICATION_SETTINGS" in source
    assert '"drain_native_notification_work"' in source
    assert 'meshchat://notification/$notificationId' in source
    assert 'notify(notificationId, 0, notification)' in source
    assert "item.toString().toByteArray(Charsets.UTF_8).size > 1024" in source
    assert "validPlainText(title, 80)" in source
    assert "validPlainText(body, 160)" in source
    assert "scheduleWithFixedDelay" in source
    assert "Firebase" not in source
    assert "FOREGROUND_SERVICE" not in manifest


def test_ios_boundary_uses_local_notifications_and_lifecycle_only() -> None:
    source = IOS_PLUGIN.read_text(encoding="utf-8")
    assert "UNUserNotificationCenter" in source
    assert "UNNotificationRequest" in source
    assert '"drain_native_notification_work"' in source
    assert "didEnterBackgroundNotification" in source
    assert "willEnterForegroundNotification" in source
    assert "didReceiveRemoteNotification" not in source
    assert "registerForRemoteNotifications" not in source


def test_renderer_cannot_invoke_native_notification_work_commands() -> None:
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    renderer_allowlist = rust[rust.index("fn allowed_renderer_command") : rust.index("#[cfg(desktop)]")]
    for command in (
        "native_notification_state",
        "mobile_lifecycle_transition",
        "drain_native_notification_work",
        "acknowledge_native_notification",
    ):
        assert f'| "{command}"' not in renderer_allowlist

    api = (ROOT / "src" / "api.ts").read_text(encoding="utf-8")
    assert "notification\\/([0-9a-f]{64})" in api
    assert "onOpenUrl" in api
