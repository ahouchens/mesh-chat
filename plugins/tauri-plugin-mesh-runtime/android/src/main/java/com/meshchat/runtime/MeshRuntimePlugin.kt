package com.meshchat.runtime

import android.Manifest
import android.app.Activity
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.webkit.WebView
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.Permission
import app.tauri.annotation.PermissionCallback
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

@InvokeArg
class InitializeArgs {
    var displayName: String? = null
}

@TauriPlugin(
    permissions = [
        Permission(strings = [Manifest.permission.POST_NOTIFICATIONS], alias = "postNotification"),
    ],
)
class MeshRuntimePlugin(private val activity: Activity) : Plugin(activity) {
    companion object {
        private const val TAG = "MeshChatRuntime"
        private const val MESSAGE_CHANNEL = "mesh_chat_messages_v1"
        private const val MENTION_CHANNEL = "mesh_chat_mentions_v1"
        private const val LAUNCH_PREFERENCES = "mesh-chat-launch-v1"
        private const val PENDING_INVITATION = "pending-invitation"
    }

    private val preferences by lazy {
        activity.getSharedPreferences("mesh-chat-vault", Context.MODE_PRIVATE)
    }
    private var multicastLock: WifiManager.MulticastLock? = null
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-python").apply { isDaemon = true }
    }
    private val notificationPump = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "mesh-chat-notifications").apply { isDaemon = true }
    }
    private val pumpQueued = AtomicBoolean(false)
    private val pumpStarted = AtomicBoolean(false)
    @Volatile private var runtimeInitialized = false
    @Volatile private var lifecycleRegistered = false

    @Synchronized
    private fun python() = if (Python.isStarted()) {
        Python.getInstance()
    } else {
        Python.start(AndroidPlatform(activity.applicationContext))
        Python.getInstance()
    }

    private fun vaultKey(): ByteArray {
        val alias = "mesh-chat-vault-key-v1"
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!keyStore.containsAlias(alias)) {
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            generator.generateKey()
        }
        val wrappingKey = keyStore.getKey(alias, null) as SecretKey
        val stored = preferences.getString("wrapped-key", null)
        if (stored != null) {
            val packed = Base64.decode(stored, Base64.NO_WRAP)
            require(packed.size > 12)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, wrappingKey, GCMParameterSpec(128, packed, 0, 12))
            return cipher.doFinal(packed, 12, packed.size - 12)
        }

        val raw = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey)
        val packed = cipher.iv + cipher.doFinal(raw)
        check(preferences.edit().putString("wrapped-key", Base64.encodeToString(packed, Base64.NO_WRAP)).commit())
        return raw
    }

    private fun bridge(function: String, requestJson: String? = null): String {
        val module = python().getModule("mesh_chat.mobile_bridge")
        return if (requestJson == null) {
            module.callAttr(function).toString()
        } else {
            module.callAttr(function, requestJson).toString()
        }
    }

    private fun internalCommand(command: String, payload: JSONObject = JSONObject()): JSONObject {
        val request = JSONObject().put("command", command).put("payload", payload)
        return JSONObject(bridge("command", request.toString()))
    }

    private fun resolve(invoke: Invoke, json: String) {
        val value = JSObject()
        value.put("json", json)
        invoke.resolve(value)
    }

    private fun reject(invoke: Invoke, operation: String, error: Throwable) {
        // Record only the failing stage and exception type. Messages from
        // upstream libraries can contain private paths or peer addresses.
        Log.e(TAG, "$operation failed (${error.javaClass.simpleName})")
        invoke.reject("mobile_runtime_unavailable")
    }

    private fun permissionState(): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return if (NotificationManagerCompat.from(activity).areNotificationsEnabled()) {
                "allowed"
            } else {
                "settings_required"
            }
        }
        if (
            ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED &&
            NotificationManagerCompat.from(activity).areNotificationsEnabled()
        ) return "allowed"
        if (!preferences.getBoolean("notification-permission-requested", false)) {
            return "not_requested"
        }
        return if (ActivityCompat.shouldShowRequestPermissionRationale(
                activity,
                Manifest.permission.POST_NOTIFICATIONS,
            )) "denied" else "settings_required"
    }

    private fun capability(): JSONObject = JSONObject()
        .put("supported", true)
        .put("platform", "android")
        .put("permission_state", permissionState())

    private fun successful(result: JSONObject): String = JSONObject()
        .put("ok", true)
        .put("result", result)
        .toString()

    private fun syncNativeState() {
        if (!runtimeInitialized) return
        try {
            internalCommand("native_notification_state", capability())
        } catch (error: Throwable) {
            Log.e(TAG, "notification state sync failed (${error.javaClass.simpleName})")
        }
    }

    private fun lifecycle(state: String, reason: String) {
        if (!runtimeInitialized) return
        pythonExecutor.execute {
            try {
                syncNativeState()
                internalCommand(
                    "mobile_lifecycle_transition",
                    JSONObject().put("state", state).put("reason", reason),
                )
            } catch (error: Throwable) {
                Log.e(TAG, "lifecycle sync failed (${error.javaClass.simpleName})")
            }
        }
    }

    override fun load(webView: WebView) {
        super.load(webView)
        if (lifecycleRegistered) return
        lifecycleRegistered = true
        activity.application.registerActivityLifecycleCallbacks(
            object : Application.ActivityLifecycleCallbacks {
                override fun onActivityCreated(value: Activity, state: Bundle?) = Unit
                override fun onActivityStarted(value: Activity) = Unit
                override fun onActivitySaveInstanceState(value: Activity, state: Bundle) = Unit
                override fun onActivityStopped(value: Activity) {
                    if (value === activity) lifecycle("suspended", "activity_stopped")
                }
                override fun onActivityDestroyed(value: Activity) = Unit
                override fun onActivityResumed(value: Activity) {
                    if (value === activity) lifecycle("foreground", "activity_resumed")
                }
                override fun onActivityPaused(value: Activity) {
                    if (value === activity) lifecycle("background", "activity_paused")
                }
            },
        )
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = activity.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannels(
            listOf(
                NotificationChannel(
                    MESSAGE_CHANNEL,
                    "Mesh Chat messages",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "Local message notifications while Mesh Chat can execute"
                },
                NotificationChannel(
                    MENTION_CHANNEL,
                    "Mesh Chat mentions",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "Local structured-mention notifications"
                },
            ),
        )
    }

    private fun validPlainText(value: String, maximum: Int): Boolean =
        value.codePointCount(0, value.length) <= maximum && value.codePoints().allMatch { codePoint ->
            Character.getType(codePoint) != Character.CONTROL.toInt() &&
                Character.getType(codePoint) != Character.FORMAT.toInt() &&
                Character.getType(codePoint) != Character.SURROGATE.toInt()
        }

    private fun acknowledge(notificationId: String, outcome: String) {
        internalCommand(
            "acknowledge_native_notification",
            JSONObject().put("notification_id", notificationId).put("outcome", outcome),
        )
    }

    private fun displayNativeWork(item: JSONObject) {
        val notificationId = item.optString("notification_id")
        val groupingKey = item.optString("grouping_key")
        val category = item.optString("category")
        val title = item.optString("title")
        val body = item.optString("body")
        if (
            !notificationId.matches(Regex("^[0-9a-f]{64}$")) ||
            !groupingKey.matches(Regex("^[0-9a-f]{32}$")) ||
            category !in setOf(
                "mention",
                "thread_reply",
                "direct_message",
                "group_message",
                "announcement_message",
                "channel_message",
            ) ||
            !validPlainText(title, 80) ||
            !validPlainText(body, 160) ||
            item.toString().toByteArray(Charsets.UTF_8).size > 1024
        ) {
            if (notificationId.matches(Regex("^[0-9a-f]{64}$"))) {
                acknowledge(notificationId, "denied")
            }
            return
        }
        if (permissionState() != "allowed") {
            syncNativeState()
            acknowledge(notificationId, "denied")
            return
        }
        val route = Uri.parse("meshchat://notification/$notificationId")
        val intent = Intent(activity, activity.javaClass)
            .setAction(Intent.ACTION_VIEW)
            .setData(route)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val requestCode = notificationId.take(8).toLong(16).toInt()
        val pending = PendingIntent.getActivity(
            activity,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val channel = if (category == "mention") MENTION_CHANNEL else MESSAGE_CHANNEL
        val notification = NotificationCompat.Builder(activity, channel)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setGroup(groupingKey)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        try {
            NotificationManagerCompat.from(activity).notify(notificationId, 0, notification)
            acknowledge(notificationId, "accepted")
        } catch (error: SecurityException) {
            syncNativeState()
            acknowledge(notificationId, "denied")
        } catch (error: Throwable) {
            Log.e(TAG, "native notification failed (${error.javaClass.simpleName})")
            acknowledge(notificationId, "retry")
        }
    }

    private fun drainNativeNotifications() {
        if (!runtimeInitialized || permissionState() != "allowed") return
        val response = internalCommand(
            "drain_native_notification_work",
            JSONObject().put("limit", 16),
        )
        if (!response.optBoolean("ok")) return
        val items = response.optJSONObject("result")?.optJSONArray("items") ?: return
        for (index in 0 until minOf(items.length(), 16)) {
            items.optJSONObject(index)?.let(::displayNativeWork)
        }
    }

    private fun startNotificationPump() {
        if (!pumpStarted.compareAndSet(false, true)) return
        notificationPump.scheduleWithFixedDelay(
            {
                if (!runtimeInitialized || !pumpQueued.compareAndSet(false, true)) return@scheduleWithFixedDelay
                pythonExecutor.execute {
                    try {
                        drainNativeNotifications()
                    } catch (error: Throwable) {
                        Log.e(TAG, "notification pump failed (${error.javaClass.simpleName})")
                    } finally {
                        pumpQueued.set(false)
                    }
                }
            },
            0,
            750,
            TimeUnit.MILLISECONDS,
        )
    }

    @Command
    fun initialize(invoke: Invoke) {
        val args = invoke.parseArgs(InitializeArgs::class.java)
        pythonExecutor.execute {
            try {
                val profileDir = activity.filesDir.resolve("mesh-chat/profile-v1")
                check(profileDir.mkdirs() || profileDir.isDirectory)
                val request = JSONObject()
                    .put("profile_dir", profileDir.canonicalPath)
                    .put("vault_key", Base64.encodeToString(vaultKey(), Base64.NO_WRAP))
                    .put("display_name", args.displayName)
                    .put("platform", "android")
                val wifi = activity.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                multicastLock = multicastLock ?: wifi.createMulticastLock("mesh-chat-reticulum").apply {
                    setReferenceCounted(false)
                    acquire()
                }
                createNotificationChannels()
                val initialized = bridge("initialize", request.toString())
                runtimeInitialized = true
                syncNativeState()
                internalCommand(
                    "mobile_lifecycle_transition",
                    JSONObject().put("state", "foreground").put("reason", "runtime_initialized"),
                )
                startNotificationPump()
                resolve(invoke, initialized)
            } catch (error: Throwable) {
                reject(invoke, "initialize", error)
            }
        }
    }

    @Command
    fun command(invoke: Invoke) {
        // Preserve the exact nested JSON object emitted by Rust. Jackson cannot
        // populate org.json.JSONObject/JSObject fields and silently produced an
        // empty payload, which made every parameterized mobile command fail
        // validation even though its scanned or pasted invitation was valid.
        val requestJson = invoke.getRawArgs()
        pythonExecutor.execute {
            try {
                resolve(invoke, bridge("command", requestJson))
            } catch (error: Throwable) {
                reject(invoke, "command", error)
            }
        }
    }

    @Command
    fun drainEvents(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                resolve(invoke, bridge("drain_events"))
            } catch (error: Throwable) {
                reject(invoke, "drain_events", error)
            }
        }
    }

    @Command
    fun takePendingInvitation(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                val launch = activity.getSharedPreferences(LAUNCH_PREFERENCES, Context.MODE_PRIVATE)
                val value = launch.getString(PENDING_INVITATION, null)
                if (value != null && !launch.edit().remove(PENDING_INVITATION).commit()) {
                    throw IllegalStateException("pending invitation could not be cleared")
                }
                resolve(
                    invoke,
                    JSONObject().put("ok", true).put("result", value ?: JSONObject.NULL).toString(),
                )
            } catch (error: Throwable) {
                reject(invoke, "take_pending_invitation", error)
            }
        }
    }

    @Command
    fun notificationCapability(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                syncNativeState()
                resolve(invoke, successful(capability()))
            } catch (error: Throwable) {
                reject(invoke, "notification_capability", error)
            }
        }
    }

    @Command
    fun requestNotificationPermission(invoke: Invoke) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || permissionState() == "allowed") {
            pythonExecutor.execute {
                syncNativeState()
                resolve(invoke, successful(capability()))
            }
            return
        }
        if (preferences.getBoolean("notification-permission-requested", false)) {
            pythonExecutor.execute {
                syncNativeState()
                resolve(invoke, successful(capability()))
            }
            return
        }
        check(preferences.edit().putBoolean("notification-permission-requested", true).commit())
        requestPermissionForAlias("postNotification", invoke, "notificationPermissionResult")
    }

    @PermissionCallback
    private fun notificationPermissionResult(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                syncNativeState()
                resolve(invoke, successful(capability()))
            } catch (error: Throwable) {
                reject(invoke, "request_notification_permission", error)
            }
        }
    }

    @Command
    fun openNotificationSettings(invoke: Invoke) {
        try {
            val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            resolve(invoke, successful(capability()))
        } catch (error: Throwable) {
            reject(invoke, "open_notification_settings", error)
        }
    }

    @Command
    fun shutdown(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                val result = bridge("shutdown")
                runtimeInitialized = false
                multicastLock?.let { if (it.isHeld) it.release() }
                multicastLock = null
                resolve(invoke, result)
            } catch (error: Throwable) {
                reject(invoke, "shutdown", error)
            }
        }
    }
}
