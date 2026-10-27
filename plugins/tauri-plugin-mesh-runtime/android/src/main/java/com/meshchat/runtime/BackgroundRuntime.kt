package com.meshchat.runtime

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.security.KeyStore
import java.security.SecureRandom
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Process-scoped runtime pieces needed by the availability service.
 *
 * This deliberately uses the application context. The Activity-scoped
 * MeshRuntimePlugin keeps the foreground UI, permission prompts, media
 * bridge, and call audio. Both call the same embedded CPython module, whose
 * service is process-global and idempotent.
 */
object BackgroundRuntime {
    private const val TAG = "MeshChatBackground"
    private const val MESSAGE_CHANNEL = "mesh_chat_messages_v1"
    private const val MENTION_CHANNEL = "mesh_chat_mentions_v1"
    private const val INCOMING_CALL_CHANNEL = "mesh_chat_incoming_calls_v1"
    private const val INCOMING_CALL_NOTIFICATION_ID = 7003
    private const val AVAILABILITY_CHANNEL = "mesh_chat_availability_v1"
    private const val PREFERENCES = "mesh-chat-vault"
    private const val AVAILABILITY_KEY = "background-availability-enabled"
    private const val DEFAULT_APPLIED_KEY = "background-availability-default-v2"
    private const val PREFERENCE_KEY = "background-availability-preference-v2"

