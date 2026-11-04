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
        const val VERSION = "0.2.0-experimental"
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

    fun messageQuery(profile: String, message: String): JSONObject = request(
        "message.query",
        JSONObject().put("profile", profile).put("message", message),
    )

    fun messageList(
        profile: String,
        cursor: String? = null,
        limit: Int = 128,
    ): JSONObject {
        if (limit !in 1..128) throw CoreException("invalid_request")
        return request(
            "message.list",
            JSONObject().put("profile", profile)
                .put("cursor", cursor ?: JSONObject.NULL)
                .put("limit", limit),
        )
    }

    fun connectionStart(profile: String, peer: String): JSONObject = request(
        "connection.start",
        JSONObject().put("profile", profile).put("peer", peer),
    )

    fun connectionStop(profile: String, peer: String): JSONObject = request(
        "connection.stop",
        JSONObject().put("profile", profile).put("peer", peer),
    )

    fun connectionSnapshot(profile: String, connection: String): JSONObject = request(
        "connection.snapshot",
        JSONObject().put("profile", profile).put("connection", connection),
    )

    fun peerQuery(profile: String, peer: String): JSONObject = request(
        "peer.query",
        JSONObject().put("profile", profile).put("peer", peer),
    )

    fun workspaceChannels(profile: String, workspace: String): JSONObject =
        request("workspace.channels", JSONObject().put("profile", profile).put("workspace", workspace))

    fun workspaceInvitationCreate(
        profile: String,
        workspace: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "workspace invitations")
        return dispatch(
            "workspace.invitation_create",
            JSONObject().put("profile", profile).put("workspace", workspace),
            idempotencyKey,
        )
    }

    fun workspaceChannelCreate(
        profile: String,
        workspace: String,
        name: String,
        idempotencyKey: String,
        visibility: String = "public",
        members: List<String> = emptyList(),
    ): JSONObject {
        if (name.isEmpty() || name.length > 64) throw CoreException("invalid_request")
        if (visibility != "public" && visibility != "private") {
            throw CoreException("invalid_request")
        }
        if (visibility == "private" && members.size !in 1..8) {
            throw CoreException("invalid_request")
        }
        if (visibility == "public" && members.isNotEmpty()) {
            throw CoreException("invalid_request")
        }
        requireKey(idempotencyKey, "channel creation")
        val params = JSONObject()
            .put("profile", profile)
            .put("workspace", workspace)
            .put("name", name)
            .put("visibility", visibility)
        if (visibility == "private") {
            params.put("members", org.json.JSONArray(members))
        }
        return dispatch("workspace.channel_create", params, idempotencyKey)
    }

    fun workspaceChannelArchive(
        profile: String,
        workspace: String,
        channel: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "channel archive")
        return dispatch(
            "workspace.channel_archive",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel", channel),
            idempotencyKey,
        )
    }

    fun workspaceDeviceLinkCreate(
        profile: String,
        workspace: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "device links")
        return dispatch(
            "workspace.device_link_create",
            JSONObject().put("profile", profile).put("workspace", workspace),
            idempotencyKey,
        )
    }

    fun workspaceDeviceLinkSubmit(
        profile: String,
        document: String,
        idempotencyKey: String,
    ): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        requireKey(idempotencyKey, "device link submission")
        return dispatch(
            "workspace.device_link_submit",
            JSONObject().put("profile", profile).put("document", document),
            idempotencyKey,
        )
    }

    fun workspaceDeviceLinks(profile: String, workspace: String): JSONObject = request(
        "workspace.device_links",
        JSONObject().put("profile", profile).put("workspace", workspace),
    )

    fun workspaceDeviceLinkApprove(
        profile: String,
        workspace: String,
        request: String,
        idempotencyKey: String,
    ): JSONObject = deviceLinkDecision(
        "workspace.device_link_approve", profile, workspace, request, idempotencyKey,
    )

    fun workspaceDeviceLinkDecline(
        profile: String,
        workspace: String,
        request: String,
        idempotencyKey: String,
    ): JSONObject = deviceLinkDecision(
        "workspace.device_link_decline", profile, workspace, request, idempotencyKey,
    )

    private fun deviceLinkDecision(
        operation: String,
        profile: String,
        workspace: String,
        request: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "device-link decisions")
        return dispatch(
            operation,
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("request", request),
            idempotencyKey,
        )
    }

    fun workspaceDeviceLinkPreview(profile: String, document: String): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        return request(
            "workspace.device_link_preview",
            JSONObject().put("profile", profile).put("document", document),
        )
    }

    fun workspaceChannelTransferOffer(
        profile: String,
        workspace: String,
        channel: String,
        member: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "channel transfers")
        return dispatch(
            "workspace.channel_transfer_offer",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel", channel).put("member", member),
            idempotencyKey,
        )
    }

    fun workspaceChannelTransferAccept(
        profile: String,
        workspace: String,
        channel: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "channel transfers")
        return dispatch(
            "workspace.channel_transfer_accept",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel", channel),
            idempotencyKey,
        )
    }

    fun workspacePolicyUpdate(
        profile: String,
        workspace: String,
        channelCreation: String,
        posting: String,
        invitationRequests: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "workspace policies")
        return dispatch(
            "workspace.policy_update",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("channel_creation", channelCreation).put("posting", posting)
                .put("invitation_requests", invitationRequests),
            idempotencyKey,
        )
    }

    fun workspaceDevices(profile: String, workspace: String): JSONObject = request(
        "workspace.devices",
        JSONObject().put("profile", profile).put("workspace", workspace),
    )

    fun workspaceDeviceRemove(
        profile: String,
        workspace: String,
        device: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "device removal")
        return dispatch(
            "workspace.device_remove",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("device", device),
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
        posting: String? = null,
    ): JSONObject {
        if (name.isEmpty() || name.length > 64 || topic.length > 1024) {
            throw CoreException("invalid_request")
        }
        if (posting != null && posting !in setOf("inherit", "all_members", "owner_and_admins")) {
            throw CoreException("invalid_request")
        }
        requireKey(idempotencyKey, "channel edits")
        val params = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("channel", channel).put("name", name).put("topic", topic)
        if (posting != null) params.put("posting", posting)
        return dispatch("workspace.channel_update", params, idempotencyKey)
    }

    fun workspaceList(profile: String): JSONObject =
        request("workspace.query", JSONObject().put("profile", profile))

    fun workspaceJoinRequests(profile: String, workspace: String): JSONObject = request(
        "workspace.join_requests",
        JSONObject().put("profile", profile).put("workspace", workspace),
    )

    fun workspaceJoinApprove(
        profile: String,
        workspace: String,
        requestHandle: String,
        idempotencyKey: String,
    ): JSONObject {
        requireKey(idempotencyKey, "workspace approvals")
        return dispatch(
            "workspace.join_approve",
            JSONObject().put("profile", profile).put("workspace", workspace)
                .put("request", requestHandle),
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

    fun workspaceJoin(profile: String, document: String): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        return request(
            "workspace.join",
            JSONObject().put("profile", profile).put("document", document),
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
        if (reply.optInt("api_version", -1) != 1) {
            close()
            throw CoreException("protocol", requestId)
        }
        if (reply.optString("request_id") != requestId) rejectUncorrelatedReply(reply, requestId)
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

    private fun rejectUncorrelatedReply(reply: JSONObject, requestId: String): Nothing {
        close()
        val code = reply.optJSONObject("error")?.optString("code")
        val admissionFailure = reply.has("request_id") && reply.isNull("request_id") &&
            reply.opt("ok") == false &&
            code in setOf("forbidden", "invalid_request", "resource_exhausted", "unavailable")
        // A host can reject before parsing the request. Preserve that typed
        // failure, but never keep an uncorrelated session open or retry it.
        throw CoreException(if (admissionFailure) checkNotNull(code) else "protocol", requestId)
    }

    private fun requireKey(key: String, what: String) {
        if (key.length < 16) throw IllegalArgumentException("$what require a caller-scoped key")
    }

    private fun bounded(limit: Int, maximum: Int, what: String) {
        if (limit < 1 || limit > maximum) throw IllegalArgumentException("$what is outside bounds")
    }
}
