package com.meshchat.runtime

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * Keeps the process, CPython runtime, and native transports at foreground
 * importance while the user opts in.
 *
 * It deliberately does not own the vault or a second interpreter. Activity
 * destruction must not stop this service; explicit Mesh Chat lock, the Stop
 * action, or the user's disable action must.
 */
class MeshAvailabilityService : Service() {
    companion object {
        private const val TAG = "MeshChatAvailability"
        const val ACTION_START = "com.meshchat.runtime.action.START_AVAILABILITY"
        const val ACTION_STOP = "com.meshchat.runtime.action.STOP_AVAILABILITY"
        const val NOTIFICATION_ID = 7002

        @Volatile private var running = false

        fun isRunning(): Boolean = running

        fun start(context: Context) {
            BackgroundRuntime.configure(context.applicationContext)
            ContextCompat.startForegroundService(
                context,
                Intent(context, MeshAvailabilityService::class.java).setAction(ACTION_START),
            )
        }

        fun stop(context: Context) {
            BackgroundRuntime.configure(context.applicationContext)
            context.stopService(Intent(context, MeshAvailabilityService::class.java))
        }

        fun isEnabled(context: Context): Boolean = BackgroundRuntime.isEnabled(context)
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onCreate() {
        super.onCreate()
        BackgroundRuntime.configure(applicationContext)
        BackgroundRuntime.ensureNotificationChannels()
        try {
            startAsForeground()
            running = true
            BackgroundRuntime.onServiceStarted()
        } catch (error: Throwable) {
            Log.e(TAG, "foreground start denied (${error.javaClass.simpleName})")
            running = false
            BackgroundRuntime.setEnabled(applicationContext, false)
            BackgroundRuntime.availabilityFailed("foreground_start_denied")
            stopSelf()
            return
        }
        acquireLocks()
        BackgroundRuntime.execute {
            try {
                if (BackgroundRuntime.isEnabled(applicationContext)) {
                    BackgroundRuntime.initialize()
                    BackgroundRuntime.setBackgroundPreference(true)
                }
            } catch (error: Throwable) {
                Log.e(TAG, "background runtime initialization failed (${error.javaClass.simpleName})")
                BackgroundRuntime.setEnabled(applicationContext, false)
                BackgroundRuntime.availabilityFailed("runtime_initialization_failed")
                try {
                    BackgroundRuntime.setBackgroundPreference(false)
                } catch (_: Throwable) {
                    // Python may not have initialized at all.
                }
                stopSelf()
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                BackgroundRuntime.setPreference(applicationContext, false)
                NativeWebRtcBridge.closeAll()
                BackgroundRuntime.execute {
                    try {
                        BackgroundRuntime.setBackgroundPreference(false)
                    } catch (error: Throwable) {
                        Log.e(TAG, "background disable failed (${error.javaClass.simpleName})")
                    }
                }
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                return try {
                    startAsForeground()
                    START_STICKY
                } catch (error: Throwable) {
                    Log.e(TAG, "foreground restart denied (${error.javaClass.simpleName})")
                    BackgroundRuntime.setEnabled(applicationContext, false)
                    BackgroundRuntime.availabilityFailed("foreground_restart_denied")
                    stopSelf()
                    START_NOT_STICKY
                }
            }
        }
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // A task swipe is not a user opt-out. Keep the notification and the
        // service running; the Stop action is the explicit exit.
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        running = false
        BackgroundRuntime.onServiceStopped()
        releaseLocks()
        BackgroundRuntime.shutdownNotificationPump()
        stopForeground(Service.STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startAsForeground() {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING
        } else {
            0
        }
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            BackgroundRuntime.availabilityNotification(),
            type,
        )
    }

    @Suppress("DEPRECATION")
    private fun acquireLocks() {
        if (wakeLock == null) {
            val power = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = power.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "mesh-chat:availability",
            ).apply {
                setReferenceCounted(false)
                acquire()
            }
        }
        if (wifiLock == null) {
            val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiLock = wifi.createWifiLock(
                WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                "mesh-chat:availability",
            ).apply {
                setReferenceCounted(false)
                acquire()
            }
        }
    }

    private fun releaseLocks() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
    }
}
