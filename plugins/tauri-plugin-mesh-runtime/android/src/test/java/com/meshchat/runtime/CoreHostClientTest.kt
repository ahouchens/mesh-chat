package com.meshchat.runtime

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CoreHostClientTest {
    private fun reply(request: JSONObject, result: JSONObject) = JSONObject().put("api_version", 1)
        .put("request_id", request.getString("request_id")).put("ok", true).put("result", result)
        .toString().plus("\n").toByteArray(Charsets.UTF_8)

    private fun failure(action: () -> Unit): JSONObject {
        try { action(); fail("Expected typed failure") }
        catch (error: CoreHostFailure) { return error.error }
        throw AssertionError("unreachable")
    }

    @Test fun genericMutationPreservesCoreFieldsAndCallerKeyOnTheWire() {
        val frames = mutableListOf<JSONObject>()
        val client = CoreHostClient { bytes ->
            val request = JSONObject(String(bytes, Charsets.UTF_8)).also { frames.add(it) }
            val result = if (request.getString("operation") == "runtime.capabilities") {
                JSONObject().put("api_major", 1).put("operations", JSONArray().put("workspace.messages"))
            } else JSONObject().put("accepted", true)
            reply(request, result)
        }
        val result = CoreHostCommands(client).execute("request", JSONObject()
            .put("operation", "workspace.messages").put("params", JSONObject()
                .put("conversation", "scoped-conversation").put("thread_root", "scoped-thread"))
            .put("idempotencyKey", "unchanged-caller-key"))
        assertTrue(result.getBoolean("accepted"))
        val sent = frames.last()
        assertEquals("unchanged-caller-key", sent.getString("idempotency_key"))
        assertEquals("scoped-conversation", sent.getJSONObject("params").getString("conversation"))
        assertEquals("scoped-thread", sent.getJSONObject("params").getString("thread_root"))
        assertFalse(sent.has("caller"))
        assertFalse(sent.has("scope"))
    }

    @Test fun destinationCommandsResolveScopedHandlesBeforeSending() {
        val frames = mutableListOf<JSONObject>()
        val client = CoreHostClient { bytes ->
            val request = JSONObject(String(bytes)).also { frames.add(it) }
            val result = when (request.getString("operation")) {
                "runtime.capabilities" -> JSONObject().put("api_major", 1)
                    .put("profiles", JSONArray().put("opaque-profile"))
                "profile.query" -> JSONObject().put("peers", JSONArray().put("opaque-peer"))
                "peer.query" -> JSONObject().put("destination", "peer-destination")
                else -> JSONObject().put("accepted", true)
            }
            reply(request, result)
        }
        val commands = CoreHostCommands(client)
        val payload = JSONObject().put("destination", "peer-destination").put("text", "hello")
            .put("idempotencyKey", "stable-message-key")
        commands.execute("profile", JSONObject())
        assertEquals("opaque-profile", frames.last().getJSONObject("params").getString("profile"))
        assertEquals("opaque-peer", commands.execute("peer", payload).getString("peer"))
        commands.execute("draftGet", payload)
        assertEquals("peer.draft_get", frames.last().getString("operation"))
        commands.execute("draftSet", payload)
        assertEquals("hello", frames.last().getJSONObject("params").getString("text"))
        commands.execute("sendMessage", payload)
        assertEquals("message.enqueue", frames.last().getString("operation"))
        assertEquals(mapOf("profile" to "opaque-profile", "recipient" to "opaque-peer",
            "kind" to "text", "text" to "hello"), frames.last().getJSONObject("params").let { params ->
                params.keys().asSequence().associateWith { params.get(it) }
            })
        assertEquals("stable-message-key", frames.last().getString("idempotency_key"))
    }

    @Test fun errorsKeepRetryAndUnknownOutcomeMetadataWithoutReplaying() {
        var calls = 0
        val client = CoreHostClient { bytes ->
            calls++
            val request = JSONObject(String(bytes))
            JSONObject().put("api_version", 1).put("request_id", request.getString("request_id"))
                .put("ok", false).put("error", JSONObject().put("code", "unavailable")
                    .put("retry_after_ms", 50).put("outcome", "unknown"))
                .toString().plus("\n").toByteArray()
        }
        val error = failure { client.request("message.enqueue", JSONObject(), "stable-message-key") }
        assertEquals("unavailable", error.getString("code"))
        assertEquals(50, error.getInt("retry_after_ms"))
        assertEquals("unknown", error.getString("outcome"))
        assertEquals(1, calls)
    }

    @Test fun admissionFailuresRemainTypedButUncorrelatedSuccessIsRejected() {
        for (code in listOf("forbidden", "resource_exhausted", "unavailable")) {
            val client = CoreHostClient { CoreDispatch.errorFrame(code) }
            assertEquals(code, failure { client.request("runtime.capabilities") }.getString("code"))
        }
        val client = CoreHostClient { reply(JSONObject().put("request_id", "other"), JSONObject()) }
        assertEquals("protocol", failure { client.request("runtime.capabilities") }.getString("code"))
    }

    @Test fun frameBudgetUsesUtf8BytesAndRejectsBeforeExchange() {
        var calls = 0
        val client = CoreHostClient { calls++; byteArrayOf() }
        val text = "\u20ac".repeat(CoreDispatch.MAX_FRAME_BYTES / 2)
        assertEquals("invalid_request", failure { client.request("message.enqueue",
            JSONObject().put("text", text), "stable-message-key") }.getString("code"))
        assertEquals(0, calls)
    }

    @Test fun malformedAndOversizedRepliesCannotMasqueradeAsResults() {
        for (bytes in listOf(
            "not-json\n".toByteArray(),
            "{\"api_version\":1,\"request_id\":\"host:1\",\"ok\":true,\"result\":{}} {}\n".toByteArray(),
            ByteArray(CoreDispatch.MAX_FRAME_BYTES + 1),
        )) {
            assertEquals("protocol", failure { CoreHostClient { bytes }.request("runtime.capabilities") }
                .getString("code"))
        }
    }

    @Test fun unadvertisedOperationsDoNotReachTheMutationBoundary() {
        var calls = 0
        val client = CoreHostClient { bytes ->
            calls++
            reply(JSONObject(String(bytes)), JSONObject().put("api_major", 1).put("operations", JSONArray()))
        }
        val error = failure { CoreHostCommands(client).execute("request", JSONObject()
            .put("operation", "private.inject").put("params", JSONObject())) }
        assertEquals("unsupported_operation", error.getString("code"))
        assertEquals(1, calls)
    }
}
