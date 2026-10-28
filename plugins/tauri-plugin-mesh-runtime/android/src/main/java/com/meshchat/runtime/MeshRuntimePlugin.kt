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
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.webkit.WebView
import androidx.activity.result.ActivityResult
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowInsetsControllerCompat
import app.tauri.annotation.ActivityCallback
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

@InvokeArg
class ThemeArgs {
    var theme: String? = null
}

@InvokeArg
class DirectExchangeArgs {
    var json: String? = null
}

@InvokeArg
class BackgroundAvailabilityArgs {
    var enabled: Boolean? = null
}

@InvokeArg
class CallMediaArgs {
    var media: String? = null
}

/**
 * Result of opening and validating an invitation document in the host app.
 *
 * The runtime plugin owns the system picker while the app owns the invitation
 * parser. Keeping this interface value-only prevents content-provider paths or
 * URIs from crossing the native bridge into the renderer.
 */
data class InvitationDocumentResult(
    val value: String? = null,
    val error: String? = null,
)

interface InvitationDocumentHost {
    fun readInvitationDocument(uri: Uri): InvitationDocumentResult
}

@TauriPlugin(
    permissions = [
        Permission(strings = [Manifest.permission.POST_NOTIFICATIONS], alias = "postNotification"),
        Permission(
            strings = [Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA],
            alias = "media",
        ),
        Permission(strings = [Manifest.permission.RECORD_AUDIO], alias = "audio"),
    ],
)
class MeshRuntimePlugin(private val activity: Activity) : Plugin(activity) {
    // Brief user-mediated sharing is a background transition, not immediate
    // socket loss. This grants no background execution guarantee: process death
    // and the existing native ownership checks still require fresh details.
    private val sharingHandler = Handler(Looper.getMainLooper())
    private val suspendAfterSharing = Runnable {
        if (!availabilityActive()) {
            lifecycle("suspended", "background_grace_expired")
        }
    }

    private fun availabilityActive(): Boolean =
        MeshAvailabilityService.isRunning() || MeshAvailabilityService.isEnabled(activity)
    @Command
    fun buildInfo(invoke: Invoke) {
        val info = activity.packageManager.getPackageInfo(activity.packageName, 0)
        val result = JSONObject()
            .put("installed_version", info.versionName)
            .put("android_version_code", if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong())
            .put("os_version", Build.VERSION.RELEASE)
        val response = JSObject()
        response.put("json", JSONObject().put("ok", true).put("result", result).toString())
        invoke.resolve(response)
    }
    init { BootstrapClient.configure(activity.applicationContext) }
    companion object {
        private const val TAG = "MeshChatRuntime"
        private const val MESSAGE_CHANNEL = "mesh_chat_messages_v1"
        private const val MENTION_CHANNEL = "mesh_chat_mentions_v1"
        private const val LAUNCH_PREFERENCES = "mesh-chat-launch-v1"
        private const val PENDING_INVITATION = "pending-invitation"
        private const val UI_THEME = "ui-theme"
    }

