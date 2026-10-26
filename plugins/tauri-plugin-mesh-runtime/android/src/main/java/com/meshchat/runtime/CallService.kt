package com.meshchat.runtime

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat

/**
 * Keeps an active audio/video call alive while the activity is backgrounded.
 *
 * The WebView owns the media itself; this service only supplies the Android
 * foreground lifecycle and a persistent, non-secret notification. It never
 * reads the vault or the messaging profile.
 */
class CallService : Service() {
    companion object {
        private const val TAG = "MeshChatCall"
        const val CHANNEL_ID = "mesh_chat_calls_v1"
        const val NOTIFICATION_ID = 7001
        const val EXTRA_MEDIA = "call_media"
    }

    private var foregroundStarted = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                getSystemService(NotificationManager::class.java).createNotificationChannel(
                    NotificationChannel(
                        CHANNEL_ID,
                        "Ongoing calls",
                        NotificationManager.IMPORTANCE_LOW,
                    ).apply {
                        description = "Shown while a Mesh Chat call is active"
                        setShowBadge(false)
                    },
                )
            }
            val launch = packageManager.getLaunchIntentForPackage(packageName)
                ?: throw IllegalStateException("Mesh Chat launch activity is unavailable")
            val pending = PendingIntent.getActivity(
                this,
                0,
                launch,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val notification = NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_call)
                .setContentTitle("Mesh Chat call in progress")
                .setContentText("Tap to return to the call")
                .setContentIntent(pending)
                .setOngoing(true)
                .setSilent(true)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .build()
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val cameraType = if (intent?.getStringExtra(EXTRA_MEDIA) == "video") {
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                } else {
                    0
                }
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or cameraType
            } else {
                0
            }
            ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
            foregroundStarted = true
            START_NOT_STICKY
        } catch (error: Throwable) {
            // A permission or foreground-start denial must not kill the process
            // that owns the independent messaging WebRTC bridge.
            Log.e(TAG, "call foreground start failed (${error.javaClass.simpleName})")
            stopSelf(startId)
            START_NOT_STICKY
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        if (foregroundStarted) stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
}
