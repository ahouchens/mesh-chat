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
    private var hostClient: CoreHostClient? = null
    private val exchangeLock = Any()
    private var bindingRequested = false
    private var applicationContext: Context? = null
    @Volatile
    private var latch = CountDownLatch(1)

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            synchronized(lock) {
                bound = service?.let { IMeshCoreApi.Stub.asInterface(it) }
                client = null
                hostClient = null
                latch.countDown()
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            synchronized(lock) {
                bound = null
                client = null
                hostClient = null
                latch = CountDownLatch(1)
            }
        }

        override fun onBindingDied(name: ComponentName?) {
            val context = synchronized(lock) {
                bound = null
                client = null
                hostClient = null
                bindingRequested = false
                latch = CountDownLatch(1)
                applicationContext
            } ?: return
            context.unbindService(this)
            bind(context)
        }

        override fun onNullBinding(name: ComponentName?) {
            val context = synchronized(lock) {
                bindingRequested = false
                latch.countDown()
                applicationContext
            }
            context?.unbindService(this)
        }
    }

    fun bind(context: Context) {
        synchronized(lock) {
            applicationContext = context.applicationContext
            if (bindingRequested) return
            if (latch.count == 0L) latch = CountDownLatch(1)
            bindingRequested = true
            val appContext = checkNotNull(applicationContext)
            if (!appContext.bindService(Intent(appContext, MeshCoreApiService::class.java),
                    connection, Context.BIND_AUTO_CREATE)) {
                bindingRequested = false
                latch.countDown()
            }
        }
    }

    /** No legacy command fallback after a typed Core operation is submitted. */
    fun typedCommand(context: Context, raw: String): String = synchronized(exchangeLock) {
        try {
            bind(context)
            latch.await(3, TimeUnit.SECONDS)
            val current = synchronized(lock) {
                val api = bound ?: throw CoreHostFailure("unavailable")
                hostClient ?: CoreHostClient { frame -> api.exchange(frame) }.also { hostClient = it }
            }
            val request = JSONObject(raw)
            val result = CoreHostCommands(current).execute(request.getString("action"),
                request.getJSONObject("payload"))
            JSONObject().put("ok", true).put("result", result).toString()
        } catch (error: CoreHostFailure) {
            JSONObject().put("ok", false).put("error", error.error).toString()
        } catch (_: org.json.JSONException) {
            failure("invalid_request")
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            failure("unavailable")
        } catch (_: android.os.RemoteException) {
            synchronized(lock) { hostClient = null; client = null }
            // The mutation outcome may be unknown. Rebinding never replays it.
            failure("unavailable")
        }
    }

    private fun failure(code: String) = JSONObject().put("ok", false)
        .put("error", CoreHostFailure(code).error).toString()

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
            val result = current.nativeCommand(command, payload)
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
