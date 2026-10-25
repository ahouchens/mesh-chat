package com.meshchat.runtime

import android.content.Context

/**
 * Lightweight application-context holder. This class deliberately has no
 * org.webrtc references so normal app startup never loads or links libwebrtc.
 */
object NativeWebRtcContext {
    @Volatile
    private var context: Context? = null

    @JvmStatic
    fun attach(value: Context) {
        context = value.applicationContext
    }

    @JvmStatic
    fun get(): Context? = context
}
