package com.meshchat.runtime.core

import org.json.JSONObject

/**
 * Experimental Kotlin client for the private Mesh Chat Core API.
 *
 * It wraps the versioned frame contract only: no authentication, runtime
 * ownership, retry policy or data directory. Until a supported host binding is
 * packaged, this stays component code and is not a redistribution promise.
 */
class CoreClient private constructor(private val transport: CoreTransport) {
    private var sequence = 0
    private var closed = false

    var capabilities: JSONObject = JSONObject()
        private set

    companion object {
        const val MAX_FRAME_CHARS = 4 * 1024 * 1024
        const val MAX_BATCH = 128
        const val MAX_DIAGNOSTICS = 256

        @JvmStatic
        fun open(transport: CoreTransport): CoreClient {
            val client = CoreClient(transport)
            val capabilities = client.request("runtime.capabilities", JSONObject())
            if (capabilities.optInt("api_major", -1) != 1) {
                client.close()
                throw CoreException("incompatible_version")
            }
            client.capabilities = capabilities
            return client
        }
    }

    /** Send one request and return its selected result object. */
    fun request(operation: String, params: JSONObject = JSONObject()): JSONObject =
        dispatch(operation, params, null)

    private fun dispatch(operation: String, params: JSONObject, key: String?): JSONObject {
        if (closed) throw CoreException("transport_closed")
        val requestId = "client:${(++sequence).toString(36)}"
        val envelope = JSONObject()
            .put("api_version", 1)
            .put("request_id", requestId)
            .put("operation", operation)
            .put("params", params)
        if (key != null) envelope.put("idempotency_key", key)
        val line = envelope.toString() + "\n"
        if (line.length > MAX_FRAME_CHARS) throw CoreException("invalid_request", requestId)
        transport.writeLine(line)
        return decodeReply(requestId)
    }

    fun profileQuery(profile: String): JSONObject =
        request("profile.query", JSONObject().put("profile", profile))

    fun received(profile: String, cursor: String? = null, limit: Int = MAX_BATCH): JSONObject {
        bounded(limit, MAX_BATCH, "received page")
        return request(
            "message.received",
            JSONObject().put("profile", profile).put("cursor", cursor ?: JSONObject.NULL)
                .put("limit", limit),
        )
    }

    fun enqueue(profile: String, recipient: String, text: String, idempotencyKey: String): JSONObject {
        requireKey(idempotencyKey, "mutations")
        return dispatch(
            "message.enqueue",
            JSONObject().put("profile", profile).put("recipient", recipient)
                .put("kind", "text").put("text", text),
            idempotencyKey,
        )
    }

    fun pollEvents(profile: String, cursor: String? = null, limit: Int = MAX_BATCH): JSONObject {
        bounded(limit, MAX_BATCH, "event page")
        return request(
            "events.poll",
            JSONObject().put("profile", profile).put("cursor", cursor ?: JSONObject.NULL)
                .put("limit", limit),
        )
    }

    fun acknowledge(profile: String, cursor: String, idempotencyKey: String): JSONObject {
        requireKey(idempotencyKey, "acknowledgments")
        return dispatch(
            "events.ack",
            JSONObject().put("profile", profile).put("cursor", cursor),
            idempotencyKey,
        )
    }

    fun diagnostics(profile: String, limit: Int = MAX_DIAGNOSTICS): JSONObject {
        bounded(limit, MAX_DIAGNOSTICS, "diagnostic page")
        return request("diagnostics.query", JSONObject().put("profile", profile).put("limit", limit))
    }

    fun approve(profile: String, peer: String): JSONObject =
        request("peer.approve", JSONObject().put("profile", profile).put("peer", peer))

    fun revoke(profile: String, peer: String): JSONObject =
        request("peer.revoke", JSONObject().put("profile", profile).put("peer", peer))

    fun pairingCreate(profile: String): JSONObject =
        request("peer.pairing_create", JSONObject().put("profile", profile))

    fun pairingRequest(profile: String, peer: String): JSONObject =
        request("peer.pairing_request", JSONObject().put("profile", profile).put("peer", peer))

    fun workspaceChannels(profile: String, workspace: String): JSONObject =
        request("workspace.channels", JSONObject().put("profile", profile).put("workspace", workspace))

