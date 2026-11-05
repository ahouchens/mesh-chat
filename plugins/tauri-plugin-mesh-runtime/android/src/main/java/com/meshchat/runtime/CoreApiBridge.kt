package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import com.meshchat.runtime.core.CoreClient
import com.meshchat.runtime.core.CoreException
import com.meshchat.runtime.core.CoreExchangeTransport
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Same-process Binder client for the application's own Core API service. */
object CoreApiBridge {
    private val lock = Any()
    private var bound: IMeshCoreApi? = null
    private var client: CoreClient? = null
    @Volatile
    private var latch = CountDownLatch(1)

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            synchronized(lock) {
                bound = service?.let { IMeshCoreApi.Stub.asInterface(it) }
                client = null
                latch.countDown()
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            synchronized(lock) {
                bound = null
                client = null
                latch = CountDownLatch(1)
            }
        }
    }

    fun bind(context: Context) {
        if (bound != null) return
        context.bindService(
            Intent(context, MeshCoreApiService::class.java),
            connection,
            Context.BIND_AUTO_CREATE,
        )
    }

    fun command(raw: String): String? {
        val request = JSONObject(raw)
        val command = request.optString("command")
        val payload = request.optJSONObject("payload") ?: JSONObject()
        if (command.isEmpty()) return null
        latch.await(3, TimeUnit.SECONDS)
        val api = synchronized(lock) { bound } ?: return null
        val current = synchronized(lock) {
            client ?: CoreClient.open(CoreExchangeTransport { frame -> api.exchange(frame) })
                .also { client = it }
        }
        return try {
            val result = current.applicationCommand(command, payload)
            JSONObject().put("ok", true).put("result", result).toString()
        } catch (error: CoreException) {
            if (command == "snapshot" || command == "workspace_snapshot") {
                null
            } else {
                JSONObject().put("ok", false).put(
                    "error", JSONObject().put("code", error.code),
                ).toString()
            }
        }
    }
}
