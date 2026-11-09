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
        val provider = NativeProfileProvider("fixed-path", "app.owner", { ByteArray(32) }, gate)
        assertTrue(gate.begin(first))
        assertTrue(gate.verified(first))
        assertFalse(provider.consumeAuthorization(first, "other.app", "primary"))
        assertFalse(provider.consumeAuthorization(first, "app.owner", "other-slot"))
        assertTrue(provider.consumeAuthorization(first, "app.owner", "primary"))
        assertFalse(provider.consumeAuthorization(first, "app.owner", "primary"))
    }

    @Test fun catalogKeyIsDomainSeparatedFromTheProfileKey() {
        val key = ByteArray(32) { 'b'.code.toByte() }
        val derived = profileCatalogKey(key)
        assertEquals(32, derived.size)
        assertFalse(key.contentEquals(derived))
        assertEquals("b".repeat(32), key.toString(Charsets.US_ASCII))
    }
}
