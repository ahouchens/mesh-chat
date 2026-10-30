package com.meshchat.runtime

import android.content.Context
import android.os.Process
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.security.SecureRandom
import java.util.UUID

/** Runs packaged CPython/mobile crypto and JNI in the optimized Android host.
 * The runner supplies a local real Worker via adb reverse; never the public
 * deployment. Fault injection is deterministic, not a cellular/Doze proof.
 */
@RunWith(AndroidJUnit4::class)
class SignalMailboxAndroidTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val expectedDefault = "https://mesh-chat-signal.webtechalex.workers.dev"

    private fun python(): Python {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        return Python.getInstance()
    }

    private fun fixture(): PyObject {
        val py = python()
        val module = py.getModule("types").callAttr("ModuleType", "android_signal_fixture")
        val source = instrumentation.context.assets.open("signal_mailbox_fixture.py")
            .bufferedReader().use { it.readText() }
        py.builtins.callAttr("exec", source, module.get("__dict__"))
        return module
    }

    private fun workerUrl(): String {
        val url = InstrumentationRegistry.getArguments().getString("mailboxUrl")
        require(url == "http://127.0.0.1:8789") { "Run through scripts/test_android_signaling.sh" }
        return url!!
    }

    private fun command(name: String, payload: JSONObject = JSONObject()): JSONObject {
        val response = JSONObject(python().getModule("mesh_chat.mobile_bridge").callAttr("command",
            JSONObject().put("command", name).put("payload", payload).toString()).toString())
        assertTrue("Command failed: $name (${response.optJSONObject("error")?.optString("code")})",
            response.optBoolean("ok"))
        return response.optJSONObject("result") ?: JSONObject()
    }

    private fun initialize(path: String, key: String) {
        val response = JSONObject(python().getModule("mesh_chat.mobile_bridge").callAttr("initialize",
            JSONObject().put("profile_dir", path).put("vault_key", key)
                .put("display_name", "Synthetic Android mailbox").put("platform", "android").toString()).toString())
        assertTrue("Android runtime initialization failed", response.optBoolean("ok"))
    }

    private fun shutdown() {
        val response = JSONObject(python().getModule("mesh_chat.mobile_bridge").callAttr("shutdown").toString())
        assertTrue("Android runtime shutdown failed", response.optBoolean("ok"))
    }

    @Test(timeout = 90_000)
    fun embeddedDefaultAndChoicesSurviveProcessRestart() {
        // The runner invokes seed, force-stops the isolated host, then verify.
        // A separate test process is required: restarting a Python service alone
        // would miss accidental dependence on process-local configuration.
        val phase = InstrumentationRegistry.getArguments().getString("restartPhase")
        require(phase == "seed" || phase == "verify")
        val preferences = context.getSharedPreferences("mailbox-test-restart", Context.MODE_PRIVATE)
        if (phase == "seed") {
            val run = UUID.randomUUID().toString()
            val records = JSONArray()
            for (choice in listOf("default", "custom", "disabled")) {
                val key = Base64.encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) }, Base64.NO_WRAP)
                val path = context.filesDir.resolve("mailbox-ci/$run/$choice").absolutePath
                try {
                    initialize(path, key)
                    val settings = command("call_settings")
                    assertEquals(expectedDefault, settings.getString("signal_mailbox_default_url"))
                    assertEquals(expectedDefault, settings.getString("signal_mailbox_url"))
                    if (choice != "default") {
                        command("update_call_settings", JSONObject().put("stun_urls", JSONArray())
                            .put("relay_only", false).put("signal_mailbox_url",
                                if (choice == "custom") "https://custom.example.test/" else JSONObject.NULL))
                    }
                    records.put(JSONObject().put("choice", choice).put("path", path).put("key", key))
                } finally { shutdown() }
            }
            // Synthetic keys only, in the isolated instrumentation app's sandbox.
            preferences.edit().putString("records", records.toString()).putInt("pid", Process.myPid()).commit()
        } else {
            assertTrue("Seed phase was not run", preferences.contains("records"))
            assertNotEquals("Runner did not restart the process", preferences.getInt("pid", -1), Process.myPid())
            val records = JSONArray(preferences.getString("records", null))
            for (i in 0 until records.length()) {
                val record = records.getJSONObject(i)
                try {
                    initialize(record.getString("path"), record.getString("key"))
                    val settings = command("call_settings")
                    assertEquals(expectedDefault, settings.getString("signal_mailbox_default_url"))
                    when (record.getString("choice")) {
                        "default" -> assertEquals(expectedDefault, settings.getString("signal_mailbox_url"))
                        "custom" -> assertEquals("https://custom.example.test", settings.getString("signal_mailbox_url"))
                        "disabled" -> assertTrue(settings.isNull("signal_mailbox_url"))
                    }
                } finally { shutdown() }
            }
            preferences.edit().clear().commit()
        }
    }

    @Test(timeout = 45_000)
    fun packagedAndroidCryptoExchangesCiphertextWithWorker() {
        assertEquals("True", fixture().callAttr("encrypted_round_trip", workerUrl()).toString())
    }

    @Test(timeout = 450_000)
    fun personalMailboxRecoversAfterLossRestartAndLifecycleChanges() = recovery(false)

    @Test(timeout = 450_000)
    fun workspaceMailboxRecoversAfterLossRestartAndLifecycleChanges() = recovery(true)

    private fun recovery(workspace: Boolean) {
        python()
        NativeWebRtcHost.initialize(context)
        try {
            val directory = context.filesDir.resolve("mailbox-ci/${UUID.randomUUID()}").absolutePath
            assertEquals("True", fixture().callAttr("run_recovery", directory, workerUrl(), workspace).toString())
        } finally {
            NativeWebRtcHost.closeAll()
        }
    }

    @Test(timeout = 450_000)
    fun sharedRuntimeOwnsNativeRecoveryAcrossLifecycle() {
        python()
        NativeWebRtcHost.initialize(context)
        try {
            val directory = context.filesDir.resolve("mailbox-ci/${UUID.randomUUID()}").absolutePath
            assertEquals("True", fixture().callAttr("run_shared_runtime_native", directory, workerUrl()).toString())
        } finally {
            NativeWebRtcHost.closeAll()
        }
    }

    @Test(timeout = 240_000)
    fun sharedRuntimeAdoptsVerifiedManualNativeCarrierWithoutMailbox() {
        python()
        NativeWebRtcHost.initialize(context)
        val key = Base64.encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) }, Base64.NO_WRAP)
        try {
            val directory = context.filesDir.resolve("manual-adoption-ci/${UUID.randomUUID()}").absolutePath
            initialize(directory, key)
            assertEquals("True", fixture().callAttr("run_manual_native_adoption").toString())
        } finally {
            shutdown()
            NativeWebRtcHost.closeAll()
        }
    }
}
