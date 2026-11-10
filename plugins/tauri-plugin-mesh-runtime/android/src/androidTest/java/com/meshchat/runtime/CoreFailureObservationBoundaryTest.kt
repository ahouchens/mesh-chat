package com.meshchat.runtime

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Separate optimized instrumentation controls; no extra requests in the interop controller workload. */
@RunWith(AndroidJUnit4::class)
class CoreFailureObservationBoundaryTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private fun withQualifiedService(action: (PyObject, String, String) -> Unit) {
        val executor = Executors.newSingleThreadExecutor()
        try {
            executor.submit {
                BootstrapClient.configure(context)
                NativeWebRtcBridge.attach(context)
                if (!Python.isStarted()) Python.start(AndroidPlatform(context))
                val python = Python.getInstance()
                val fixture = python.getModule("types").callAttr("ModuleType", "core_failure_observation_fixture")
                python.builtins.callAttr("exec", FIXTURE, fixture.get("__dict__"))
                val parent = context.filesDir.resolve("core-failure-observation").canonicalFile
                check(parent.mkdirs() || parent.isDirectory)
                val directory = parent.resolve("mesh-qualification-" + UUID.randomUUID().toString().replace("-", "")).canonicalFile
                check(directory.parentFile == parent)
                try {
                    val binding = fixture.callAttr("setup", directory.absolutePath).toString()
                    assertTrue(binding.matches(Regex("[a-f0-9]{64}")))
                    val capabilities = JSONObject(CoreApiBridge.typedCommand(context,
                        JSONObject().put("action", "capabilities").put("payload", JSONObject()).toString()))
                    assertTrue(capabilities.getBoolean("ok"))
                    val profile = capabilities.getJSONObject("result").getJSONArray("profiles").getString(0)
                    action(fixture, binding, profile)
                } finally {
                    fixture.callAttr("close")
                    NativeWebRtcBridge.closeAll()
                    check(directory.parentFile == parent)
                    directory.deleteRecursively()
                }
            }.get(90, TimeUnit.SECONDS)
        } finally {
            executor.shutdownNow()
            check(executor.awaitTermination(5, TimeUnit.SECONDS))
        }
    }
    private fun raw(profile: String) = JSONObject().put("action", "request").put("payload", JSONObject()
        .put("operation", "call.ice_servers").put("params", JSONObject().put("profile", profile))
        .put("idempotencyKey", JSONObject.NULL)).toString()
    private fun observed(raw: String, binding: String): JSONObject {
        val entry = Class.forName("com.meshchat.runtime.CoreFailureObservation").getDeclaredMethod("typedCommand",
            Context::class.java, String::class.java, String::class.java).apply { isAccessible = true }
        return JSONObject((entry.invoke(null, context, raw, binding) ?: error("Observation entry returned no reply")).toString())
    }
    private fun internal(reply: JSONObject) {
        assertFalse(reply.getBoolean("ok"))
        assertEquals("internal", reply.getJSONObject("error").getString("code"))
        assertFalse(reply.toString().contains("PRIVATE"))
    }

    @Test fun implicitCapabilitiesFailureUsesOneExistingExchange() = withQualifiedService { fixture, binding, profile ->
        fixture.callAttr("arm", "capabilities")
        val reply = observed(raw(profile), binding)
        internal(reply)
        val selected = reply.getJSONObject("core_failure_observation")
        assertEquals("runtime_capabilities", selected.getString("operation"))
        assertEquals("capabilities", selected.getString("stage"))
        assertEquals("unexpected", selected.getString("category"))
        assertEquals("1", fixture.callAttr("count").toString())
        assertEquals("0", fixture.callAttr("ice_count").toString())
    }

    @Test fun iceFailureUsesTwoExistingExchangesAndPrivateObservation() = withQualifiedService { fixture, binding, profile ->
        fixture.callAttr("arm", "ice")
        val reply = observed(raw(profile), binding)
        internal(reply)
        val selected = reply.getJSONObject("core_failure_observation")
        assertEquals("ice_servers", selected.getString("operation"))
        assertEquals("ice_service", selected.getString("stage"))
        assertEquals("unexpected", selected.getString("category"))
        assertEquals("file_not_found", selected.getString("cause"))
        assertEquals(5, selected.length())
        assertEquals("2", fixture.callAttr("count").toString())
        assertEquals("1", fixture.callAttr("ice_count").toString())
    }

    @Test fun wrongBindingAndPublicEntryOmitObservation() = withQualifiedService { fixture, binding, profile ->
        fixture.callAttr("arm", "ice")
        val publicReply = JSONObject(CoreApiBridge.typedCommand(context, raw(profile)))
        internal(publicReply)
        assertFalse(publicReply.has("core_failure_observation"))
        val wrong = (if (binding[0] == '0') "1" else "0") + binding.drop(1)
        val rejected = observed(raw(profile), wrong)
        internal(rejected)
        assertEquals(publicReply.toString(), rejected.toString())
        assertFalse(rejected.has("core_failure_observation"))
        val selected = observed(raw(profile), binding)
        internal(selected)
        assertTrue(selected.has("core_failure_observation"))
        selected.remove("core_failure_observation")
        assertEquals(publicReply.toString(), selected.toString())
        assertEquals("6", fixture.callAttr("count").toString())
    }

    @Test fun successfulEntryOmitsObservation() = withQualifiedService { fixture, binding, _ ->
        fixture.callAttr("arm", "success")
        val raw = JSONObject().put("action", "capabilities").put("payload", JSONObject()).toString()
        val selected = observed(raw, binding)
        assertTrue(selected.getBoolean("ok"))
        assertFalse(selected.has("core_failure_observation"))
        assertEquals("1", fixture.callAttr("count").toString())
    }

    companion object {
        private val FIXTURE = """
            import json, os, base64
            from mesh_chat import mobile_bridge as mobile
            from mesh_chat.core_api import qualification_host as qualification
            from mesh_chat.core_api.session import CoreSession
            from mesh_chat.service import MeshChatService

            original_execute = CoreSession._execute
            original_capabilities = CoreSession._capabilities
            calls, ice_calls = [], []

            def setup(path):
                close()
                start, lan = MeshChatService._start_network, MeshChatService._prepare_lan_fallback
                try:
                    MeshChatService._start_network = lambda *_: None
                    MeshChatService._prepare_lan_fallback = lambda *_: None
                    reply = json.loads(qualification.android_initialize(json.dumps({
                        'profile_dir': path, 'vault_key': base64.b64encode(os.urandom(32)).decode('ascii'),
                        'display_name': 'Mesh qualification', 'platform': 'android'})))
                    assert reply['ok'] is True
                finally:
                    MeshChatService._start_network, MeshChatService._prepare_lan_fallback = start, lan
                inventory = json.loads(qualification.android_control(json.dumps({
                    'command': 'qualification.inventory', 'payload': {}})))
                assert inventory['ok'] is True
                value = inventory['result']
                assert value['resources'] == [] and value['host_accounting']['complete'] is True
                assert all(value['host_accounting'][name] == 0 for name in (
                    'reserved_count', 'creating_count', 'allocated_count', 'active_count', 'retiring_count'))
                return value['service_incarnation'] + value['profile_incarnation']

            def arm(mode):
                calls.clear(); ice_calls.clear()
                def execute(self, grant, operation, params, key=None):
                    calls.append(operation)
                    return original_execute(self, grant, operation, params, key)
                def capabilities(self, profiles):
                    if mode == 'capabilities': raise OSError('PRIVATE_CAPABILITY_SENTINEL')
                    return original_capabilities(self, profiles)
                def ice():
                    ice_calls.append(True)
                    raise RuntimeError('PRIVATE_DOMAIN_SENTINEL') from FileNotFoundError('PRIVATE_CA_PATH_CREDENTIAL')
                CoreSession._execute, CoreSession._capabilities = execute, capabilities
                if mode == 'ice': mobile._service.call_ice_servers = ice

            def count(): return len(calls)
            def ice_count(): return len(ice_calls)
            def close():
                CoreSession._execute, CoreSession._capabilities = original_execute, original_capabilities
                reply = json.loads(mobile.shutdown())
                assert reply.get('ok') is True
        """.trimIndent()
    }
}
