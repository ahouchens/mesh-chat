package com.meshchat.runtime

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class NativeCallbackQueueTest {
    @Test(timeout = 10000)
    fun saturatedMetadataQueueStillAdmitsExactDisposal() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val disposed = CountDownLatch(1)
        val failures = AtomicInteger()
        val discarded = AtomicInteger()
        val queue = NativeCallbackQueue({ failures.incrementAndGet() }, capacity = 1)
        try {
            queue.submit({ fail("First callback rejected") }) {
                entered.countDown()
                release.await(5, TimeUnit.SECONDS)
            }
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            queue.submit({ discarded.incrementAndGet() }) { fail("Overflow callback ran") }
            assertEquals(1, failures.get())
            assertEquals(1, discarded.get())
            queue.close { disposed.countDown() }
            release.countDown()
            assertTrue(disposed.await(2, TimeUnit.SECONDS))
            queue.submit({ discarded.incrementAndGet() }) { fail("Closed queue accepted work") }
            assertEquals(2, discarded.get())
        } finally {
            release.countDown()
            queue.close { disposed.countDown() }
        }
    }
}
