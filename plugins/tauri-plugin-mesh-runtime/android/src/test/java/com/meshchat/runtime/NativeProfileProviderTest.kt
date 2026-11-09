package com.meshchat.runtime

import org.junit.Assert.*
import org.junit.Test

class NativeProfileProviderTest {
    private val first = "a".repeat(32)
    private val second = "b".repeat(32)

    @Test fun unverifiedOrDifferentChallengeCannotIssueAuthorization() {
        val gate = NativeProfileAuthorization()
        assertTrue(gate.begin(first))
        assertFalse(gate.consume(first))
        assertFalse(gate.verified(second))
        assertFalse(gate.consume(second))
        assertTrue(gate.verified(first))
        assertTrue(gate.consume(first))
        assertFalse(gate.consume(first))
    }

    @Test fun onlyOneConfirmationCanBePendingAndLateCancellationCannotClearNewOne() {
        val gate = NativeProfileAuthorization()
        assertTrue(gate.begin(first))
        assertFalse(gate.begin(second))
        gate.cancel(first)
        assertTrue(gate.begin(second))
        gate.cancel(first)
        assertTrue(gate.verified(second))
        assertTrue(gate.consume(second))
    }

    @Test fun expiryRejectsCompletedNativeAuthenticationAndAllowsANewChallenge() {
        var now = 10L
        val gate = NativeProfileAuthorization { now }
        assertTrue(gate.begin(first))
        now += 60_000
        assertFalse(gate.verified(first))
        assertFalse(gate.consume(first))
        assertTrue(gate.begin(second))
    }

    @Test fun nativeProviderBindsProofToTheFrameworkCallerAndRegisteredSlot() {
        val gate = NativeProfileAuthorization()
        val provider = NativeProfileProvider("fixed-path", "app.owner", { ByteArray(32) }, { ByteArray(32) }, gate)
        assertTrue(gate.begin(first))
        assertTrue(gate.verified(first))
        assertFalse(provider.consumeAuthorization(first, "other.app", "primary"))
        assertFalse(provider.consumeAuthorization(first, "app.owner", "other-slot"))
        assertTrue(provider.consumeAuthorization(first, "app.owner", "primary"))
        assertFalse(provider.consumeAuthorization(first, "app.owner", "primary"))
    }

    @Test fun coldCatalogReadsItsSeparateAuthorityWithoutLoadingOrOpeningTheProfile() {
        var catalogReads = 0
        val metadata = ByteArray(32) { 7 }
        val issued = mutableListOf<ByteArray>()
        val provider = NativeProfileProvider("fixed-path", "app.owner",
            { error("Locked catalog must never request the original profile key") },
            { catalogReads++; metadata.copyOf().also { issued.add(it) } },
            NativeProfileAuthorization(), beforeOpen = { error("Must remain locked") },
            encodeKey = { java.util.Base64.getEncoder().encodeToString(it) })
        repeat(2) {
            assertEquals(java.util.Base64.getEncoder().encodeToString(metadata), provider.catalogKey())
        }
        assertEquals(2, catalogReads)
        assertTrue(issued.all { key -> key.all { it == 0.toByte() } })
    }

    @Test fun profileOpenReadsOriginalAuthorityFreshAndNeverReadsCatalogKey() {
        var profileReads = 0
        var opens = 0
        val issued = mutableListOf<ByteArray>()
        val provider = NativeProfileProvider("fixed-path", "app.owner",
            { profileReads++; ByteArray(32) { profileReads.toByte() }.also { issued.add(it) } },
            { error("Profile opener must not request the catalog key") },
            NativeProfileAuthorization(), beforeOpen = { opens++ },
            encodeKey = { java.util.Base64.getEncoder().encodeToString(it) })
        assertNotEquals(provider.profileKey(), provider.profileKey())
        assertEquals(2, profileReads)
        assertEquals(2, opens)
        assertTrue(issued.all { key -> key.all { it == 0.toByte() } })
    }

    @Test fun activityDestructionInvalidatesAlreadyVerifiedProof() {
        val gate = NativeProfileAuthorization()
        assertTrue(gate.begin(first))
        assertTrue(gate.verified(first))
        gate.cancelAll()
        assertFalse(gate.consume(first))
    }
}
