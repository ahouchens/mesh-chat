package com.meshchat.runtime

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Production Tauri typed entry -> Binder -> CoreDispatch -> framed Python session.
 * Fixture setup and assertions inspect private service state. Calls under test use the
 * application entry point, with no replacement Core client or legacy commands.
 */
@RunWith(AndroidJUnit4::class)
class TypedCoreBridgeBoundaryTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext

    private fun withRuntime(seedProfile: Boolean = true, action: (PyObject) -> Unit) {
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
                    fixture.callAttr("setup", directory.absolutePath, seedProfile)
                    action(fixture)
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

    @Test(timeout = 120_000)
    fun typedSettingsMutationsReadBackFromTheRealDomain() = withRuntime { fixture ->
        val handle = profile()
        val network = JSONObject().put("nearby_discovery", false).put("lan_fallback", false)
            .put("help_route", true)
        result(request("settings.update", JSONObject().put("profile", handle).put("settings", network)))
        val read = result(request("settings.query", JSONObject().put("profile", handle)))
        assertTrue(read.getJSONObject("settings").getBoolean("help_route"))
        val calls = JSONObject().put("stun_urls", JSONArray()).put("turn_broker_url", JSONObject.NULL)
            .put("turn_broker_consent", false).put("signal_mailbox_url", JSONObject.NULL)
            .put("relay_only", false).put("store_call_signaling", false)
        result(request("call.settings_update", JSONObject().put("profile", handle).put("settings", calls)))
        val callRead = result(request("call.settings_query", JSONObject().put("profile", handle)))
        assertFalse(callRead.getJSONObject("settings").getBoolean("store_call_signaling"))
        assertTrue(callRead.getJSONObject("settings").isNull("signal_mailbox_url"))
        assertEquals("True", fixture.callAttr("assert_settings_mutated").toString())
    }

    @Test(timeout = 120_000)
    fun typedCallControlSignsQueuesAndEndsAnApprovedCall() = withRuntime { fixture ->
        val handle = profile()
        val fingerprint = "sha-256 " + List(32) { "AB" }.joinToString(":")
        val sdp = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=fingerprint:$fingerprint\r\n"
        val started = result(request("call.control", JSONObject().put("profile", handle)
            .put("action", "start").put("contact_id", "android-call-peer").put("media", "audio")
            .put("sdp", sdp).put("dtls_fingerprint", fingerprint), "android-boundary-call-start-0001"))
            .getJSONObject("result")
        val callId = started.getString("id")
        assertEquals("dialing", started.getString("state"))
        assertEquals("True", fixture.callAttr("assert_call_started", callId).toString())
        val ended = result(request("call.control", JSONObject().put("profile", handle)
            .put("action", "end").put("call_id", callId).put("reason", "completed"),
            "android-boundary-call-end-0001")).getJSONObject("result")
        assertEquals(callId, ended.getString("id"))
        assertEquals("ended", ended.getString("state"))
        assertEquals("True", fixture.callAttr("assert_call_ended", callId).toString())
    }

    @Test(timeout = 120_000)
    fun typedFreshProfileBootstrapDoesNotSeedIdentity() = withRuntime(false) { fixture ->
        assertEquals("True", fixture.callAttr("assert_profile_absent").toString())
        result(exchange("capabilities"))
        fixture.callAttr("capture_preview_state")
        val preview = result(request("bootstrap.preview", JSONObject().put("kind", "personal")
            .put("document", fixture.callAttr("bootstrap_document").toString())))
        assertEquals("personal", preview.getString("kind"))
        assertEquals("Pre-profile sponsor", preview.getJSONObject("preview").getString("display_name"))
        assertEquals("True", fixture.callAttr("assert_preview_unchanged").toString())
        val params = JSONObject().put("display_name", "Fresh Android owner")
        val key = "android-fresh-profile-key-0001"
        val created = result(request("profile.create", params, key))
        val view = result(exchange("profile"))
        assertEquals("Fresh Android owner", view.getString("display_name"))
        val destination = view.getString("destination")
        val identity = fixture.callAttr("profile_identity_hash").toString()
        assertEquals(created.toString(), result(request("profile.create", params, key)).toString())
        val conflict = request("profile.create", JSONObject().put("display_name", "Changed owner"), key)
        assertFalse(conflict.getBoolean("ok"))
        assertEquals("idempotency_conflict", conflict.getJSONObject("error").getString("code"))
        fixture.callAttr("reopen")
        assertEquals(created.toString(), result(request("profile.create", params, key)).toString())
        assertEquals(destination, result(exchange("profile")).getString("destination"))
        assertEquals(identity, fixture.callAttr("profile_identity_hash").toString())
    }

    companion object {
        // No sockets or ordinary app profile. The actual Binder/session path
        // still derives its grant from the calling UID and serializes all calls.
        private val FIXTURE = """
            import os
            import base64
            import RNS
            from pathlib import Path
            from uuid import uuid4
            from mesh_chat import mobile_bridge
            from mesh_chat.core_api.android_host import close_all
            from mesh_chat.service import MeshChatService
            from mesh_chat.vault import VaultStore
            from mesh_chat.reticulum_config import NetworkSettings
            from mesh_chat.webrtc_signaling import verify_call_invite, verify_call_hangup
            from mesh_chat.invitations import create_invitation

            def setup(path, seed_profile=True):
                global fixture_path, fixture_key, effect_calls
                close()
                directory = Path(path)
                fixture_path, fixture_key = directory, os.urandom(32)
                effect_calls = []
                store = VaultStore(directory, fixture_key, allow_unprotected_for_tests=True)
                store.put("settings", "network", NetworkSettings(nearby_discovery=False, lan_fallback=False).to_dict())
                start = MeshChatService._start_network
                lan = MeshChatService._prepare_lan_fallback
                try:
                    MeshChatService._start_network = lambda *_: None
                    MeshChatService._prepare_lan_fallback = lambda *_: None
                    service = MeshChatService(store, directory, lambda _: effect_calls.append("event"))
                    service._start_network = lambda *_: effect_calls.append("start_network")
                    service._prepare_lan_fallback = lambda *_: effect_calls.append("prepare_lan")
                    mobile_bridge._service = service
                    if not seed_profile:
                        return
                    service.create_profile("Typed Android Alex")
                    store.put("contact", "android-boundary-peer", {
                        "id": "android-boundary-peer", "display_name": "Typed Android Blair",
                        "trust": "approved", "destination_hash": "ab" * 16,
                    })
                    peer = RNS.Identity()
                    store.put("contact", "android-call-peer", {
                        "id": "android-call-peer", "display_name": "Approved call fixture",
                        "trust": "approved", "destination_hash": RNS.Destination.hash(peer, "lxmf", "delivery").hex(),
                        "identity_hash": peer.hash.hex(),
                        "public_identity": base64.b64encode(peer.get_public_key()).decode("ascii"),
                    })
                    service.create_workspace(str(uuid4()), "Typed Android Team", "")
                finally:
                    MeshChatService._start_network = start
                    MeshChatService._prepare_lan_fallback = lan

            def close():
                close_all()
                mobile_bridge.shutdown()

            def reopen():
                close()
                start = MeshChatService._start_network
                lan = MeshChatService._prepare_lan_fallback
                try:
                    MeshChatService._start_network = lambda *_: None
                    MeshChatService._prepare_lan_fallback = lambda *_: None
                    store = VaultStore(fixture_path, fixture_key, allow_unprotected_for_tests=True)
                    mobile_bridge._service = MeshChatService(store, fixture_path, lambda _: None)
                    mobile_bridge._service._start_network = lambda *_: None
                    mobile_bridge._service._prepare_lan_fallback = lambda *_: None
                finally:
                    MeshChatService._start_network = start
                    MeshChatService._prepare_lan_fallback = lan

            def assert_profile_absent():
                service = mobile_bridge._service
                assert service.store.get("profile", "local") is None
                assert service.store.get("identity", "local") is None
                assert service._identity is None
                return True

            def profile_identity_hash():
                service = mobile_bridge._service
                assert len(service.store.list("identity")) == len(service.store.list("profile")) == 1
                return service.store.get("profile", "local")["identity_hash"]

            def bootstrap_document():
                return create_invitation(RNS.Identity(), "Pre-profile sponsor")["file"]

            def capture_preview_state():
                global preview_changes, preview_effects
                assert_profile_absent()
                preview_changes = mobile_bridge._service.store._db.total_changes
                preview_effects = list(effect_calls)

            def assert_preview_unchanged():
                assert_profile_absent()
                service = mobile_bridge._service
                assert service.store._db.total_changes == preview_changes
                assert effect_calls == preview_effects
                assert not service.store.list("contact") and not service.store.list("message")
                return True

            def assert_settings_mutated():
                service = mobile_bridge._service
                assert service.settings.help_route is True
                assert service.store.get("settings", "network")["help_route"] is True
                assert service.call_settings()["store_call_signaling"] is False
                assert service.call_settings()["signal_mailbox_url"] is None
                assert service.store.get("call_settings", "default")["store_call_signaling"] is False
                assert service.store.get("call_settings", "default")["signal_mailbox_url"] is None
                return True

            def assert_call_started(call_id):
                service = mobile_bridge._service
                contact = service.store.get("contact", "android-call-peer")
                assert contact["trust"] == "approved"
                record = service.store.get("call", call_id)
                assert record["state"] == "dialing" and record["media"] == "audio"
                invite = verify_call_invite(record["invite"], expected_callee_destination=contact["destination_hash"])
                assert invite.call_id == call_id
                assert invite.caller_destination == service._require_profile()["destination_hash"]
                messages = [row for row in service.store.list("message") if row["kind"] == "call_signal"]
                assert len(messages) == 1 and messages[0]["text"] == record["invite"]
                assert messages[0]["state"] != "delivered"
                return True

            def assert_call_ended(call_id):
                service = mobile_bridge._service
                assert service.store.get("call", call_id)["state"] == "ended"
                messages = [row for row in service.store.list("message") if row["kind"] == "call_signal"]
                assert len(messages) == 2
                hangups = [row for row in messages if row["text"] != service.store.get("call", call_id)["invite"]]
                assert len(hangups) == 1
                hangup = verify_call_hangup(hangups[0]["text"], call_id=call_id,
                    expected_signer_destination=service._require_profile()["destination_hash"])
                assert hangup.reason == "completed" and hangups[0]["state"] != "delivered"
                return True
        """.trimIndent()
    }
}
