package com.meshchat.runtime

import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Binder
import android.os.IBinder
import android.os.Process
import android.util.Base64
import com.chaquo.python.Python
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject

/**
 * Authenticated Binder entry for the private core API.
 *
 * Authentication is a framework decision: the service is exported only behind a
 * signature permission, and the caller package comes from [Binder.getCallingUid]
 * rather than from the frame. Python binds one framed session per caller and
 * scope: the application's own UID receives owner grants, external
 * signature-permission packages receive consumer grants. No retry, queue or
 * runtime ownership lives here.
 */
class MeshCoreApiService : Service() {
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-core-api").apply { isDaemon = true }
    }

    private val api = object : IMeshCoreApi.Stub() {
        override fun exchange(frame: ByteArray): ByteArray = dispatch(frame)
    }

    override fun onBind(intent: Intent?): IBinder = api

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun dispatch(frame: ByteArray): ByteArray {
        // Same-UID callers are the application itself (its UI or its own
        // services), which is the host; every other caller must hold the
        // signature permission.
        if (Binder.getCallingUid() != Process.myUid() &&
            checkCallingPermission(PERMISSION) != PackageManager.PERMISSION_GRANTED
        ) {
            return errorFrame("forbidden")
        }
        val caller = callingPackage() ?: return errorFrame("forbidden")
        if (frame.isEmpty() || frame.size > MAX_FRAME_BYTES) {
            // Binder transactions are smaller than the facade ceiling; refuse
            // before dispatch so a consumer never sees a truncated frame.
            return errorFrame("invalid_request")
        }
        return try {
            executor.submit<ByteArray> {
                val module = Python.getInstance().getModule("mesh_chat.mobile_bridge")
                val encoded = Base64.encodeToString(frame, Base64.NO_WRAP)
                val scope = if (Binder.getCallingUid() == Process.myUid()) "owner" else "consumer"
                val reply = module.callAttr("core_exchange", caller, encoded, scope).toString()
                Base64.decode(reply, Base64.NO_WRAP)
            }.get(30, TimeUnit.SECONDS)
        } catch (error: Throwable) {
            errorFrame("unavailable")
        }
    }

    private fun callingPackage(): String? {
        val uid = Binder.getCallingUid()
        val packageManager = packageManager
        if (uid == Process.myUid()) {
            return packageName
        }
        return packageManager.getNameForUid(uid)?.substringBefore(':')
    }

    companion object {
        const val PERMISSION = "com.meshchat.runtime.permission.CORE_API"
        const val MAX_FRAME_BYTES = 256 * 1024

        fun errorFrame(code: String): ByteArray {
            val error = JSONObject()
                .put("api_version", 1)
                .put("request_id", JSONObject.NULL)
                .put("ok", false)
                .put("error", JSONObject().put("code", code).put("retry_after_ms", JSONObject.NULL))
            return (error.toString() + "\n").toByteArray(Charsets.UTF_8)
        }
    }
}
