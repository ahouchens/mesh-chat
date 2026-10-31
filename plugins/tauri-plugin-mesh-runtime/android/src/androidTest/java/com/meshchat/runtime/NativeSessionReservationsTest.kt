package com.meshchat.runtime

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class NativeSessionReservationsTest {
    @Test
    fun cancellationRetainsCapacityUntilCreationAndDisposalFinish() {
        val registry = NativeSessionReservations(1)
        val lease = requireNotNull(registry.reserve("one"))
        assertTrue(registry.beginAllocation(lease))
        registry.cancel("one")
        assertFalse(registry.active(lease))
        assertNull(registry.reserve("two"))
        registry.disposed(lease)
        assertNull(registry.reserve("two"))
        registry.finishCreation(lease)
        assertNotNull(registry.reserve("two"))
    }

    @Test
    fun cancelledCreationCannotRetryOrReplaceItsReservation() {
        val registry = NativeSessionReservations(1)
        val old = requireNotNull(registry.reserve("one"))
        registry.cancel("one")
        assertFalse(registry.beginAllocation(old))
        assertNull(registry.reserve("one"))
        registry.finishCreation(old)
        val replacement = requireNotNull(registry.reserve("one"))
        assertTrue(registry.beginAllocation(replacement))
        registry.disposed(old)
        registry.finishCreation(old)
        assertTrue(registry.active(replacement))
        assertFalse(registry.beginAllocation(replacement))
    }

    @Test
    fun replacementWaitsForExactPhysicalDisposal() {
        val registry = NativeSessionReservations(1)
        val lease = requireNotNull(registry.reserve("one"))
        assertTrue(registry.beginAllocation(lease))
        assertFalse(registry.beginAllocation(lease))
        registry.disposed(lease)
        assertTrue(registry.beginAllocation(lease))
        registry.finishCreation(lease)
        registry.cancel("one")
        assertNull(registry.reserve("one"))
        registry.disposed(lease)
        assertNotNull(registry.reserve("one"))
    }

    @Test(timeout = 10000)
    fun concurrentCreatorsCannotOverbookOrReplaceAnId() {
        val registry = NativeSessionReservations(1)
        val start = CountDownLatch(1)
        val pool = Executors.newFixedThreadPool(8)
        try {
            val results = (1..8).map {
                pool.submit<NativeSessionReservations.Lease?> {
                    start.await(2, TimeUnit.SECONDS)
                    registry.reserve("same")
                }
            }
            start.countDown()
            assertEquals(1, results.count { it.get(2, TimeUnit.SECONDS) != null })
        } finally {
            pool.shutdownNow()
        }
    }
}
