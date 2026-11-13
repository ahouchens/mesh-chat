package com.meshchat.runtime

import java.io.Closeable
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CompletableFuture
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONObject

/** Authority captured on the Binder transaction thread, never on its executor. */
internal class CoreCaller private constructor(val name: String, val scope: String) {
    companion object {
        fun fromUid(uid: Int, hostUid: Int, name: String) =
            CoreCaller(name, if (uid == hostUid) "owner" else "consumer")
    }
}

/** One admitted operation, no queued mutations, and bounded Binder frames. */
internal class CoreDispatch(
    private val invoke: (CoreCaller, ByteArray, CoreFrameObservation?) -> ByteArray,
    private val timeoutMillis: Long = 30_000,
) : Closeable {
    private val occupied = AtomicBoolean(false)
    // The single handoff slot is available only after the previous invocation
    // finishes, while its worker is completing the response future.
    private val executor = ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
        ArrayBlockingQueue(1), { runnable -> Thread(runnable, "mesh-chat-core-api").apply { isDaemon = true } })

    fun exchange(caller: CoreCaller, frame: ByteArray, observation: CoreFrameObservation? = null): ByteArray {
        fun rejected(code: String): ByteArray { observation?.failedDelivery(); return errorFrame(code) }
        if (frame.isEmpty() || frame.size > MAX_FRAME_BYTES) return rejected("invalid_request")
        if (executor.isShutdown) return rejected("unavailable")
        if (!occupied.compareAndSet(false, true)) return rejected("resource_exhausted")
        val request = frame.copyOf()
        val pending = CompletableFuture<ByteArray>()
        try {
            executor.execute {
                val result = runCatching { invoke(caller, request, observation?.takeIf { it.active() }) }
                occupied.set(false)
                result.fold(pending::complete, pending::completeExceptionally)
            }
        } catch (_: RejectedExecutionException) {
            occupied.set(false)
            return rejected(if (executor.isShutdown) "unavailable" else "resource_exhausted")
        }
        return try {
            val reply = pending.get(timeoutMillis, TimeUnit.MILLISECONDS)
            if (reply.isEmpty() || reply.size > MAX_FRAME_BYTES) rejected("resource_exhausted") else reply
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            rejected("unavailable")
        } catch (_: Exception) {
            // A timed-out mutation has an unknown outcome. Do not retry it or
            // release worker capacity until the actual invocation has ended.
            rejected("unavailable")
        }
    }

    override fun close() { executor.shutdownNow() }

    companion object {
        const val MAX_FRAME_BYTES = 256 * 1024
        fun errorFrame(code: String): ByteArray = (JSONObject()
            .put("api_version", 1).put("request_id", JSONObject.NULL).put("ok", false)
            .put("error", JSONObject().put("code", code).put("retry_after_ms", JSONObject.NULL))
            .toString() + "\n").toByteArray(Charsets.UTF_8)
    }
}
