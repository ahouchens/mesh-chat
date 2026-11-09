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
    fun callRecoveryRequiresCapabilitiesAndPreservesExplicitAbandonKey() {
        val unsupported = Scripted(success("client:1", capabilities()))
        val oldClient = CoreClient.open(unsupported)
        val error = runCatching { oldClient.callOperationAbandon(PROFILE, PEER, "explicit-abandon-key00") }.exceptionOrNull()
        assertEquals("unsupported_operation", (error as CoreException).code)
        assertEquals(1, unsupported.written.size)
        val caps = capabilities().put("api_minor", 1).put("operations", org.json.JSONArray(listOf(
            "call.operation_list", "call.operation_query", "call.operation_abandon")))
        for (name in listOf("call_operations_per_caller_profile", "call_operations_per_vault", "call_operation_retention_seconds",
                "call_operation_keys_per_caller_profile", "call_operation_keys_per_vault")) caps.getJSONObject("limits").put(name, 256)
        val transport = Scripted(success("client:1", caps), success("client:2", JSONObject()))
        val client = CoreClient.open(transport)
        assertTrue(runCatching { client.callOperationAbandon(PROFILE, PEER, "bad") }.isFailure)
        assertEquals(1, transport.written.size)
        client.callOperationAbandon(PROFILE, PEER, "explicit-abandon-key00")
        val frame = JSONObject(transport.written[1])
        assertEquals("explicit-abandon-key00", frame.getString("idempotency_key"))
        assertEquals(PEER, frame.getJSONObject("params").getString("operation"))
        assertEquals(2, transport.written.size)
    }

    @Test
    fun malformedMajorNeverCoercesToSupportedVersion() {
        for (major in listOf<Any>("1", 1.5, true)) {
            val transport = Scripted(success("client:1", capabilities().put("api_major", major)))
            val error = runCatching { CoreClient.open(transport) }.exceptionOrNull()
            assertEquals("incompatible_version", (error as CoreException).code)
            assertTrue(transport.closed)
            assertEquals(1, transport.written.size)
        }
    }

    @Test
    fun explicitGroupKeyRequiresFeatureAndPreservesLegacyNoKeyCall() {
        val transport = Scripted(success("client:1", capabilities()), success("client:2", JSONObject()))
        val client = CoreClient.open(transport)
        val error = runCatching { client.createGroup(PROFILE, "Title", "members", listOf(PEER), "explicit-group-key-0001") }.exceptionOrNull()
        assertEquals("unsupported_operation", (error as CoreException).code)
        assertEquals(1, transport.written.size)
        client.createGroup(PROFILE, "Title", "members", listOf(PEER))
        assertFalse(JSONObject(transport.written[1]).has("idempotency_key"))
    }

    @Test
    fun missingComposerCapabilityRejectsBeforeAnyMutationFrame() {
        val transport = Scripted(success("client:1", capabilities()))
        val client = CoreClient.open(transport)
        val error = runCatching { client.enqueueDraft(PROFILE, PEER, "a".repeat(64)) }.exceptionOrNull()
        assertEquals("unsupported_operation", (error as CoreException).code)
        assertEquals(1, transport.written.size)
    }

    @Test
    fun composerSerializesIssuedKeysAndExplicitNullRevision() {
        val caps = capabilities().put("api_minor", 1).put("operations", org.json.JSONArray(listOf(
            "peer.composer_query", "peer.composer_update", "message.enqueue_draft")))
        val limits = caps.getJSONObject("limits")
        for (name in listOf("composer_text_utf8_bytes", "composers_per_caller_profile", "composers_per_vault",
                "composer_update_idempotency_seconds", "composer_update_keys_per_caller_profile", "composer_update_keys_per_vault",
                "composer_send_idempotency_seconds", "composer_send_keys_per_caller_profile", "composer_send_keys_per_vault")) {
            limits.put(name, 16384)
        }
        val transport = Scripted(success("client:1", caps), success("client:2", JSONObject()), success("client:3", JSONObject()))
        val client = CoreClient.open(transport)
        client.composerUpdate(PROFILE, PEER, null, "draft", "b".repeat(64))
        client.enqueueDraft(PROFILE, PEER, "a".repeat(64))
        val update = JSONObject(transport.written[1])
        assertEquals("b".repeat(64), update.getString("idempotency_key"))
        assertTrue(update.getJSONObject("params").isNull("expected_revision"))
        val enqueue = JSONObject(transport.written[2])
        assertEquals("a".repeat(64), enqueue.getString("idempotency_key"))
        assertFalse(enqueue.getJSONObject("params").has("text"))
    }

    @Test
    fun hostAdmissionErrorsKeepTheirCodeAndCloseTheUncorrelatedSession() {
        for (code in listOf("forbidden", "invalid_request", "resource_exhausted", "unavailable")) {
            val rejection = JSONObject(failure("ignored", code)).put("request_id", JSONObject.NULL).toString()
            val transport = Scripted(success("client:1", capabilities()), rejection)
            val client = CoreClient.open(transport)
            val error = runCatching { client.profileQuery(PROFILE) }.exceptionOrNull()
            assertTrue(error is CoreException)
            assertEquals(code, (error as CoreException).code)
            assertTrue(transport.closed)
            val next = runCatching { client.profileQuery(PROFILE) }.exceptionOrNull()
            assertEquals("transport_closed", (next as CoreException).code)
            assertEquals(2, transport.written.size)
        }
    }

    @Test
    fun uncorrelatedSuccessOrDomainResultsCannotBeAccepted() {
        val replies = listOf(
            JSONObject(success("ignored", JSONObject())).put("request_id", JSONObject.NULL),
            JSONObject(failure("ignored", "resync_required")).put("request_id", JSONObject.NULL),
            JSONObject(failure("ignored", "unavailable")).apply { remove("request_id") },
            JSONObject(failure("other-request", "unavailable")),
        )
        for (reply in replies) {
            val transport = Scripted(success("client:1", capabilities()), reply.toString())
            val client = CoreClient.open(transport)
            val error = runCatching { client.profileQuery(PROFILE) }.exceptionOrNull()
            assertEquals("protocol", (error as CoreException).code)
            assertTrue(transport.closed)
        }
    }

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
    fun channelUpdateCarriesPostingOverride() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success(
                "client:2",
                JSONObject().put("profile", PROFILE).put("workspace", "w".repeat(64))
                    .put("channel", "c".repeat(64)).put("name", "Renamed")
                    .put("topic", "Ops").put("visibility", "public")
                    .put("posting", "owner_and_admins"),
            ),
        )
        val client = CoreClient.open(transport)
        client.workspaceChannelUpdate(
            PROFILE, "w".repeat(64), "c".repeat(64), "Renamed", "Ops", "e".repeat(16),
            posting = "owner_and_admins",
        )
        val params = JSONObject(transport.written[1]).getJSONObject("params")
        assertEquals("owner_and_admins", params.getString("posting"))
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

    @Test
    fun workspaceInvitationCreateSerializesModeAndI2pOptions() {
        val relay = "a".repeat(52) + ".b32.i2p"
        val transport = Scripted(
            success("client:1", capabilities()),
            success(
                "client:2",
                JSONObject().put("profile", PROFILE).put("workspace", "w".repeat(64))
                    .put("document", "signed").put("link", "meshchat://workspace/example")
                    .put("expires_at", 1234).put("connection_mode", "i2p")
                    .put("i2p_access_point", relay),
            ),
        )
        val client = CoreClient.open(transport)
        val result = client.workspaceInvitationCreate(
            PROFILE, "w".repeat(64), "k".repeat(16), "i2p", relay, "Community relay",
        )
        assertEquals("i2p", result.getString("connection_mode"))
        val request = JSONObject(transport.written[1])
        assertEquals("workspace.invitation_create", request.getString("operation"))
        assertEquals("k".repeat(16), request.getString("idempotency_key"))
        val params = request.getJSONObject("params")
        assertEquals("i2p", params.getString("connection_mode"))
        assertEquals(relay, params.getString("i2p_access_point"))
        assertEquals("Community relay", params.getString("i2p_label"))
        assertTrue(
            runCatching {
                client.workspaceInvitationCreate(PROFILE, "w".repeat(64), "short")
            }.exceptionOrNull() is IllegalArgumentException,
        )
    }

    @Test
    fun workspaceJoinPreservesExplicitCallerKeyAndRefusesMissingKey() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success(
                "client:2",
                JSONObject().put("profile", PROFILE).put("workspace", "w".repeat(64))
                    .put("name", "Core").put("state", "joining"),
            ),
        )
        val client = CoreClient.open(transport)
        assertTrue(runCatching { client.workspaceJoin(PROFILE, "invitation") }.exceptionOrNull() is IllegalArgumentException)
        assertEquals(1, transport.written.size)
        client.workspaceJoin(PROFILE, "invitation", "workspace-join-key-0001")
        val join = JSONObject(transport.written[1])
        assertEquals("workspace.join", join.getString("operation"))
        assertEquals("workspace-join-key-0001", join.getString("idempotency_key"))
    }

    @Test
    fun workspaceAdministrationHelpersEmitDeclaredEnvelopes() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success("client:2", JSONObject().put("profile", PROFILE).put(
                "workspaces", org.json.JSONArray())),
            success("client:3", JSONObject().put("profile", PROFILE)
                .put("workspace", "w".repeat(64)).put("requests", org.json.JSONArray())),
            success("client:4", JSONObject().put("profile", PROFILE)
                .put("workspace", "w".repeat(64)).put("state", "active")),
        )
        val client = CoreClient.open(transport)
        client.workspaceList(PROFILE)
        client.workspaceJoinRequests(PROFILE, "w".repeat(64))
        client.workspaceJoinApprove(
            PROFILE, "w".repeat(64), "r".repeat(64), "k".repeat(16),
        )
        assertEquals("workspace.query", JSONObject(transport.written[1]).getString("operation"))
        assertEquals(
            "workspace.join_requests",
            JSONObject(transport.written[2]).getString("operation"),
        )
        val approve = JSONObject(transport.written[3])
        assertEquals("workspace.join_approve", approve.getString("operation"))
        assertEquals("k".repeat(16), approve.getString("idempotency_key"))
    }

    @Test
    fun connectionAndPeerHelpersEmitDeclaredEnvelopes() {
        val transport = Scripted(
            success("client:1", capabilities()),
            success("client:2", JSONObject().put("profile", PROFILE).put("peer", PEER)
                .put("desired", "enabled").put("active", true)),
            success("client:3", JSONObject().put("profile", PROFILE).put("peer", PEER)
                .put("desired", "stopped").put("active", false)),
            success("client:4", JSONObject().put("profile", PROFILE).put("peer", PEER)
                .put("display_name", "Blair").put("destination", "d".repeat(32))
                .put("trust", "approved")),
            success("client:5", JSONObject().put("profile", PROFILE)),
        )
        val client = CoreClient.open(transport)
        client.connectionStart(PROFILE, PEER)
        client.connectionStop(PROFILE, PEER)
        client.peerQuery(PROFILE, PEER)
        client.connectionSnapshot(PROFILE, "c".repeat(64))
        assertEquals(
            "connection.start",
            JSONObject(transport.written[1]).getString("operation"),
        )
        assertEquals(
            "connection.stop",
            JSONObject(transport.written[2]).getString("operation"),
        )
        assertEquals("peer.query", JSONObject(transport.written[3]).getString("operation"))
        assertEquals(
            "connection.snapshot",
            JSONObject(transport.written[4]).getString("operation"),
        )
        assertFalse(JSONObject(transport.written[1]).has("idempotency_key"))
    }

    @Test
    fun messageQueryAndListEmitDeclaredEnvelopes() {
        val message = JSONObject().put("profile", PROFILE).put("message", "m".repeat(64))
            .put("recipient", PEER).put("kind", "text").put("text", "Hello")
            .put("state", "queued").put("created_at", 1)
        val transport = Scripted(
            success("client:1", capabilities()),
            success("client:2", message),
            success("client:3", JSONObject().put("profile", PROFILE)
                .put("messages", org.json.JSONArray(listOf(message)))
                .put("next_cursor", JSONObject.NULL).put("events_cursor", "c".repeat(64))),
        )
        val client = CoreClient.open(transport)
        client.messageQuery(PROFILE, "m".repeat(64))
        client.messageList(PROFILE, limit = 7)
        assertEquals("message.query", JSONObject(transport.written[1]).getString("operation"))
        val listed = JSONObject(transport.written[2])
        assertEquals("message.list", listed.getString("operation"))
        assertEquals(7, listed.getJSONObject("params").getInt("limit"))
    }
}
