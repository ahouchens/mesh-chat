package com.meshchat.runtime

import android.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** One current native device-credential confirmation; no renderer facts grant it. */
class NativeProfileAuthorization(private val now: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private data class Proof(val challenge: String, val expires: Long, var verified: Boolean = false)
    private var proof: Proof? = null

    @Synchronized fun begin(challenge: String): Boolean {
        if (!challenge.matches(Regex("^[0-9a-f]{32}$")) || proof?.let { it.expires > now() } == true) return false
        proof = Proof(challenge, now() + 60_000)
        return true
    }

    @Synchronized fun verified(challenge: String): Boolean {
        val current = proof ?: return false
        if (current.challenge != challenge || current.expires <= now()) return false
        current.verified = true
        return true
    }

    @Synchronized fun consume(challenge: String): Boolean {
        val current = proof ?: return false
        if (current.challenge != challenge || !current.verified || current.expires <= now()) return false
        proof = null
        return true
    }

    @Synchronized fun cancel(challenge: String) {
        if (proof?.challenge == challenge) proof = null
    }
}

internal fun profileCatalogKey(key: ByteArray): ByteArray {
    require(key.size == 32)
    return Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }
        .doFinal("mesh-chat:profile-host-catalog:v1".toByteArray(Charsets.US_ASCII))
}

/** Installed only by native Kotlin; the original Keystore-backed key reader is authoritative. */
class NativeProfileProvider(
    private val directory: String,
    private val caller: String,
    private val loadExistingKey: () -> ByteArray,
    private val authorization: NativeProfileAuthorization,
    private val beforeOpen: () -> Unit = {},
    private val publication: (String) -> Unit = {},
) {
    fun profileDirectory(): String = directory
    fun ownerCaller(): String = caller
    fun publicationChanged(context: String) = publication(context)

    fun profileKey(): String {
        beforeOpen()
        val key = loadExistingKey()
        try {
            check(key.size == 32)
            return Base64.encodeToString(key, Base64.NO_WRAP)
        } finally {
            key.fill(0)
        }
    }

    fun catalogKey(): String {
        val key = loadExistingKey()
        var derived: ByteArray? = null
        try {
            derived = profileCatalogKey(key)
            return Base64.encodeToString(derived, Base64.NO_WRAP)
        } finally {
            key.fill(0)
            derived?.fill(0)
        }
    }

    fun consumeAuthorization(challenge: String, owner: String, profile: String): Boolean =
        owner == caller && profile == "primary" && authorization.consume(challenge)
}
