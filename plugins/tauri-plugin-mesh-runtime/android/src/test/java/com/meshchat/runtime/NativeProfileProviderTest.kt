package com.meshchat.runtime

import org.junit.Assert.*
import org.junit.Test

class NativeProfileProviderTest {
    private val first = "a".repeat(32)
    private val second = "b".repeat(32)

    @Test fun catalogPolicyRefusesReplacementBeforeCallingTheKeyLoader() {
        val root = java.nio.file.Files.createTempDirectory("mesh-catalog-policy").toFile()
        try {
            val profile = root.resolve("profile-v1")
            val catalog = root.resolve("host-v1/mesh-chat.vault")
            catalog.parentFile!!.mkdirs()
            catalog.writeBytes(byteArrayOf(1))
            val error = assertThrows(IllegalStateException::class.java) {
                NativeProfileKeyPolicy.catalog(profile, { false }) { error("Key loader must not run") }
            }
            assertEquals("native_key_unavailable", error.message)
            val existing = ByteArray(32) { 7 }
            assertSame(existing, NativeProfileKeyPolicy.catalog(profile, { true }) { existing })
            assertArrayEquals(byteArrayOf(1), catalog.readBytes())
        } finally { root.deleteRecursively() }
    }

    @Test fun profileWithoutItsCatalogCannotCreateANewMetadataAuthority() {
        val root = java.nio.file.Files.createTempDirectory("mesh-catalog-policy").toFile()
        try {
            val profile = root.resolve("profile-v1")
            profile.mkdirs()
            profile.resolve("mesh-chat.vault").writeBytes(byteArrayOf(1))
            assertThrows(IllegalStateException::class.java) {
                NativeProfileKeyPolicy.catalog(profile, { true }) { error("Key loader must not run") }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun onlyAnEmptyNamespaceCanCreateItsFirstCatalogKey() {
        val root = java.nio.file.Files.createTempDirectory("mesh-catalog-policy").toFile()
        try {
            val fresh = ByteArray(32)
            assertSame(fresh, NativeProfileKeyPolicy.catalog(root.resolve("profile-v1"), { false }) { fresh })
        } finally { root.deleteRecursively() }
    }

    @Test fun failedCatalogKeyDoesNotReadOrOpenTheProfile() {
        val failure = IllegalStateException("native_key_unavailable")
        val provider = NativeProfileProvider("fixed-path", "app.owner",
            { error("Must not read the profile key") }, { throw failure }, NativeProfileAuthorization(),
            beforeOpen = { error("Must not open the profile") })
        assertSame(failure, assertThrows(IllegalStateException::class.java) { provider.catalogKey() })
    }

    @Test fun malformedCatalogKeyIsClearedWithoutOpeningTheProfile() {
        val malformed = ByteArray(16) { 7 }
        val provider = NativeProfileProvider("fixed-path", "app.owner",
            { error("Must not read the profile key") }, { malformed }, NativeProfileAuthorization(),
            beforeOpen = { error("Must not open the profile") }, encodeKey = { error("Must not encode it") })
        assertThrows(IllegalStateException::class.java) { provider.catalogKey() }
        assertTrue(malformed.all { it == 0.toByte() })
    }

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