    @Volatile private var configured = false
    @Volatile private var runtimeInitialized = false
    @Volatile private var nativeWebRtcReady = false
    @Volatile private var availabilityFailure: String? = null
    @Volatile private var uiForeground = false
    @Volatile private var startRequestedAt = 0L
    @Volatile private var restorations = 0
    private lateinit var appContext: Context
    private val preferences by lazy {
        appContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
    }
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-background-python").apply { isDaemon = true }
    }
    private var notificationPump: java.util.concurrent.ScheduledExecutorService? = null
    private val pumpQueued = AtomicBoolean(false)
    private val pumpStarted = AtomicBoolean(false)
    private val shownIncomingCalls = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()
    @Volatile private var multicastLock: WifiManager.MulticastLock? = null

    fun configure(context: Context) {
        if (configured) return
        synchronized(this) {
            if (configured) return
            appContext = context.applicationContext
            configured = true
        }
    }

    fun isEnabled(context: Context): Boolean {
        configure(context)
        return preferences.getBoolean(AVAILABILITY_KEY, false)
    }

    /** Apply the new default once, after the person unlocks the app. */
    @Synchronized
    fun applyDefault(context: Context) {
        configure(context)
        val enabled = if (preferences.getBoolean(DEFAULT_APPLIED_KEY, false)) {
            preferences.getBoolean(PREFERENCE_KEY, true)
        } else true
        preferences.edit().putBoolean(AVAILABILITY_KEY, enabled)
            .putBoolean(PREFERENCE_KEY, enabled).putBoolean(DEFAULT_APPLIED_KEY, true).apply()
    }

    /** An explicit settings/notification Stop choice survives later unlocks. */
    fun setPreference(context: Context, enabled: Boolean) {
        configure(context)
        preferences.edit().putBoolean(PREFERENCE_KEY, enabled)
            .putBoolean(AVAILABILITY_KEY, enabled).putBoolean(DEFAULT_APPLIED_KEY, true).apply()
    }

    fun setEnabled(context: Context, enabled: Boolean) {
        configure(context)
        preferences.edit().putBoolean(AVAILABILITY_KEY, enabled).apply()
    }

    @Synchronized
    fun start(context: Context) {
        configure(context)
        ensureNotificationChannels()
        check(notificationAllowed()) { "notification_permission_required" }
        availabilityFailure = null
        setEnabled(context, true)
        if (MeshAvailabilityService.isRunning() || startPending()) return
        startRequestedAt = SystemClock.elapsedRealtime()
        try {
            ContextCompat.startForegroundService(
                context,
                Intent(context, MeshAvailabilityService::class.java).setAction(MeshAvailabilityService.ACTION_START),
            )
        } catch (error: Throwable) {
            setEnabled(context, false)
            availabilityFailed("foreground_start_denied")
            throw error
        }
    }

    /** Restore an existing opt-in only after the unlocked UI returns. */
    @Synchronized
    fun restoreIfEnabled(context: Context) {
        configure(context)
        if (!uiForeground || !preferences.getBoolean(PREFERENCE_KEY, true) || !notificationAllowed() || MeshAvailabilityService.isRunning() || startPending()) return
        try {
            start(context)
            restorations++
        } catch (error: Throwable) {
            Log.e(TAG, "availability restore failed (${error.javaClass.simpleName})")
            availabilityFailed(if (!notificationAllowed()) "notification_permission_required" else "foreground_start_denied")
        }
    }

    private fun startPending(): Boolean = startRequestedAt != 0L &&
        SystemClock.elapsedRealtime() - startRequestedAt < 15_000

    fun onServiceStarted() { startRequestedAt = 0L }

    fun onServiceStopped() { startRequestedAt = 0L }

    @Synchronized
    fun stop(context: Context) {
        configure(context)
        startRequestedAt = 0L
        setEnabled(context, false)
        NativeWebRtcBridge.closeAll()
        context.stopService(Intent(context, MeshAvailabilityService::class.java))
        execute { clearIncomingCallNotifications() }
    }

    fun initialize(): String {
        check(configured)
        nativeWebRtcReady = NativeWebRtcBridge.initialize(appContext)
        createNotificationChannels()
        acquireMulticast()
        if (runtimeInitialized) {
            startNotificationPump()
            try {
                internalCommand(
                    "mobile_lifecycle_transition",
                    JSONObject().put("state", availabilityLifecycle()).put("reason", "availability_service"),
                )
            } catch (error: Throwable) {
                Log.e(TAG, "lifecycle update failed (${error.javaClass.simpleName})")
            }
            return JSONObject().put("ok", true).toString()
        }
        val profileDir = appContext.filesDir.resolve("mesh-chat/profile-v1")
        check(profileDir.mkdirs() || profileDir.isDirectory)
        val request = JSONObject()
            .put("profile_dir", profileDir.canonicalPath)
            .put("vault_key", Base64.encodeToString(vaultKey(), Base64.NO_WRAP))
            .put("platform", "android")
        val initialized = bridge("initialize", request.toString())
        check(JSONObject(initialized).optBoolean("ok", false)) {
            "background runtime initialization was rejected"
        }
        runtimeInitialized = true
        syncNativeState()
        internalCommand(
            "mobile_lifecycle_transition",
            JSONObject().put("state", availabilityLifecycle()).put("reason", "availability_service"),
        )
        startNotificationPump()
        return initialized
    }

    fun onUiLifecycle(state: String) {
        uiForeground = state == "foreground"
    }

    private fun availabilityLifecycle(): String = if (uiForeground) "foreground" else "background_available"

    fun command(raw: String): String = bridge("command", raw)

    fun setBackgroundPreference(enabled: Boolean): String {
        val request = JSONObject()
            .put("command", "set_background_availability")
            .put("payload", JSONObject().put("enabled", enabled))
        return internalCommandRaw(request.toString())
    }

    @Synchronized
    fun shutdownNotificationPump() {
        pumpStarted.set(false)
        notificationPump?.shutdownNow()
        notificationPump = null
        multicastLock?.let { if (it.isHeld) it.release() }
        multicastLock = null
    }

    /** Called after the foreground plugin closes the shared Python service. */
    fun onRuntimeShutdown() {
        runtimeInitialized = false
        shutdownNotificationPump()
        execute { clearIncomingCallNotifications() }
    }

    fun statusJson(): JSONObject = JSONObject()
        .put("enabled", configured && preferences.getBoolean(AVAILABILITY_KEY, false))
        .put("runtime_initialized", runtimeInitialized)
        .put("native_webrtc_ready", nativeWebRtcReady)
        .put("multicast_lock_held", multicastLock?.isHeld == true)
        .put("service_running", MeshAvailabilityService.isRunning())
        .put("start_requested", startPending())
        .put("restorations", restorations)
        .put("ui_foreground", uiForeground)
        .put("notification_visible", if (configured) notificationVisible() else false)
        .put("failure", availabilityFailure ?: JSONObject.NULL)
        .put("notification_state", if (configured) permissionState() else "unknown")

    @JvmStatic
    fun status(): String = statusJson().toString()

    fun availabilityFailed(reason: String) {
        startRequestedAt = 0L
        availabilityFailure = reason
        setEnabled(appContext, false)
        execute {
            try { setBackgroundPreference(false) } catch (_: Throwable) { }
        }
    }

    @Synchronized
    private fun acquireMulticast() {
        if (multicastLock != null) return
        val wifi = appContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        multicastLock = wifi.createMulticastLock("mesh-chat-reticulum-background").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun python() = if (Python.isStarted()) {
        Python.getInstance()
    } else {
        Python.start(AndroidPlatform(appContext))
        Python.getInstance()
    }

    private fun bridge(function: String, requestJson: String? = null): String {
        val module = python().getModule("mesh_chat.mobile_bridge")
        return if (requestJson == null) {
            module.callAttr(function).toString()
        } else {
            module.callAttr(function, requestJson).toString()
        }
    }

    private fun internalCommandRaw(raw: String): String = bridge("command", raw)

    private fun internalCommand(command: String, payload: JSONObject = JSONObject()): JSONObject {
        val request = JSONObject().put("command", command).put("payload", payload)
        return JSONObject(internalCommandRaw(request.toString()))
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

    private fun permissionState(): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return if (NotificationManagerCompat.from(appContext).areNotificationsEnabled()) {
                "allowed"
            } else {
                "settings_required"
            }
        }
        return if (
            ContextCompat.checkSelfPermission(appContext, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED &&
            NotificationManagerCompat.from(appContext).areNotificationsEnabled()
        ) {
            "allowed"
        } else if (!preferences.getBoolean("notification-permission-requested", false)) {
            "not_requested"
        } else {
            "denied"
        }
    }

    private fun capability(): JSONObject = JSONObject()
        .put("supported", true)
        .put("platform", "android")
        .put("permission_state", permissionState())

    private fun syncNativeState() {
        if (!runtimeInitialized) return
        try {
            internalCommand("native_notification_state", capability())
        } catch (error: Throwable) {
            Log.e(TAG, "notification state sync failed (${error.javaClass.simpleName})")
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
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
                NotificationChannel(
                    INCOMING_CALL_CHANNEL,
                    "Incoming calls",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "Calls received while Mesh Chat is available in the background"
                },
                NotificationChannel(
                    AVAILABILITY_CHANNEL,
                    "Background availability",
                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = "Shown while Mesh Chat keeps connections available"
                    setShowBadge(false)
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
        val launch = appContext.packageManager.getLaunchIntentForPackage(appContext.packageName)
        if (launch == null) {
            acknowledge(notificationId, "denied")
            return
        }
        val route = Uri.parse("meshchat://notification/$notificationId")
        launch.setAction(Intent.ACTION_VIEW).setData(route)
        launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val requestCode = notificationId.take(8).toLong(16).toInt()
        val pending = PendingIntent.getActivity(
            appContext,
            requestCode,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val channel = if (category == "mention") MENTION_CHANNEL else MESSAGE_CHANNEL
        val notification = NotificationCompat.Builder(appContext, channel)
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
            NotificationManagerCompat.from(appContext).notify(notificationId, 0, notification)
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

    private fun activeIncomingCallNotificationIds(): Set<String> = try {
        val manager = appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.activeNotifications.mapNotNull { notification ->
            if (notification.id != INCOMING_CALL_NOTIFICATION_ID) return@mapNotNull null
            val tag = notification.tag ?: return@mapNotNull null
            if (!tag.startsWith("mesh_chat_incoming_call_")) return@mapNotNull null
            tag.removePrefix("mesh_chat_incoming_call_")
                .takeIf { it.matches(Regex("^[0-9a-f]{32}$")) }
        }.toSet()
    } catch (_: Throwable) { emptySet() }

    private fun clearIncomingCallNotifications() {
        val manager = NotificationManagerCompat.from(appContext)
        for (callId in shownIncomingCalls.toSet() + activeIncomingCallNotificationIds()) {
            manager.cancel("mesh_chat_incoming_call_$callId", INCOMING_CALL_NOTIFICATION_ID)
            shownIncomingCalls.remove(callId)
        }
    }

    private fun syncIncomingCallNotifications() {
        if (
            !runtimeInitialized || uiForeground || !isEnabled(appContext) ||
            !MeshAvailabilityService.isRunning() || permissionState() != "allowed"
        ) {
            clearIncomingCallNotifications()
            return
        }
        val response = internalCommand("native_ringing_calls")
        if (!response.optBoolean("ok")) return
        val calls = response.optJSONObject("result")?.optJSONArray("calls") ?: return
        val current = mutableSetOf<String>()
        val manager = NotificationManagerCompat.from(appContext)
        shownIncomingCalls.addAll(activeIncomingCallNotificationIds())
        for (index in 0 until calls.length()) {
            val call = calls.optJSONObject(index) ?: continue
            val callId = call.optString("id")
            val media = call.optString("media")
            if (!callId.matches(Regex("^[0-9a-f]{32}$")) || media !in setOf("audio", "video")) continue
            val remainingMillis = (call.optDouble("ring_expires_at") * 1000 - System.currentTimeMillis())
                .toLong()
            if (remainingMillis <= 0) continue
            current.add(callId)
            if (shownIncomingCalls.contains(callId)) continue
            val launch = appContext.packageManager.getLaunchIntentForPackage(appContext.packageName)
                ?: continue
            launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            val pending = PendingIntent.getActivity(
                appContext,
                INCOMING_CALL_NOTIFICATION_ID,
                launch,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val notification = NotificationCompat.Builder(appContext, INCOMING_CALL_CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_call)
                .setContentTitle(if (media == "video") "Incoming Mesh Chat video call" else "Incoming Mesh Chat audio call")
                .setContentText("Tap to answer in Mesh Chat")
                .setContentIntent(pending)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setOnlyAlertOnce(true)
                .setAutoCancel(true)
                .setTimeoutAfter(remainingMillis)
                .build()
            try {
                manager.notify("mesh_chat_incoming_call_$callId", INCOMING_CALL_NOTIFICATION_ID, notification)
                shownIncomingCalls.add(callId)
            } catch (error: SecurityException) {
                syncNativeState()
            } catch (error: Throwable) {
                Log.e(TAG, "incoming call notification failed (${error.javaClass.simpleName})")
            }
        }
        for (callId in shownIncomingCalls.toList()) {
            if (callId !in current) {
                manager.cancel("mesh_chat_incoming_call_$callId", INCOMING_CALL_NOTIFICATION_ID)
                shownIncomingCalls.remove(callId)
            }
        }
    }

    @Synchronized
    private fun startNotificationPump() {
        if (!pumpStarted.compareAndSet(false, true)) return
        val pump = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "mesh-chat-background-notifications").apply { isDaemon = true }
        }
        notificationPump = pump
        pump.scheduleWithFixedDelay(
            {
                if (!runtimeInitialized || !pumpQueued.compareAndSet(false, true)) return@scheduleWithFixedDelay
                pythonExecutor.execute {
                    try {
                        drainNativeNotifications()
                        syncIncomingCallNotifications()
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

    fun execute(task: () -> Unit) {
        pythonExecutor.execute(task)
    }

    fun availabilityChannelId(): String = AVAILABILITY_CHANNEL

    fun notificationAllowed(): Boolean {
        if (permissionState() != "allowed") return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true
        val manager = appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        return manager.getNotificationChannel(AVAILABILITY_CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE
    }

    private fun notificationVisible(): Boolean = try {
        val manager = appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationAllowed() && manager.activeNotifications.any { it.id == MeshAvailabilityService.NOTIFICATION_ID }
    } catch (_: Throwable) { false }

    fun ensureNotificationChannels() {
        createNotificationChannels()
    }

    fun notificationId(): Int = MeshAvailabilityService.NOTIFICATION_ID

    fun stopActionPendingIntent(): PendingIntent {
        val intent = Intent(appContext, MeshAvailabilityService::class.java)
            .setAction(MeshAvailabilityService.ACTION_STOP)
        return PendingIntent.getService(
            appContext,
            1,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    fun openAppPendingIntent(): PendingIntent? {
        val launch = appContext.packageManager.getLaunchIntentForPackage(appContext.packageName)
            ?: return null
        return PendingIntent.getActivity(
            appContext,
            2,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    fun availabilityNotification(): android.app.Notification {
        val builder = NotificationCompat.Builder(appContext, AVAILABILITY_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("Mesh Chat is available")
            .setContentText("Keeping your conversations connected")
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setOngoing(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setSilent(true)
            .setShowWhen(false)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .addAction(0, "Stop", stopActionPendingIntent())
        openAppPendingIntent()?.let { builder.setContentIntent(it) }
        return builder.build()
    }

    fun notificationSettingsIntent(): Intent =
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, appContext.packageName)
}
