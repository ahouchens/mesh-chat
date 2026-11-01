package com.meshchat.runtime.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private val PROFILE = "p".repeat(64)
private val PEER = "q".repeat(64)

private class Scripted(vararg frames: String?) : CoreTransport {
    private val inbox = ArrayDeque(frames.toList())
    val written = mutableListOf<String>()
    var closed = false

    override fun readLine(): String? = inbox.removeFirstOrNull()

    override fun writeLine(line: String) {
        written.add(line)
    }

    override fun close() {
        closed = true
    }
}

private fun success(requestId: String, result: JSONObject): String =
    JSONObject()
        .put("api_version", 1)
        .put("request_id", requestId)
        .put("ok", true)
        .put("result", result)
        .toString()

private fun failure(requestId: String, code: String, retry: Long? = null): String =
    JSONObject()
        .put("api_version", 1)
        .put("request_id", requestId)
        .put("ok", false)
        .put("error", JSONObject().put("code", code).put("retry_after_ms", retry ?: JSONObject.NULL))
        .toString()

private fun capabilities(major: Int = 1): JSONObject = JSONObject()
    .put("api_major", major)
    .put("api_minor", 0)
    .put("stability", "experimental")
    .put("operations", org.json.JSONArray(listOf("runtime.capabilities")))
    .put("profiles", org.json.JSONArray(listOf(PROFILE)))
    .put("limits", JSONObject().put("frame_bytes", 4194304))

class CoreClientTest {
    @Test
    fun negotiatesOnceAndSerializesTheDeclaredEnvelope() {
        val transport = Scripted(success("client:1", capabilities()))
        val client = CoreClient.open(transport)
        assertEquals(1, client.capabilities.getInt("api_major"))
        val sent = JSONObject(transport.written.single())
        assertEquals(1, sent.getInt("api_version"))
        assertEquals("client:1", sent.getString("request_id"))
        assertEquals("runtime.capabilities", sent.getString("operation"))
        assertEquals(0, sent.getJSONObject("params").length())
    }

    @Test
    fun refusesAnUnsupportedMajorAndCloses() {
        val transport = Scripted(success("client:1", capabilities(major = 2)))
        val error = runCatching { CoreClient.open(transport) }.exceptionOrNull()
        assertTrue(error is CoreException)
        assertEquals("incompatible_version", (error as CoreException).code)
        assertTrue(transport.closed)
    }

    @Test
    fun mapsTypedErrorsWithTheirRetryHint() {
        val transport = Scripted(
            success("client:1", capabilities()),
            failure("client:2", "resync_required", 1500),
        )
        val client = CoreClient.open(transport)
        val error = runCatching { client.profileQuery(PROFILE) }.exceptionOrNull()
        assertTrue(error is CoreException)
        assertEquals("resync_required", (error as CoreException).code)
        assertEquals(1500L, error.retryAfterMs)
    }

    @Test
    fun mutationsCarryOnlyTheirCallerKeyAndHelpersUseTheContract() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success("client:2", JSONObject().put("accepted", true)),
            success("client:3", JSONObject().put("stopping", true).put("already_stopping", false)),
        )
        val client = CoreClient.open(transport)
        client.enqueue(PROFILE, PEER, "hello", "k".repeat(16))
        client.stopRuntime()
        val enqueue = JSONObject(transport.written[1])
        assertEquals("message.enqueue", enqueue.getString("operation"))
        assertEquals("k".repeat(16), enqueue.getString("idempotency_key"))
        assertEquals(PEER, enqueue.getJSONObject("params").getString("recipient"))
        val stop = JSONObject(transport.written[2])
        assertEquals("runtime.stop", stop.getString("operation"))
        assertFalse(stop.has("idempotency_key"))
        assertEquals(0, stop.getJSONObject("params").length())
    }

    @Test
    fun shortKeysAndEmptyPairingDocumentsAreRefusedBeforeDispatch() {
        val transport = Scripted(success("client:1", capabilities()))
        val client = CoreClient.open(transport)
        assertTrue(runCatching { client.enqueue(PROFILE, PEER, "x", "short") }.exceptionOrNull()
            is IllegalArgumentException)
        val error = runCatching { client.pairingAccept(PROFILE, "") }.exceptionOrNull()
        assertTrue(error is CoreException)
        assertEquals("invalid_request", (error as CoreException).code)
        assertEquals(1, transport.written.size)
    }

    @Test
    fun privateChannelCreationCarriesVisibilityAndMembers() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success(
                "client:2",
                JSONObject().put("profile", PROFILE).put("workspace", "w".repeat(64))
                    .put("channel", "c".repeat(64)).put("name", "Secret")
                    .put("visibility", "private"),
            ),
        )
        val client = CoreClient.open(transport)
        client.workspaceChannelCreate(
            PROFILE, "w".repeat(64), "Secret", "k".repeat(16),
            visibility = "private", members = listOf("m".repeat(64)),
        )
        val params = JSONObject(transport.written[1]).getJSONObject("params")
        assertEquals("private", params.getString("visibility"))
        assertEquals("m".repeat(64), params.getJSONArray("members").getString(0))
        assertTrue(
            runCatching {
                client.workspaceChannelCreate(
                    PROFILE, "w".repeat(64), "Bad", "k".repeat(16),
                    visibility = "private",
                )
            }.exceptionOrNull() is CoreException,
        )
    }
}
