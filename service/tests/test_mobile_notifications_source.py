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
        "native_ringing_calls",
        "mobile_lifecycle_transition",
        "drain_native_notification_work",
        "acknowledge_native_notification",
    ):
        assert f'| "{command}"' not in renderer_allowlist

    api = (ROOT / "src" / "api.ts").read_text(encoding="utf-8")
    assert "notification\\/([0-9a-f]{64})" in api
    assert "onOpenUrl" in api


def test_android_launch_ingress_is_bounded_durable_and_single_task_safe() -> None:
    android_root = ROOT / "src-tauri" / "gen" / "android" / "app" / "src"
    activity = (
        android_root / "main" / "java" / "com" / "meshchat" / "mobile" / "MainActivity.kt"
    ).read_text(encoding="utf-8")
    pending = (
        android_root
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "PendingInvitation.kt"
    ).read_text(encoding="utf-8")
    plugin = ANDROID_PLUGIN.read_text(encoding="utf-8")
    workspace_protocol = (
        ROOT / "service" / "src" / "mesh_chat" / "workspace_protocol.py"
    ).read_text(encoding="utf-8")
    manifest = (android_root / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert 'android:launchMode="singleTask"' in manifest
    assert 'android:mimeType="*/*"' in manifest
    assert 'android:pathPattern=".*\\\\.meshchat"' in manifest
    assert 'android:pathPattern=".*\\\\.meshchat-invite"' in manifest
    assert 'android.intent.action.SEND"' not in manifest
    assert "override fun onCreate" in activity
    assert "override fun onNewIntent" in activity
    assert "PendingInvitation.capture" in activity
    assert "InvitationDocumentHost" in activity
    assert "PendingInvitation.readDocument" in activity
    assert "Intent(Intent.ACTION_MAIN)" in activity
    assert 'MAX_STANDARD_BYTES = 32 * 1024' in pending
    assert 'MAX_DEVICE_LINK_BYTES = 700 * 1024' in pending
    assert 'MAX_DIRECT_BYTES = 2 * 1024 * 1024' in pending
    assert 'MAX_DOCUMENT_BYTES = MAX_DIRECT_BYTES' in pending
    assert 'compact.startsWith("mesh-direct:") -> "mesh-direct:" to MAX_DIRECT_BYTES' in pending
    assert 'document.optString("type") == "direct_connection"' in pending
    assert 'MAX_WORKSPACE_INVITE_DOCUMENT_BYTES = 256 * 1024' in pending
    assert 'MAX_DEVICE_LINK_DOCUMENT_BYTES = 320 * 1024' in pending
    assert 'document.optString("type") == "workspace_invite"' in pending
    assert 'document.optString("type") == "workspace_device_link_offer"' in pending
    assert "MAX_AUTHORITY_BOOTSTRAP_BYTES = 256 * 1024" in workspace_protocol
    assert "MAX_DEVICE_LINK_BYTES = 320 * 1024" in workspace_protocol
    assert 'uri.scheme != "meshchat"' in pending
    assert 'uri.scheme != "content"' in pending
    assert 'it.endsWith(".meshchat")' in pending
    assert 'it.endsWith(".meshchat-invite")' in pending
    assert 'it.endsWith(".json")' in pending
    assert "CodingErrorAction.REPORT" in pending
    assert "canonicalPath" not in pending
    assert "Intent.ACTION_OPEN_DOCUMENT" in plugin
    assert "Intent.CATEGORY_OPENABLE" in plugin
    assert 'type = "*/*"' in plugin
    assert "InvitationDocumentHost" in plugin
    assert "pickInvitationFile" in plugin
    picker_callback = plugin[
        plugin.index("private fun pickInvitationFileResult") : plugin.index(
            "fun notificationCapability"
        )
    ]
    assert picker_callback.index("pythonExecutor.execute") < picker_callback.index(
        "host.readInvitationDocument"
    )
    assert "takePendingInvitation" in plugin
    assert '.remove(PENDING_INVITATION).commit()' in plugin
    assert "take_pending_invitation" in rust
    assert "validated_invitation_value" in rust


def test_android_build_recreates_pending_invitation_from_canonical_template() -> None:
    template = (
        ROOT / "scripts" / "templates" / "android" / "PendingInvitation.kt"
    ).read_text(encoding="utf-8")
    generated = (
        ROOT
        / "src-tauri"
        / "gen"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "meshchat"
        / "mobile"
        / "PendingInvitation.kt"
    ).read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_android.py").read_text(
        encoding="utf-8"
    )

    assert generated == template
    assert 'activity.with_name("PendingInvitation.kt")' in build_script
    assert "PENDING_INVITATION_TEMPLATE.read_text" in build_script


def test_android_native_accepts_every_live_message_notification_family() -> None:
    source = ANDROID_PLUGIN.read_text(encoding="utf-8")
    for category in (
        "direct_message",
        "group_message",
        "announcement_message",
        "channel_message",
        "thread_reply",
        "mention",
    ):
        assert f'"{category}"' in source
