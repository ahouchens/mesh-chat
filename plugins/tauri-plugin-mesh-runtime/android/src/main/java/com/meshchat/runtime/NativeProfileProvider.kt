package com.meshchat.runtime

import android.util.Base64
import java.io.File

/** Existing encrypted metadata never authorizes replacement key creation. */
internal object NativeProfileKeyPolicy {
    fun catalog(profile: File, hasKey: () -> Boolean, load: () -> ByteArray): ByteArray {
        val catalog = profile.parentFile!!.resolve("host-v1/mesh-chat.vault")
        check(!profile.resolve("mesh-chat.vault").exists() || catalog.exists()) { "native_key_unavailable" }
        check(!catalog.exists() || hasKey()) { "native_key_unavailable" }
        return load()
    }
}

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

    @Synchronized fun cancelAll() { proof = null }
}

/** Installed only by native Kotlin; the original Keystore-backed key reader is authoritative. */
class NativeProfileProvider(
    private val directory: String,
    private val caller: String,
    private val loadExistingKey: () -> ByteArray,
    private val loadCatalogKey: () -> ByteArray,
    private val authorization: NativeProfileAuthorization,
    private val beforeOpen: () -> Unit = {},
    private val publication: (String) -> Unit = {},
    private val encodeKey: (ByteArray) -> String = { Base64.encodeToString(it, Base64.NO_WRAP) },
) {
    fun profileDirectory(): String = directory
    fun ownerCaller(): String = caller
    fun publicationChanged(context: String) = publication(context)

    fun profileKey(): String {
        beforeOpen()
        val key = loadExistingKey()
        try {
            check(key.size == 32)
            return encodeKey(key)
        } finally {
            key.fill(0)
        }
    }

    fun catalogKey(): String {
        val key = loadCatalogKey()
        try {
            check(key.size == 32)
            return encodeKey(key)
        } finally {
            key.fill(0)
        }
    }

    fun consumeAuthorization(challenge: String, owner: String, profile: String): Boolean =
        owner == caller && profile == "primary" && authorization.consume(challenge)
}