    private val preferences by lazy {
        activity.getSharedPreferences("mesh-chat-vault", Context.MODE_PRIVATE)
    }
    private var multicastLock: WifiManager.MulticastLock? = null
    private var audioFocusRequest: AudioFocusRequest? = null
    private var legacyAudioFocusListener: AudioManager.OnAudioFocusChangeListener? = null
    private var previousAudioMode: Int = AudioManager.MODE_NORMAL
    private var callAudioActive = false
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-python").apply { isDaemon = true }
    }
    // Separate from commands which may be waiting on a private native result.
    private val directExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-direct-private").apply { isDaemon = true }
    }

    @Command
    fun directExchange(invoke: Invoke) {
        val request = invoke.parseArgs(DirectExchangeArgs::class.java).json
        if (request == null || request.toByteArray(Charsets.UTF_8).size > 65536) {
            invoke.reject("invalid_request")
            return
        }
        directExecutor.execute {
            try { resolve(invoke, bridge("direct_exchange", request)) }
            catch (error: Throwable) { reject(invoke, "direct exchange", error) }
        }
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
        BackgroundRuntime.onUiLifecycle(state)
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

    private fun applyTheme(theme: String) {
        val light = theme == "light"
        val background = Color.parseColor(if (light) "#F7F4EB" else "#0F1714")
        val lightNavigationIconsSupported = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
        val navigation = Color.parseColor(if (light && lightNavigationIconsSupported) "#F8F8F3" else "#141D19")
        val nativeTheme = activity.resources.getIdentifier(
            if (light) "Theme.mesh_chat.Light" else "Theme.mesh_chat",
            "style",
            activity.packageName,
        )
        if (nativeTheme != 0) activity.setTheme(nativeTheme)
        activity.window.statusBarColor = background
        activity.window.navigationBarColor = navigation
        activity.window.decorView.setBackgroundColor(background)
        WindowInsetsControllerCompat(activity.window, activity.window.decorView).apply {
            isAppearanceLightStatusBars = light
            isAppearanceLightNavigationBars = light && lightNavigationIconsSupported
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            activity.window.navigationBarDividerColor = navigation
        }
    }

    override fun load(webView: WebView) {
        super.load(webView)
        BackgroundRuntime.onUiLifecycle("foreground")
        applyTheme(preferences.getString(UI_THEME, "dark") ?: "dark")
        if (lifecycleRegistered) return
        lifecycleRegistered = true
        activity.application.registerActivityLifecycleCallbacks(
            object : Application.ActivityLifecycleCallbacks {
                override fun onActivityCreated(value: Activity, state: Bundle?) = Unit
                override fun onActivityStarted(value: Activity) = Unit
                override fun onActivitySaveInstanceState(value: Activity, state: Bundle) = Unit
                override fun onActivityStopped(value: Activity) {
                    if (value === activity) {
                        sharingHandler.removeCallbacks(suspendAfterSharing)
                        if (availabilityActive()) {
                            lifecycle("background_available", "activity_stopped")
                        } else {
                            sharingHandler.postDelayed(suspendAfterSharing, 45_000)
                        }
                    }
                }
                override fun onActivityDestroyed(value: Activity) {
                    if (value === activity) {
                        sharingHandler.removeCallbacks(suspendAfterSharing)
                        if (availabilityActive()) {
                            lifecycle("background_available", "activity_destroyed")
                        } else {
                            lifecycle("suspended", "activity_destroyed")
                        }
                    }
                }
                override fun onActivityResumed(value: Activity) {
                    if (value === activity) {
                        sharingHandler.removeCallbacks(suspendAfterSharing)
                        lifecycle("foreground", "activity_resumed")
                        if (runtimeInitialized) BackgroundRuntime.restoreIfEnabled(activity)
                    }
                }
                override fun onActivityPaused(value: Activity) {
                    if (value === activity) lifecycle("background", "activity_paused")
                }
            },
        )
    }

    @Command
    fun setTheme(invoke: Invoke) {
        val theme = invoke.parseArgs(ThemeArgs::class.java).theme
        if (theme != "dark" && theme != "light") {
            invoke.reject("invalid_theme")
            return
        }
        activity.runOnUiThread {
            try {
                applyTheme(theme)
                preferences.edit().putString(UI_THEME, theme).apply()
                resolve(invoke, successful(JSONObject().put("theme", theme)))
            } catch (error: Throwable) {
                reject(invoke, "set_theme", error)
            }
        }
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
                NativeWebRtcBridge.attach(activity.applicationContext)
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
                runtimeInitialized = JSONObject(initialized).optBoolean("ok", false)
                if (!runtimeInitialized) {
                    resolve(invoke, initialized)
                    return@execute
                }
                BackgroundRuntime.applyDefault(activity)
                syncNativeState()
                internalCommand(
                    "mobile_lifecycle_transition",
                    JSONObject().put("state", "foreground").put("reason", "runtime_initialized"),
                )
                startNotificationPump()
                activity.runOnUiThread { BackgroundRuntime.restoreIfEnabled(activity) }
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
    fun pickInvitationFile(invoke: Invoke) {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivityForResult(invoke, intent, "pickInvitationFileResult")
        } catch (_: Exception) {
            resolve(
                invoke,
                JSONObject()
                    .put("ok", false)
                    .put("error", JSONObject().put("code", "invitation_file_unavailable"))
                    .toString(),
            )
        }
    }

    @ActivityCallback
    private fun pickInvitationFileResult(invoke: Invoke, result: ActivityResult) {
        if (result.resultCode != Activity.RESULT_OK) {
            resolve(
                invoke,
                JSONObject().put("ok", true).put("result", JSONObject.NULL).toString(),
            )
            return
        }
        val uri = result.data?.data
        val host = activity as? InvitationDocumentHost
        if (uri == null || host == null) {
            resolve(
                invoke,
                JSONObject()
                    .put("ok", false)
                    .put("error", JSONObject().put("code", "invitation_file_unavailable"))
                    .toString(),
            )
            return
        }
        pythonExecutor.execute {
            val document = try {
                host.readInvitationDocument(uri)
            } catch (_: Throwable) {
                InvitationDocumentResult(error = "invitation_file_unavailable")
            }
            if (document.value != null) {
                resolve(
                    invoke,
                    JSONObject().put("ok", true).put("result", document.value).toString(),
                )
                return@execute
            }
            resolve(
                invoke,
                JSONObject()
                    .put("ok", false)
                    .put(
                        "error",
                        JSONObject().put("code", document.error ?: "invitation_file_invalid"),
                    )
                    .toString(),
            )
        }
    }

    private fun restoreAvailabilityAfterPermission() {
        activity.runOnUiThread {
            if (runtimeInitialized) BackgroundRuntime.restoreIfEnabled(activity)
        }
    }

    @Command
    fun notificationCapability(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                syncNativeState()
                restoreAvailabilityAfterPermission()
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
                restoreAvailabilityAfterPermission()
                resolve(invoke, successful(capability()))
            }
            return
        }
        if (preferences.getBoolean("notification-permission-requested", false)) {
            pythonExecutor.execute {
                syncNativeState()
                restoreAvailabilityAfterPermission()
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
                restoreAvailabilityAfterPermission()
                resolve(invoke, successful(capability()))
            } catch (error: Throwable) {
                reject(invoke, "request_notification_permission", error)
            }
        }
    }

    @Command
    fun requestMediaPermission(invoke: Invoke) {
        val media = invoke.parseArgs(CallMediaArgs::class.java).media
        if (media != "audio" && media != "video") {
            reject(invoke, "request_media_permission", IllegalArgumentException("invalid_media"))
            return
        }
        val audio = ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        val camera = ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        if (audio && (media == "audio" || camera)) {
            resolve(invoke, successful(JSONObject().put("audio", audio).put("camera", camera)))
            return
        }
        try {
            requestPermissionForAlias(if (media == "video") "media" else "audio", invoke, "mediaPermissionResult")
        } catch (error: Throwable) {
            reject(invoke, "request_media_permission", error)
        }
    }

    @PermissionCallback
    private fun mediaPermissionResult(invoke: Invoke) {
        val audio = ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        val camera = ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        resolve(invoke, successful(JSONObject().put("audio", audio).put("camera", camera)))
    }

    @Command
    fun beginCallAudio(invoke: Invoke) {
        val media = invoke.parseArgs(CallMediaArgs::class.java).media
        if (media != "audio" && media != "video") {
            reject(invoke, "begin_call_audio", IllegalArgumentException("invalid_media"))
            return
        }
        val audioAllowed = ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        val cameraAllowed = ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        if (!audioAllowed || (media == "video" && !cameraAllowed)) {
            resolve(invoke, successful(JSONObject().put("granted", false)))
            return
        }
        try {
            val audio = activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (!callAudioActive) {
                previousAudioMode = audio.mode
                val granted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                        .setAudioAttributes(
                            AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build(),
                        )
                        .setOnAudioFocusChangeListener { }
                        .build()
                    val acquired = audio.requestAudioFocus(request) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
                    if (acquired) audioFocusRequest = request
                    acquired
                } else {
                    @Suppress("DEPRECATION")
                    val listener = AudioManager.OnAudioFocusChangeListener { }
                    val acquired = audio.requestAudioFocus(
                        listener,
                        AudioManager.STREAM_VOICE_CALL,
                        AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,
                    ) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
                    if (acquired) legacyAudioFocusListener = listener
                    acquired
                }
                if (!granted) {
                    resolve(invoke, successful(JSONObject().put("granted", false)))
                    return
                }
                audio.mode = AudioManager.MODE_IN_COMMUNICATION
                ContextCompat.startForegroundService(
                    activity,
                    Intent(activity, CallService::class.java)
                        .putExtra(CallService.EXTRA_MEDIA, media),
                )
                callAudioActive = true
                resolve(invoke, successful(JSONObject().put("granted", true)))
                return
            }
            ContextCompat.startForegroundService(
                activity,
                Intent(activity, CallService::class.java)
                    .putExtra(CallService.EXTRA_MEDIA, media),
            )
            resolve(invoke, successful(JSONObject().put("granted", true)))
        } catch (error: Throwable) {
            val audio = activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                audioFocusRequest?.let { audio.abandonAudioFocusRequest(it) }
            } else {
                @Suppress("DEPRECATION")
                legacyAudioFocusListener?.let { audio.abandonAudioFocus(it) }
            }
            audioFocusRequest = null
            legacyAudioFocusListener = null
            callAudioActive = false
            audio.mode = previousAudioMode
            reject(invoke, "begin_call_audio", error)
        }
    }

    @Command
    fun endCallAudio(invoke: Invoke) {
        try {
            if (!callAudioActive) {
                resolve(invoke, successful(JSONObject().put("active", false)))
                return
            }
            val audio = activity.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                audioFocusRequest?.let { audio.abandonAudioFocusRequest(it) }
            } else {
                @Suppress("DEPRECATION")
                audio.abandonAudioFocus(legacyAudioFocusListener)
            }
            audioFocusRequest = null
            legacyAudioFocusListener = null
            callAudioActive = false
            audio.mode = previousAudioMode
            activity.stopService(Intent(activity, CallService::class.java))
            resolve(invoke, successful(JSONObject().put("active", false)))
        } catch (error: Throwable) {
            reject(invoke, "end_call_audio", error)
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
    fun openBatterySettings(invoke: Invoke) {
        activity.runOnUiThread {
            try {
                // User-controlled exemption list; no silent change or automatic prompt.
                val battery = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                val fallback = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    .setData(Uri.parse("package:${activity.packageName}"))
                try {
                    activity.startActivity(battery)
                } catch (_: android.content.ActivityNotFoundException) {
                    activity.startActivity(fallback)
                }
                resolve(invoke, successful(JSONObject().put("opened", true)))
            } catch (error: Throwable) {
                reject(invoke, "open_battery_settings", error)
            }
        }
    }

    @Command
    fun setBackgroundAvailability(invoke: Invoke) {
        val enabled = invoke.parseArgs(BackgroundAvailabilityArgs::class.java).enabled
        if (enabled == null) {
            invoke.reject("invalid_background_availability")
            return
        }
        try {
            BackgroundRuntime.configure(activity.applicationContext)
            if (enabled && !BackgroundRuntime.notificationAllowed()) {
                // Preserve the actionable code through Rust's mobile_result;
                // a plugin rejection is flattened to availability_unavailable.
                resolve(invoke, JSONObject().put("ok", false)
                    .put("error", JSONObject().put("code", "notification_permission_required"))
                    .toString())
                return
            }
            if (enabled && !runtimeInitialized) {
                invoke.reject("background_runtime_locked")
                return
            }
            BackgroundRuntime.setPreference(activity, enabled)
            if (enabled) {
                BackgroundRuntime.start(activity)
            } else {
                BackgroundRuntime.stop(activity)
            }
            resolve(
                invoke,
                JSONObject()
                    .put("ok", true)
                    .put("result", JSONObject().put("enabled", enabled))
                    .toString(),
            )
        } catch (error: Throwable) {
            reject(invoke, "set_background_availability", error)
        }
    }

    @Command
    fun shutdown(invoke: Invoke) {
        runtimeInitialized = false
        BackgroundRuntime.stop(activity, preservePreference = true)
        NativeWebRtcBridge.closeAll()
        pythonExecutor.execute {
            try {
                val result = bridge("shutdown")
                runtimeInitialized = false
                BackgroundRuntime.onRuntimeShutdown()
                multicastLock?.let { if (it.isHeld) it.release() }
                multicastLock = null
                resolve(invoke, result)
            } catch (error: Throwable) {
                reject(invoke, "shutdown", error)
            }
        }
    }
}
