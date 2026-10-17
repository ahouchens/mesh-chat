package com.meshchat.runtime

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Process
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Dedicated, non-exported interpreter. It never opens the profile vault. */
class BootstrapService : Service() {
    private lateinit var thread: HandlerThread
    private lateinit var messenger: Messenger
    private var worker: PyObject? = null

    override fun onCreate() {
        super.onCreate()
        thread = HandlerThread("mesh-bootstrap-engine").apply { start() }
        messenger = Messenger(Handler(thread.looper) { message ->
            if (message.sendingUid != applicationInfo.uid || message.replyTo == null) {
                return@Handler true
            }
            val bytes = message.data.getByteArray("request")
            var response = "{\"ok\":false,\"error\":\"bootstrap_unavailable\"}"
            try {
                require(bytes != null && bytes.size in 1..819200)
                if (worker == null) {
                    if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                    worker = Python.getInstance().getModule("mesh_chat.direct_bootstrap_worker")
                        .callAttr("BootstrapWorker", cacheDir.absolutePath)
                }
                response = worker!!.callAttr("call", String(bytes, Charsets.UTF_8)).toString()
                require(response.toByteArray(Charsets.UTF_8).size <= 819200)
            } catch (_: Throwable) {
                response = "{\"ok\":false,\"error\":\"bootstrap_unavailable\"}"
                try { worker?.callAttr("close") } catch (_: Throwable) { }
            }
            try {
                message.replyTo.send(Message.obtain().apply {
                    arg1 = message.arg1
                    data = Bundle().apply { putByteArray("response", response.toByteArray(Charsets.UTF_8)) }
                })
            } catch (_: Throwable) {
                stopSelf()
            }
            true
        })
    }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onDestroy() {
        // RNS has process-global singletons. A retired interpreter must never be
        // reused by a later relationship or by the primary service.
        super.onDestroy()
        Handler(thread.looper).post {
            try { worker?.callAttr("close") } catch (_: Throwable) { }
            finally { Process.killProcess(Process.myPid()) }
        }
        Handler(mainLooper).postDelayed({ Process.killProcess(Process.myPid()) }, 1000)
    }
}
