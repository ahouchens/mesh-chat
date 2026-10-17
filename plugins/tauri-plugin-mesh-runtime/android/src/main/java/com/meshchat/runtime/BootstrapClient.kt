package com.meshchat.runtime

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Looper
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Python-only Binder client. No Tauri command exposes this capability. */
class BootstrapClient private constructor(private val context: Context) {
    companion object {
        private var context: Context? = null
        private val active = AtomicReference<BootstrapClient?>(null)

        fun configure(value: Context) { context = value.applicationContext }

        @JvmStatic @Synchronized fun open(): BootstrapClient {
            check(active.get() == null) { "bootstrap_busy" }
            val client = BootstrapClient(checkNotNull(context))
            check(active.compareAndSet(null, client)) { "bootstrap_busy" }
            return client
        }
    }

    private val connected = CompletableFuture<Messenger>()
    private val lifecycle = Any()
    private val pending = AtomicReference<CompletableFuture<String>?>(null)
    private val thread = HandlerThread("mesh-bootstrap-replies").apply { start() }
    private val responses = Messenger(Handler(thread.looper) { message ->
        val bytes = message.data.getByteArray("response")
        if (message.arg1 == sequence && bytes != null && bytes.size <= 819200) {
            pending.get()?.complete(String(bytes, Charsets.UTF_8))
        } else {
            pending.get()?.completeExceptionally(IllegalStateException("bootstrap_unavailable"))
        }
        true
    })
    @Volatile private var sequence = 0
    @Volatile private var closed = false
    @Volatile private var bound = false
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            connected.complete(Messenger(binder))
        }
        override fun onServiceDisconnected(name: ComponentName) { close() }
        override fun onBindingDied(name: ComponentName) { close() }
        override fun onNullBinding(name: ComponentName) { close() }
    }

    @Synchronized fun call(raw: String): String {
        try {
            check(!closed)
            val bytes = raw.toByteArray(Charsets.UTF_8)
            require(bytes.size in 1..819200)
            synchronized(lifecycle) {
                check(!closed)
                if (!bound) {
                    bound = context.bindService(Intent(context, BootstrapService::class.java), connection, Context.BIND_AUTO_CREATE)
                    check(bound)
                }
            }
            val remote = connected.get(5, TimeUnit.SECONDS)
            val result = CompletableFuture<String>()
            synchronized(lifecycle) {
                check(!closed && pending.compareAndSet(null, result))
            }
            sequence += 1
            remote.send(Message.obtain().apply {
                arg1 = sequence
                replyTo = responses
                data = Bundle().apply { putByteArray("request", bytes) }
            })
            return result.get(5, TimeUnit.SECONDS)
        } catch (error: Throwable) {
            close()
            throw IllegalStateException("bootstrap_unavailable")
        } finally {
            pending.set(null)
        }
    }

    fun close() {
        synchronized(lifecycle) {
            if (closed) return
            closed = true
            connected.completeExceptionally(IllegalStateException("bootstrap_unavailable"))
            pending.get()?.completeExceptionally(IllegalStateException("bootstrap_unavailable"))
            if (bound) {
                bound = false
                try { context.unbindService(connection) } catch (_: IllegalArgumentException) { }
            }
        }
        context.stopService(Intent(context, BootstrapService::class.java))
        thread.quitSafely()
        // The old service kills its process after bounded cleanup. Do not bind a
        // replacement into that retiring interpreter during the cleanup window.
        Handler(Looper.getMainLooper()).postDelayed({ active.compareAndSet(this, null) }, 1500)
    }
}
