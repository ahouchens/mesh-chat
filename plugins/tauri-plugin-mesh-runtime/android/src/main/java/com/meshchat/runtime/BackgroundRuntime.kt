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
    private const val AVAILABILITY_CHANNEL = "mesh_chat_availability_v1"
    private const val PREFERENCES = "mesh-chat-vault"
    private const val AVAILABILITY_KEY = "background-availability-enabled"

    @Volatile private var configured = false
    @Volatile private var runtimeInitialized = false
    @Volatile private var availabilityFailure: String? = null
    @Volatile private var uiForeground = false
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
    private var multicastLock: WifiManager.MulticastLock? = null

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

    fun setEnabled(context: Context, enabled: Boolean) {
        configure(context)
        preferences.edit().putBoolean(AVAILABILITY_KEY, enabled).apply()
    }

    fun start(context: Context) {
        configure(context)
        availabilityFailure = null
        setEnabled(context, true)
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

    fun stop(context: Context) {
        configure(context)
        setEnabled(context, false)
        NativeWebRtcBridge.closeAll()
        context.stopService(Intent(context, MeshAvailabilityService::class.java))
    }

    fun initialize(): String {
        check(configured)
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
        try {
            NativeWebRtcBridge.initialize(appContext)
        } catch (error: Throwable) {
            // A native-library failure must not take down the Python runtime or
            // the foreground service; native sessions will report unavailable.
            Log.e(TAG, "native WebRTC initialize failed (${error.javaClass.simpleName})")
        }
        val request = JSONObject()
            .put("profile_dir", profileDir.canonicalPath)
            .put("vault_key", Base64.encodeToString(vaultKey(), Base64.NO_WRAP))
            .put("platform", "android")
        createNotificationChannels()
        acquireMulticast()
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
    }

    fun statusJson(): JSONObject = JSONObject()
        .put("enabled", configured && preferences.getBoolean(AVAILABILITY_KEY, false))
        .put("runtime_initialized", runtimeInitialized)
        .put("service_running", MeshAvailabilityService.isRunning())
        .put("failure", availabilityFailure ?: JSONObject.NULL)
        .put("notification_state", if (configured) permissionState() else "unknown")

    @JvmStatic
    fun status(): String = statusJson().toString()

    fun availabilityFailed(reason: String) {
        availabilityFailure = reason
        setEnabled(appContext, false)
        execute {
            try { setBackgroundPreference(false) } catch (_: Throwable) { }
        }
    }

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

    fun notificationAllowed(): Boolean = permissionState() == "allowed"

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
