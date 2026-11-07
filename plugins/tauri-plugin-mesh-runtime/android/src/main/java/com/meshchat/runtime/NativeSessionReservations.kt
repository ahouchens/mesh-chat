package com.meshchat.runtime

/** Capacity includes creation and asynchronous disposal, not just routable peers. */
class NativeSessionReservations(private val capacity: Int) {
    class Lease internal constructor(val id: String) {
        internal var creating = true
        internal var allocated = false
        internal var cancelled = false
    }

    private val leases = mutableMapOf<String, Lease>()

    init { require(capacity > 0) }

    @Synchronized
    fun reserve(id: String): Lease? {
        if (id.isBlank() || id.toByteArray(Charsets.UTF_8).size > 128 ||
            id in leases || leases.size >= capacity) return null
        return Lease(id).also { leases[id] = it }
    }

    @Synchronized
    fun active(lease: Lease): Boolean = leases[lease.id] === lease && !lease.cancelled

    @Synchronized
    fun beginAllocation(lease: Lease): Boolean {
        if (!active(lease) || lease.allocated || !lease.creating) return false
        lease.allocated = true
        return true
    }

    @Synchronized
    fun disposed(lease: Lease) {
        if (leases[lease.id] !== lease) return
        lease.allocated = false
        releaseFinished(lease)
    }

    @Synchronized
    fun finishCreation(lease: Lease) {
        if (leases[lease.id] !== lease) return
        lease.creating = false
        releaseFinished(lease)
    }

    @Synchronized
    fun cancel(id: String): Lease? = leases[id]?.also {
        it.cancelled = true
        releaseFinished(it)
    }

    @Synchronized
    fun ids(): List<String> = leases.keys.toList()

    private fun releaseFinished(lease: Lease) {
        if (lease.cancelled && !lease.creating && !lease.allocated) leases.remove(lease.id)
    }
}
