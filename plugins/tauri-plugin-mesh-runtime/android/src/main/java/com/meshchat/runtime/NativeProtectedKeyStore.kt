package com.meshchat.runtime

import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Native callers supply fixed namespaces; no SDK request selects a key slot. */
internal object NativeProtectedKeyStore {
    @Synchronized fun load(alias: String, storage: SharedPreferences, record: String = "wrapped-key"): ByteArray {
        val stored = storage.getString(record, null)
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!keyStore.containsAlias(alias)) {
            check(stored == null) { "native_key_unavailable" }
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(KeyGenParameterSpec.Builder(alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
            generator.generateKey()
        }
        val wrappingKey = keyStore.getKey(alias, null) as SecretKey
        if (stored != null) {
            val packed = Base64.decode(stored, Base64.NO_WRAP)
            require(packed.size > 12)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, wrappingKey, GCMParameterSpec(128, packed, 0, 12))
            return cipher.doFinal(packed, 12, packed.size - 12)
        }
        val raw = ByteArray(32).also { SecureRandom().nextBytes(it) }
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, wrappingKey)
            val packed = cipher.iv + cipher.doFinal(raw)
            check(storage.edit().putString(record, Base64.encodeToString(packed, Base64.NO_WRAP)).commit())
            return raw
        } catch (failure: Throwable) {
            raw.fill(0)
            throw failure
        }
    }
}
