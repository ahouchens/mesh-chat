package com.meshchat.runtime

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Production Tauri typed entry -> Binder -> CoreDispatch -> framed Python session.
 * Fixture setup alone accesses private service state. Calls under test use the
 * application entry point, with no replacement Core client or legacy commands.
 */
@RunWith(AndroidJUnit4::class)
class TypedCoreBridgeBoundaryTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext

    private fun withRuntime(action: () -> Unit) {
        val executor = Executors.newSingleThreadExecutor()
        try {
            executor.submit {
                if (!Python.isStarted()) Python.start(AndroidPlatform(context))
                val python = Python.getInstance()
                val fixture = python.getModule("types").callAttr("ModuleType", "typed_core_boundary_fixture")
                python.builtins.callAttr("exec", FIXTURE, fixture.get("__dict__"))
                val parent = context.filesDir.resolve("typed-core-boundary").canonicalFile
                val directory = parent.resolve(UUID.randomUUID().toString()).canonicalFile
                check(directory.parentFile == parent)
                directory.mkdirs()
                try {
                    fixture.callAttr("setup", directory.absolutePath)
                    action()
                } finally {
                    fixture.callAttr("close")
                    check(directory.parentFile == parent)
                    directory.deleteRecursively()
                }
            }.get(90, TimeUnit.SECONDS)
        } finally {
            executor.shutdownNow()
            check(executor.awaitTermination(5, TimeUnit.SECONDS))
        }
    }

    private fun exchange(action: String, payload: JSONObject = JSONObject()): JSONObject =
        JSONObject(CoreApiBridge.typedCommand(context,
            JSONObject().put("action", action).put("payload", payload).toString()))

    private fun result(reply: JSONObject): JSONObject {
        assertTrue("Typed app bridge failed: $reply", reply.getBoolean("ok"))
        return reply.getJSONObject("result")
    }

    private fun request(operation: String, params: JSONObject, key: String? = null): JSONObject =
        exchange("request", JSONObject().put("operation", operation).put("params", params)
            .put("idempotencyKey", key ?: JSONObject.NULL))

    private fun profile(): String = result(exchange("profile")).getString("profile")

    @Test(timeout = 120_000)
    fun typedProfileWorkspaceAndSettingsReachProductionCore() = withRuntime {
        assertEquals(1, result(exchange("capabilities")).getInt("api_major"))
        val handle = profile()
        val snapshot = result(request("application.snapshot", JSONObject()))
        assertEquals("Typed Android Alex", snapshot.getJSONObject("profile").getString("display_name"))
        assertEquals(1, snapshot.getJSONArray("workspaces").length())
        val workspace = result(request("workspace.snapshot", JSONObject().put("profile", handle)))
        assertEquals(1, workspace.getJSONArray("workspaces").length())
        assertTrue(result(request("settings.query", JSONObject().put("profile", handle))).has("settings"))
        assertTrue(result(request("call.settings_query", JSONObject().put("profile", handle))).has("settings"))
        assertTrue(result(request("call.ice_servers", JSONObject().put("profile", handle))).has("ice"))
    }

    @Test(timeout = 120_000)
    fun typedDraftAndLostReplyRetryKeepOneDurableMessage() = withRuntime {
        val destination = "ab".repeat(16)
        result(exchange("draftSet", JSONObject().put("destination", destination).put("text", "Android draft")))
        assertEquals("Android draft", result(exchange("draftGet", JSONObject().put("destination", destination))).getString("text"))
        val payload = JSONObject().put("destination", destination).put("text", "Android durable text")
            .put("idempotencyKey", "android-boundary-lost-reply-0001")
        // Deliberately discard the committed reply, as after an IPC timeout.
        result(exchange("sendMessage", payload))
        val retried = result(exchange("sendMessage", payload))
        val queried = result(request("message.query", JSONObject().put("profile", profile())
            .put("message", retried.getString("message"))))
        assertEquals("Android durable text", queried.getString("text"))
        assertNotEquals("delivered", queried.getString("state"))
        val listed = result(request("message.list", JSONObject().put("profile", profile())
            .put("cursor", JSONObject.NULL).put("limit", 128)))
        assertEquals(1, listed.getJSONArray("messages").length())
    }

    @Test(timeout = 120_000)
    fun typedErrorsPreserveConflictAndCallerAuthority() = withRuntime {
        val payload = JSONObject().put("destination", "ab".repeat(16)).put("text", "First text")
            .put("idempotencyKey", "android-boundary-conflict-0001")
        result(exchange("sendMessage", payload))
        val conflict = exchange("sendMessage", JSONObject(payload.toString()).put("text", "Changed text"))
        assertFalse(conflict.getBoolean("ok"))
        assertEquals("idempotency_conflict", conflict.getJSONObject("error").getString("code"))
        assertTrue(conflict.getJSONObject("error").has("retry_after_ms"))
        val forged = request("message.enqueue", JSONObject().put("profile", profile())
            .put("recipient", "f".repeat(64)).put("kind", "text").put("text", "Forbidden"),
            "android-boundary-forged-peer-0001")
        assertFalse(forged.getBoolean("ok"))
        assertEquals("forbidden", forged.getJSONObject("error").getString("code"))
    }

    companion object {
        // No sockets or ordinary app profile. The actual Binder/session path
        // still derives its grant from the calling UID and serializes all calls.
        private val FIXTURE = """
            import os
            from pathlib import Path
            from uuid import uuid4
            from mesh_chat import mobile_bridge
            from mesh_chat.core_api.android_host import close_all
            from mesh_chat.service import MeshChatService
            from mesh_chat.vault import VaultStore

            def setup(path):
                close()
                directory = Path(path)
                store = VaultStore(directory, os.urandom(32), allow_unprotected_for_tests=True)
                start = MeshChatService._start_network
                lan = MeshChatService._prepare_lan_fallback
                try:
                    MeshChatService._start_network = lambda *_: None
                    MeshChatService._prepare_lan_fallback = lambda *_: None
                    service = MeshChatService(store, directory, lambda _: None)
                    mobile_bridge._service = service
                    service.create_profile("Typed Android Alex")
                    store.put("contact", "android-boundary-peer", {
                        "id": "android-boundary-peer", "display_name": "Typed Android Blair",
                        "trust": "approved", "destination_hash": "ab" * 16,
                    })
                    service.create_workspace(str(uuid4()), "Typed Android Team", "")
                finally:
                    MeshChatService._start_network = start
                    MeshChatService._prepare_lan_fallback = lan

            def close():
                close_all()
                mobile_bridge.shutdown()
        """.trimIndent()
    }
}
