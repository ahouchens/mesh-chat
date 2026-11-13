package com.meshchat.runtime

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.webrtc.RTCStats
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class NativePathEvidenceTest {
    private val request = "1".repeat(32)

    @Test fun sampleRequestMustBeExactLowerHex() {
        assertTrue(NativePathEvidence.validRequest(request))
        for (bad in listOf("", "1".repeat(31), "1".repeat(33), "A".repeat(32), "g".repeat(32))) {
            assertFalse(NativePathEvidence.validRequest(bad))
        }
    }

    @Test fun originalCaptureIsRelativeToAdapterEvenWithNegativeNanoTimeOrigin() {
        val origin = -9_000_000_000L
        val captured = -8_000_000_000L
        val value = sample(reports()).put("sampled_at_ms", NativePathEvidence.sampledAt(origin, captured))
        assertEquals(1000L, value.getLong("sampled_at_ms"))
        assertTrue(NativePathEvidence.fresh(value, request, origin, captured, captured, captured + 1))
        assertFalse(NativePathEvidence.fresh(value, request, origin, captured, captured, captured + 2_000_000_001L))
    }

    @Test fun originalCaptureWindowHasNoRoundingAllowanceOrBackwardsJump() {
        val origin = -1_000_000_000L
        val captured = 999_999L
        val value = sample(reports()).put("sampled_at_ms", NativePathEvidence.sampledAt(origin, captured))
        assertTrue(NativePathEvidence.fresh(value, request, origin, captured, captured, captured + 2_000_000_000L))
        assertFalse(NativePathEvidence.fresh(value, request, origin, captured, captured, captured + 2_000_000_001L))
        assertFalse(NativePathEvidence.fresh(value, request, origin, captured + 1, captured, captured + 2))
        assertFalse(NativePathEvidence.fresh(value, request, origin, captured, captured, captured - 1))
        assertFalse(NativePathEvidence.fresh(value, request, origin, captured - 2_000_000_001L, captured, captured))
    }

    @Test fun cachedOrMalformedObservationCannotBorrowFreshRequest() {
        val captured = 1_000_000_000L
        val value = sample(reports())
        assertTrue(NativePathEvidence.fresh(value, request, 0, captured, captured, captured))
        assertFalse(NativePathEvidence.fresh(value, "2".repeat(32), 0, captured, captured, captured))
        val missing = JSONObject(value.toString()).apply { remove("sample_request") }
        assertFalse(NativePathEvidence.fresh(missing, request, 0, captured, captured, captured))
        for (bad in listOf<Any>(JSONObject.NULL, true, 1L, "A".repeat(32))) {
            val changed = JSONObject(value.toString()).put("sample_request", bad)
            assertFalse(NativePathEvidence.fresh(changed, request, 0, captured, captured, captured))
        }
        for (bad in listOf<Any>(true, "1000", 1000.5, -1L, 9007199254740992L, 999L, 1001L)) {
            val changed = JSONObject(value.toString()).put("sampled_at_ms", bad)
            assertFalse(NativePathEvidence.fresh(changed, request, 0, captured, captured, captured))
        }
        val replay = JSONObject(value.toString()).put("sample_request", "2".repeat(32))
        assertFalse(NativePathEvidence.fresh(replay, "2".repeat(32), 0, captured + 3_000_000_000L,
            captured + 3_000_000_000L, captured + 3_000_000_000L))
    }

    @Test fun duplicateCallbackCannotOverwriteOrReleaseOriginalOrNewerCustody() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val original = Any()
        val slot = AtomicReference<Any?>(original)
        val sequence = AtomicInteger()
        val invocation = NativePathEvidence.SamplingInvocation(request, 0, 1_000_000_000L,
            slot, original, { true }, { 1_000_000_000L })
        val callback = {
            invocation.collect {
                sequence.incrementAndGet()
                entered.countDown()
                check(release.await(2, TimeUnit.SECONDS))
                sample(reports())
            }
        }
        val worker = Thread { callback() }
        worker.start()
        try {
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            callback()
            assertEquals(1, sequence.get())
            assertNull(invocation.response())
            assertFalse(invocation.isComplete())
            assertSame(original, slot.get())
        } finally {
            release.countDown()
            worker.join(2000)
        }
        assertFalse(worker.isAlive)
        assertEquals(request, JSONObject(invocation.response()!!).getJSONObject("result").getString("sample_request"))
        val newer = Any()
        slot.set(newer)
        callback()
        assertSame(newer, slot.get())
        assertEquals(1, sequence.get())
    }

    @Test fun timedOutOriginalCallbackRetainsSlotUntilActualCaptureFails() {
        var now = 1_000_000_000L
        val original = Any()
        val slot = AtomicReference<Any?>(original)
        val invocation = NativePathEvidence.SamplingInvocation(request, 0, now, slot, original, { true }, { now })
        now += 2_000_000_001L
        assertFalse(invocation.isComplete())
        assertSame(original, slot.get())
        invocation.collect { captured ->
            sample(reports()).put("sampled_at_ms", captured / 1_000_000)
        }
        assertTrue(invocation.isComplete())
        assertNull(invocation.response())
        assertNull(slot.get())
    }

    @Test fun successfulCaptureCannotBeRestampedAfterTransportDelay() {
        var now = 1_000_000_000L
        val original = Any()
        val slot = AtomicReference<Any?>(original)
        val invocation = NativePathEvidence.SamplingInvocation(request, 0, now, slot, original, { true }, { now })
        invocation.collect { sample(reports()) }
        assertNotNull(invocation.response())
        now += 2_000_000_001L
        assertNull(invocation.response())
    }

    @Test fun actualInvocationRejectsFreshChallengeOverCachedOriginalTimestamp() {
        val now = 4_000_000_000L
        val original = Any()
        val slot = AtomicReference<Any?>(original)
        val invocation = NativePathEvidence.SamplingInvocation(request, 0, now, slot, original, { true }, { now })
        invocation.collect { sample(reports()) } // Original timestamp is 1000, not 4000.
        assertTrue(invocation.isComplete())
        assertNull(invocation.response())
        assertNull(slot.get())
    }

    @Test fun actualInvocationCannotPublishOrReleaseForeignSamplingToken() {
        val original = Any()
        val newer = Any()
        val slot = AtomicReference<Any?>(original)
        val invocation = NativePathEvidence.SamplingInvocation(request, 0, 1_000_000_000L,
            slot, original, { true }, { 1_000_000_000L })
        invocation.collect {
            slot.set(newer)
            sample(reports())
        }
        assertTrue(invocation.isComplete())
        assertNull(invocation.response())
        assertSame(newer, slot.get())
    }
    @Test fun cancellationDoesNotAcknowledgePhysicalRetirement() {
        val reservations = NativeSessionReservations(1)
        val lease = reservations.reserve("peer")!!
        assertTrue(reservations.beginAllocation(lease))
        reservations.finishCreation(lease)
        reservations.cancel("peer")
        assertFalse(lease.awaitRetired(1))
        assertFalse(lease.claimRetirementNotification())
        assertNull(reservations.reserve("replacement"))
        reservations.disposed(lease)
        assertTrue(lease.awaitRetired(0))
        assertTrue(lease.claimRetirementNotification())
        assertFalse(lease.claimRetirementNotification())
        assertNotNull(reservations.reserve("replacement"))
    }

    @Test fun disposalBeforeCreationUnwindsStillCannotAcknowledgeRetirement() {
        val reservations = NativeSessionReservations(1)
        val lease = reservations.reserve("peer")!!
        assertTrue(reservations.beginAllocation(lease))
        reservations.cancel("peer")
        reservations.disposed(lease)
        assertFalse(lease.awaitRetired(1))
        reservations.finishCreation(lease)
        assertTrue(lease.awaitRetired(0))
    }

    @Test fun lateOldDisposalCannotAcknowledgeANewReservationWithTheSameId() {
        val reservations = NativeSessionReservations(1)
        val old = reservations.reserve("peer")!!
        reservations.cancel("peer")
        reservations.finishCreation(old)
        assertTrue(old.awaitRetired(0))
        val fresh = reservations.reserve("peer")!!
        assertTrue(reservations.beginAllocation(fresh))
        reservations.finishCreation(fresh)
        reservations.cancel("peer")
        reservations.disposed(old)
        assertFalse(fresh.awaitRetired(1))
        reservations.disposed(fresh)
        assertTrue(fresh.awaitRetired(0))
    }

    @Test fun accountingRetainsCreatingAndCancelledAllocatedLeasesUntilActualDisposal() {
        val reservations = NativeSessionReservations(2)
        val lease = reservations.reserve("peer")!!
        assertEquals(1, reservations.accounting()["reserved_count"])
        assertEquals(1, reservations.accounting()["creating_count"])
        assertTrue(reservations.beginAllocation(lease))
        assertEquals(1, reservations.accounting()["active_count"])
        reservations.cancel("peer")
        reservations.finishCreation(lease)
        val retiring = reservations.accounting()
        assertEquals(0, retiring["active_count"])
        assertEquals(0, retiring["creating_count"])
        assertEquals(1, retiring["retiring_count"])
        assertEquals(1, retiring["allocated_count"])
        assertEquals(1, retiring["reserved_count"])
        reservations.disposed(lease)
        assertEquals(0, reservations.accounting()["reserved_count"])
    }

    private fun reports(relay: String? = "tcp"): MutableMap<String, RTCStats> {
        fun stat(type: String, id: String, vararg members: Pair<String, Any>) =
            RTCStats(1000L, type, id, mapOf(*members))
        val local = mutableMapOf<String, Any>("address" to "192.0.2.1", "port" to 1234L,
            "candidateType" to "relay", "protocol" to "udp", "url" to "turns:advertised.invalid",
            "password" to "must-not-export")
        if (relay != null) local["relayProtocol"] = relay
        return mutableMapOf(
            "transport" to stat("transport", "transport", "selectedCandidatePairId" to "pair", "dtlsState" to "connected"),
            "pair" to stat("candidate-pair", "pair", "state" to "succeeded", "localCandidateId" to "local",
                "remoteCandidateId" to "remote", "nominated" to true, "bytesSent" to 100L,
                "bytesReceived" to 200L, "currentRoundTripTime" to 0.125),
            "local" to RTCStats(1000L, "local-candidate", "local", local),
            "remote" to stat("remote-candidate", "remote", "address" to "192.0.2.2", "port" to 4321L,
                "candidateType" to "relay", "protocol" to "udp"),
        )
    }

    private fun sample(stats: Map<String, RTCStats>): JSONObject {
        val application = JSONObject()
        for (key in listOf("enqueued_packets", "enqueued_controls", "enqueued_bytes",
            "received_packets", "received_controls", "received_bytes")) application.put(key, 0L)
        return NativePathEvidence.sample("peer", "a".repeat(32), 1, 1000, request,
            "connected", "open", stats, application)
    }

    @Test fun selectedTransportReferencesActualPairAndExplicitOuterSocketAvailability() {
        val value = sample(reports())
        assertEquals("selected", value.getString("status"))
        val pair = value.getJSONObject("pair")
        // Shared v1 canonical JSON / SHA256 vector from Python validator.
        assertEquals("81911e80dca5fcbb5c26360f0a3d7446", pair.getString("token"))
        assertEquals("tcp", pair.getString("relay_protocol"))
        assertEquals("udp", pair.getJSONObject("local").getString("protocol"))
        assertTrue(pair.isNull("relay_socket"))
        assertFalse(value.getJSONObject("availability").getBoolean("relay_socket"))
        assertTrue(value.getJSONObject("availability").getBoolean("pair_bytes"))
        assertEquals(100L, pair.getLong("bytes_sent"))
        assertEquals(125.0, pair.getDouble("rtt_ms"), 0.001)
        assertFalse(value.toString().contains("password"))
        assertFalse(value.toString().contains("turns:"))
    }

    @Test fun advertisedTlsCannotReplaceAbsentActualRelayProtocol() {
        val value = sample(reports(null))
        assertEquals("unknown", value.getJSONObject("pair").getString("relay_protocol"))
        assertFalse(value.getJSONObject("availability").getBoolean("relay_protocol"))
    }

    @Test fun actualTlsStatRemainsDistinctFromUdpCandidateTransport() {
        assertEquals("tls", sample(reports("tls")).getJSONObject("pair").getString("relay_protocol"))
    }

    @Test fun CandidateInventoryDoesNotImplyASelectedPair() {
        val stats = reports()
        stats.remove("transport")
        val value = sample(stats)
        assertEquals("unsupported", value.getString("status"))
        assertTrue(value.isNull("pair"))
        assertFalse(value.getJSONObject("availability").getBoolean("selected_pair"))
    }

    @Test fun failedPairCannotReportSelectedCounters() {
        val stats = reports()
        stats["pair"] = RTCStats(1000L, "candidate-pair", "pair", mapOf("state" to "failed"))
        val value = sample(stats)
        assertEquals("unavailable", value.getString("status"))
        assertTrue(value.isNull("pair"))
        assertFalse(value.getJSONObject("availability").getBoolean("pair_bytes"))
    }
}