    fun workspaceChannelCreate(
        profile: String,
        workspace: String,
        name: String,
        idempotencyKey: String,
    ): JSONObject {
        if (name.isEmpty() || name.length > 64) throw CoreException("invalid_request")
        requireKey(idempotencyKey, "channel creation")
        return dispatch(
            "workspace.channel_create",
            JSONObject().put("profile", profile).put("workspace", workspace).put("name", name),
            idempotencyKey,
        )
    }

    fun workspaceChannelMembers(
        profile: String,
        workspace: String,
        channel: String,
    ): JSONObject = request(
        "workspace.channel_members",
        JSONObject().put("profile", profile).put("workspace", workspace).put("channel", channel),
    )

    fun workspaceChannelMembersUpdate(
        profile: String,
        workspace: String,
        channel: String,
        members: List<String>,
        idempotencyKey: String,
    ): JSONObject {
        if (members.size !in 1..8) throw CoreException("invalid_request")
        requireKey(idempotencyKey, "channel membership")
        return dispatch(
            "workspace.channel_members_update",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel", channel).put("members", org.json.JSONArray(members)),
            idempotencyKey,
        )
    }

    fun workspaceChannelUpdate(
        profile: String,
        workspace: String,
        channel: String,
        name: String,
        topic: String,
        idempotencyKey: String,
    ): JSONObject {
        if (name.isEmpty() || name.length > 64 || topic.length > 1024) {
            throw CoreException("invalid_request")
        }
        requireKey(idempotencyKey, "channel edits")
        return dispatch(
            "workspace.channel_update",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel", channel).put("name", name).put("topic", topic),
            idempotencyKey,
        )
    }

    fun workspaceMembers(profile: String, workspace: String): JSONObject =
        request("workspace.members", JSONObject().put("profile", profile).put("workspace", workspace))

    fun workspaceJoinDecline(
        profile: String,
        workspace: String,
        requestId: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "workspace declines")
        return dispatch(
            "workspace.join_decline",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("request", requestId),
            idempotencyKey,
        )
    }

    fun workspaceMemberRole(
        profile: String,
        workspace: String,
        member: String,
        role: String,
        idempotencyKey: String,
    ): JSONObject {
        if (role != "admin" && role != "member") throw CoreException("invalid_request")
        requireKey(idempotencyKey, "role changes")
        return dispatch(
            "workspace.member_role",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("member", member).put("role", role),
            idempotencyKey,
        )
    }

    fun workspacePreview(profile: String, document: String): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        return request(
            "workspace.invitation_preview",
            JSONObject().put("profile", profile).put("document", document),
        )
    }

    fun workspaceJoin(profile: String, document: String, idempotencyKey: String): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        requireKey(idempotencyKey, "workspace joins")
        return dispatch(
            "workspace.join",
            JSONObject().put("profile", profile).put("document", document),
            idempotencyKey,
        )
    }

    fun pairingAccept(profile: String, document: String): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        return request(
            "peer.pairing_accept",
            JSONObject().put("profile", profile).put("document", document),
        )
    }

    /** Ask the owning host to stop; the stream closes after this reply. */
    fun stopRuntime(): JSONObject = request("runtime.stop", JSONObject())

    fun close() {
        if (!closed) {
            closed = true
            transport.close()
        }
    }



    private fun decodeReply(requestId: String): JSONObject {
        val replyLine = transport.readLine()
            ?: run {
                close()
                throw CoreException("transport_closed", requestId)
            }
        val reply = try {
            JSONObject(replyLine)
        } catch (error: Exception) {
            close()
            throw CoreException("protocol", requestId)
        }
        if (reply.optInt("api_version", -1) != 1 || reply.optString("request_id") != requestId) {
            throw CoreException("protocol", requestId)
        }
        if (!reply.optBoolean("ok", false)) {
            val error = reply.optJSONObject("error")
            val code = error?.optString("code") ?: "protocol"
            val retry = if (error?.has("retry_after_ms") == true && !error.isNull("retry_after_ms")) {
                error.optLong("retry_after_ms")
            } else {
                null
            }
            throw CoreException(code, requestId, retry)
        }
        return reply.optJSONObject("result") ?: throw CoreException("protocol", requestId)
    }

    private fun requireKey(key: String, what: String) {
        if (key.length < 16) throw IllegalArgumentException("$what require a caller-scoped key")
    }

    private fun bounded(limit: Int, maximum: Int, what: String) {
        if (limit < 1 || limit > maximum) throw IllegalArgumentException("$what is outside bounds")
    }
}
