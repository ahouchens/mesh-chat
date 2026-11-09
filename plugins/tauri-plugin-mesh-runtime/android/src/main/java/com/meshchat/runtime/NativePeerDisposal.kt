package com.meshchat.runtime

import java.util.IdentityHashMap

/** Exact native wrappers stay owned until each close/dispose call acknowledges. */
internal class NativePeerDisposal<C : Any>(
    private val closeChannel: (C) -> Unit,
    private val disposeChannel: (C) -> Unit,
    private val closePeer: () -> Unit,
    private val disposePeer: () -> Unit,
    private val channelLimit: Int = 64,
) {
    private class Channel<C>(val value: C, var discard: Boolean = false,
                             var closed: Boolean = false, var disposed: Boolean = false)
    private val custody = Any()
    private val worker = Any()
    private val channels = IdentityHashMap<C, Channel<C>>()
    private var peerClosed = false
    private var peerDisposed = false

    /** False fences the peer, but still retains this actual wrapper for disposal. */
    fun own(value: C): Boolean = synchronized(custody) {
        channels.getOrPut(value) { Channel(value) }
        channels.size <= channelLimit
    }

    fun discard(value: C) = synchronized(custody) {
        channels.getOrPut(value) { Channel(value) }.discard = true
    }

    fun pendingChannels(): Int = synchronized(custody) { channels.values.count { !it.disposed } }
    fun pendingDiscards(): Int = synchronized(custody) { channels.values.count { it.discard && !it.disposed } }

    fun disposeDiscards() = synchronized(worker) { drain(discardOnly = true) }

    fun dispose(): Boolean = synchronized(worker) {
        if (!peerClosed) {
            closePeer()
            peerClosed = true
        }
        drain(discardOnly = false)
        if (!peerDisposed) {
            // Native peer disposal ends observer production. A callback already
            // delivering a wrapper may add custody during this call.
            disposePeer()
            peerDisposed = true
        }
        drain(discardOnly = false)
        pendingChannels() == 0
    }

    private fun drain(discardOnly: Boolean) {
        val pending = synchronized(custody) {
            channels.values.filter { !it.disposed && (!discardOnly || it.discard) }
        }
        for (channel in pending) {
            if (!channel.closed) {
                closeChannel(channel.value)
                channel.closed = true
            }
            disposeChannel(channel.value)
            synchronized(custody) { channel.disposed = true }
        }
    }
}
