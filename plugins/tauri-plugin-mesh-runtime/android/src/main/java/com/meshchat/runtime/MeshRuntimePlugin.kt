package com.meshchat.runtime

import android.app.Activity
import android.content.Context
import android.net.wifi.WifiManager
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.util.concurrent.Executors

@InvokeArg
class InitializeArgs {
    var displayName: String? = null
}

@TauriPlugin
class MeshRuntimePlugin(private val activity: Activity) : Plugin(activity) {
    companion object {
        private const val TAG = "MeshChatRuntime"
    }

    private val preferences by lazy {
        activity.getSharedPreferences("mesh-chat-vault", Context.MODE_PRIVATE)
    }
    private var multicastLock: WifiManager.MulticastLock? = null
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "mesh-chat-python").apply { isDaemon = true }
    }

    @Synchronized
    private fun python() = if (Python.isStarted()) {
        Python.getInstance()
    } else {
        Python.start(AndroidPlatform(activity.applicationContext))
        Python.getInstance()
    }

    private fun vaultKey(): ByteArray {
        val alias = "mesh-chat-vault-key-v1"
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!keyStore.containsAlias(alias)) {
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            generator.generateKey()
        }
        val wrappingKey = keyStore.getKey(alias, null) as SecretKey
        val stored = preferences.getString("wrapped-key", null)
        if (stored != null) {
            val packed = Base64.decode(stored, Base64.NO_WRAP)
            require(packed.size > 12)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, wrappingKey, GCMParameterSpec(128, packed, 0, 12))
            return cipher.doFinal(packed, 12, packed.size - 12)
        }

        val raw = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey)
        val packed = cipher.iv + cipher.doFinal(raw)
        check(preferences.edit().putString("wrapped-key", Base64.encodeToString(packed, Base64.NO_WRAP)).commit())
        return raw
    }

    private fun bridge(function: String, requestJson: String? = null): String {
        val module = python().getModule("mesh_chat.mobile_bridge")
        return if (requestJson == null) {
            module.callAttr(function).toString()
        } else {
            module.callAttr(function, requestJson).toString()
        }
    }

    private fun resolve(invoke: Invoke, json: String) {
        val value = JSObject()
        value.put("json", json)
        invoke.resolve(value)
    }

    private fun reject(invoke: Invoke, operation: String, error: Throwable) {
        // Record only the failing stage and exception type. Messages from
        // upstream libraries can contain private paths or peer addresses.
        Log.e(TAG, "$operation failed (${error.javaClass.simpleName})")
        invoke.reject("mobile_runtime_unavailable")
    }

    @Command
    fun initialize(invoke: Invoke) {
        val args = invoke.parseArgs(InitializeArgs::class.java)
        pythonExecutor.execute {
            try {
                val profileDir = activity.filesDir.resolve("mesh-chat/profile-v1")
                check(profileDir.mkdirs() || profileDir.isDirectory)
                val request = JSONObject()
                    .put("profile_dir", profileDir.canonicalPath)
                    .put("vault_key", Base64.encodeToString(vaultKey(), Base64.NO_WRAP))
                    .put("display_name", args.displayName)
                    .put("platform", "android")
                val wifi = activity.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                multicastLock = multicastLock ?: wifi.createMulticastLock("mesh-chat-reticulum").apply {
                    setReferenceCounted(false)
                    acquire()
                }
                resolve(invoke, bridge("initialize", request.toString()))
            } catch (error: Throwable) {
                reject(invoke, "initialize", error)
            }
        }
    }

    @Command
    fun command(invoke: Invoke) {
        // Preserve the exact nested JSON object emitted by Rust. Jackson cannot
        // populate org.json.JSONObject/JSObject fields and silently produced an
        // empty payload, which made every parameterized mobile command fail
        // validation even though its scanned or pasted invitation was valid.
        val requestJson = invoke.getRawArgs()
        pythonExecutor.execute {
            try {
                resolve(invoke, bridge("command", requestJson))
            } catch (error: Throwable) {
                reject(invoke, "command", error)
            }
        }
    }

    @Command
    fun drainEvents(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                resolve(invoke, bridge("drain_events"))
            } catch (error: Throwable) {
                reject(invoke, "drain_events", error)
            }
        }
    }

    @Command
    fun shutdown(invoke: Invoke) {
        pythonExecutor.execute {
            try {
                val result = bridge("shutdown")
                multicastLock?.let { if (it.isHeld) it.release() }
                multicastLock = null
                resolve(invoke, result)
            } catch (error: Throwable) {
                reject(invoke, "shutdown", error)
            }
        }
    }
}
