package com.meshchat.runtime

import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Binder
import android.os.IBinder
import android.os.Process
import android.util.Base64
import com.chaquo.python.Python

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
    private val api = object : IMeshCoreApi.Stub() {
        override fun exchange(frame: ByteArray): ByteArray = dispatch(frame)
    }

    override fun onBind(intent: Intent?): IBinder = api

    private fun dispatch(frame: ByteArray): ByteArray {
        // Same-UID callers are the application itself (its UI or its own
        // services), which is the host; every other caller must hold the
        // signature permission.
        val uid = Binder.getCallingUid()
        val hostUid = Process.myUid()
        val permission = if (MeshCoreRuntime.isInstalled()) "$packageName.permission.MESH_CORE_API" else PERMISSION
        if (uid != hostUid &&
            checkCallingPermission(permission) != PackageManager.PERMISSION_GRANTED
        ) {
            return errorFrame("forbidden")
        }
        val name = callingPackage(uid, hostUid) ?: return errorFrame("forbidden")
        val caller = CoreCaller.fromUid(uid, hostUid, name)
        val observation = CoreObservationContext.capture(api.asBinder(), uid == hostUid, caller.scope == "owner")
        return dispatcher.exchange(caller, frame, observation)
    }

    private fun callingPackage(uid: Int, hostUid: Int): String? {
        val packageManager = packageManager
        if (uid == hostUid) {
            return packageName
        }
        return packageManager.getNameForUid(uid)?.substringBefore(':')
    }

    companion object {
        // The app process owns admission. Unbinding/recreating this Android
        // service must not replace a worker whose native invocation is wedged.
        private val dispatcher = CoreDispatch({ caller, frame, observation ->
            val module = Python.getInstance().getModule("mesh_chat.mobile_bridge")
            val encoded = Base64.encodeToString(frame, Base64.NO_WRAP)
            val reply = if (observation == null) module.callAttr("core_exchange", caller.name, encoded, caller.scope).toString()
                else Python.getInstance().getModule("mesh_chat.core_api.qualification_host")
                    .callAttr("android_observed_core_exchange", caller.name, encoded, caller.scope,
                        observation.qualificationBinding, observation.sink).toString()
            Base64.decode(reply, Base64.NO_WRAP)
        })
        const val PERMISSION = "com.meshchat.runtime.permission.CORE_API"
        const val MAX_FRAME_BYTES = CoreDispatch.MAX_FRAME_BYTES

        fun errorFrame(code: String): ByteArray = CoreDispatch.errorFrame(code)
    }
}
