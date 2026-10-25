package com.meshchat.runtime

import android.content.Context
import android.util.Log

/**
 * Reflection-only entry point for lifecycle code. Keeping org.webrtc types out
 * of MeshRuntimePlugin/BackgroundRuntime class references prevents Android's
 * class verifier from touching the native WebRTC library during normal launch.
 */
object NativeWebRtcBridge {
    private const val TAG = "MeshChatNativeBridge"
    private const val HOST = "com.meshchat.runtime.NativeWebRtcHost"

    @JvmStatic
    fun attach(context: Context) {
        NativeWebRtcContext.attach(context)
    }

    @JvmStatic
    fun initialize(context: Context): Boolean {
        NativeWebRtcContext.attach(context)
        try {
            val host = Class.forName(HOST)
            host.getMethod("initialize", Context::class.java).invoke(null, context)
            return true
        } catch (error: Throwable) {
            Log.e(TAG, "native WebRTC initialize failed (${error.javaClass.simpleName})")
            return false
        }
    }

    @JvmStatic
    fun closeAll() {
        try {
            Class.forName(HOST).getMethod("closeAll").invoke(null)
        } catch (error: Throwable) {
            // The host may never have been loaded; closing is best effort.
            Log.d(TAG, "native WebRTC close skipped (${error.javaClass.simpleName})")
        }
    }
}
