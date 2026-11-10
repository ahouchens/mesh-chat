package com.meshchat.runtime

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CoreDispatchTest {
    private fun error(bytes: ByteArray) = JSONObject(String(bytes)).getJSONObject("error").getString("code")

    @Test fun sequentialExchangesDoNotLoseAdmissionDuringWorkerHandoff() {
        val caller = CoreCaller.fromUid(100, 100, "host")
        CoreDispatch({ _, frame, _ -> frame }).use { dispatch ->
            repeat(1000) { assertArrayEquals(byteArrayOf(1), dispatch.exchange(caller, byteArrayOf(1))) }
        }
    }

    @Test fun callerAuthorityIsCapturedBeforeWorkerDispatch() {
        val binderUid = ThreadLocal.withInitial { 100 }
        binderUid.set(200)
        val caller = CoreCaller.fromUid(binderUid.get(), 100, "external")
        CoreDispatch({ received, _, _ ->
            assertEquals(100, binderUid.get()) // Worker has the host's identity.
            assertEquals("consumer", received.scope)
            assertEquals("external", received.name)
            "ok".toByteArray()
        }).use { assertEquals("ok", String(it.exchange(caller, byteArrayOf(1)))) }
        assertEquals("owner", CoreCaller.fromUid(100, 100, "host").scope)
    }

    @Test fun fullAdmissionAndTimeoutCannotAccumulateOrExecuteWaitingMutations() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val caller = CoreCaller.fromUid(200, 100, "external")
        val pool = Executors.newSingleThreadExecutor()
        val dispatch = CoreDispatch({ _, _, _ ->
            entered.countDown()
            // Model a native operation which does not stop when interrupted.
            while (release.count > 0) try { release.await() } catch (_: InterruptedException) { }
            "ok".toByteArray()
        }, timeoutMillis = 100)
        try {
            val first = pool.submit<ByteArray> { dispatch.exchange(caller, byteArrayOf(1)) }
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            assertEquals("resource_exhausted", error(dispatch.exchange(caller, byteArrayOf(2))))
            assertEquals("unavailable", error(first.get(2, TimeUnit.SECONDS)))
            assertEquals("resource_exhausted", error(dispatch.exchange(caller, byteArrayOf(3))))
        } finally { release.countDown(); dispatch.close(); pool.shutdownNow() }
    }

    @Test fun malformedFramesAndClosedAdmissionHaveNoEffects() {
        var calls = 0
        val dispatch = CoreDispatch({ _, _, _ -> calls++; byteArrayOf(1) })
        val caller = CoreCaller.fromUid(100, 100, "host")
        assertEquals("invalid_request", error(dispatch.exchange(caller, byteArrayOf())))
        assertEquals("invalid_request", error(dispatch.exchange(caller, ByteArray(CoreDispatch.MAX_FRAME_BYTES + 1))))
        dispatch.close()
        assertEquals("unavailable", error(dispatch.exchange(caller, byteArrayOf(1))))
        assertEquals(0, calls)
    }

    @Test fun oversizedResponsesFailExplicitlyInsteadOfCrossingBinderBudget() {
        CoreDispatch({ _, _, _ -> ByteArray(CoreDispatch.MAX_FRAME_BYTES + 1) }).use {
            assertEquals("resource_exhausted", error(it.exchange(CoreCaller.fromUid(100, 100, "host"), byteArrayOf(1))))
        }
    }
}
