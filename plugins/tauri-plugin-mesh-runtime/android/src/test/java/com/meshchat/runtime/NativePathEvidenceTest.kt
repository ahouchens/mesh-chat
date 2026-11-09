package com.meshchat.runtime

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.webrtc.RTCStats

class NativePathEvidenceTest {
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
        return NativePathEvidence.sample("peer", "a".repeat(32), 1, 1000,
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
