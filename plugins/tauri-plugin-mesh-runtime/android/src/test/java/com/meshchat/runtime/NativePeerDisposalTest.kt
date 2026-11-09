package com.meshchat.runtime

import org.junit.Assert.*
import org.junit.Test

/** Executes the production disposal coordinator; native calls are explicit doubles. */
class NativePeerDisposalTest {
    private class Channel(var closeFailures: Int = 0, var disposeFailures: Int = 0) {
        var closes = 0
        var disposes = 0
        fun close() { closes++; if (closeFailures-- > 0) error("close unavailable") }
        fun dispose() { disposes++; if (disposeFailures-- > 0) error("dispose unavailable") }
    }

    private fun coordinator(closePeer: () -> Unit = {}, disposePeer: () -> Unit = {}) =
        NativePeerDisposal<Channel>({ it.close() }, { it.dispose() }, closePeer, disposePeer)

    private fun fails(operation: () -> Unit) {
        try { operation(); fail("Native failure must prevent acknowledgment") }
        catch (_: IllegalStateException) { }
    }

    @Test fun failedChannelDisposalRetainsExactWrapperWithoutRedisposingSuccessfulChannels() {
        var peerCloses = 0
        var peerDisposes = 0
        val disposal = coordinator({ peerCloses++ }, { peerDisposes++ })
        val successful = Channel()
        val failed = Channel(disposeFailures = 1)
        disposal.own(successful)
        disposal.own(failed)
        fails { disposal.dispose() }
        assertTrue(disposal.pendingChannels() >= 1)
        assertEquals(0, peerDisposes)
        assertTrue(disposal.dispose())
        assertEquals(0, disposal.pendingChannels())
        assertEquals(1, successful.closes)
        assertEquals(1, successful.disposes)
        assertEquals(1, failed.closes)
        assertEquals(2, failed.disposes)
        assertEquals(1, peerCloses)
        assertEquals(1, peerDisposes)
        assertTrue(disposal.dispose())
        assertEquals(1, successful.disposes)
    }

    @Test fun failedChannelCloseCannotBecomeADisposalAcknowledgment() {
        val channel = Channel(closeFailures = 1)
        val disposal = coordinator()
        disposal.own(channel)
        fails { disposal.dispose() }
        assertEquals(1, disposal.pendingChannels())
        assertEquals(0, channel.disposes)
        assertTrue(disposal.dispose())
        assertEquals(2, channel.closes)
        assertEquals(1, channel.disposes)
    }

    @Test fun failedPeerDisposalDoesNotRedisposeAcknowledgedChannelWrappers() {
        var attempts = 0
        val disposal = coordinator(disposePeer = { if (++attempts == 1) error("peer unavailable") })
        val channel = Channel()
        disposal.own(channel)
        fails { disposal.dispose() }
        assertEquals(0, disposal.pendingChannels())
        assertTrue(disposal.dispose())
        assertEquals(2, attempts)
        assertEquals(1, channel.closes)
        assertEquals(1, channel.disposes)
    }

    @Test fun lateObserverChannelDuringPeerDisposalMustAlsoAcknowledgeBeforeCompletion() {
        val late = Channel(disposeFailures = 1)
        var peerDisposes = 0
        lateinit var disposal: NativePeerDisposal<Channel>
        disposal = coordinator(disposePeer = { peerDisposes++; disposal.own(late) })
        fails { disposal.dispose() }
        assertEquals(1, disposal.pendingChannels())
        assertTrue(disposal.dispose())
        assertEquals(1, peerDisposes)
        assertEquals(1, late.closes)
        assertEquals(2, late.disposes)
    }

    @Test fun unregisteredDiscardStaysOwnedOnFailureAndDoesNotCloseTheActivePeer() {
        var peerCloses = 0
        val disposal = coordinator(closePeer = { peerCloses++ })
        val active = Channel()
        val rejected = Channel(disposeFailures = 1)
        disposal.own(active)
        disposal.own(rejected)
        disposal.discard(rejected)
        fails { disposal.disposeDiscards() }
        assertEquals(1, disposal.pendingDiscards())
        assertEquals(2, disposal.pendingChannels())
        assertEquals(0, peerCloses)
        disposal.disposeDiscards()
        assertEquals(0, disposal.pendingDiscards())
        assertEquals(1, disposal.pendingChannels())
        assertEquals(0, active.disposes)
        assertTrue(disposal.dispose())
        assertEquals(1, active.disposes)
        assertEquals(2, rejected.disposes)
        assertEquals(1, peerCloses)
    }
}
