package com.meshchat.runtime

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.Semaphore
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Metadata callbacks only. Packet/control payloads use Python's bounded inbox. */
class NativeCallbackQueue(
    private val overflow: () -> Unit,
    capacity: Int = 64,
) {
    private val closed = AtomicBoolean()
    private val slots = Semaphore(capacity)
    // One extra queue slot is reserved for exact-resource disposal.
    private val executor = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
        LinkedBlockingQueue<Runnable>(capacity + 1), { task ->
            Thread(task, "mesh-webrtc-channel-events").apply { isDaemon = true }
        })

    fun submit(discarded: () -> Unit, block: () -> Unit) {
        if (closed.get()) { discarded(); return }
        if (!slots.tryAcquire()) {
            discarded()
            overflow()
            return
        }
        try {
            executor.execute {
                try { block() } finally { slots.release() }
            }
        } catch (_: RejectedExecutionException) {
            slots.release()
            discarded()
            if (!closed.get()) overflow()
        }
    }

    fun close(dispose: () -> Unit) {
        if (!closed.compareAndSet(false, true)) return
        executor.execute { dispose() }
        executor.shutdown()
    }
}
