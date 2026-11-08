package com.meshchat.runtime.core

import org.json.JSONArray
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

    fun applicationCommand(command: String, payload: JSONObject = JSONObject()): JSONObject =
        request("application.command", JSONObject().put("command", command).put("payload", payload))

    fun applicationSnapshot(): JSONObject = request("application.snapshot", JSONObject())

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

    fun unblock(profile: String, peer: String): JSONObject =
        request("peer.unblock", JSONObject().put("profile", profile).put("peer", peer))

    fun createGroup(profile: String, title: String, postingPolicy: String,
                    members: List<String>): JSONObject =
        request("group.create", JSONObject().put("profile", profile).put("title", title)
            .put("posting_policy", postingPolicy).put("members", JSONArray(members)))

    fun retryGroupInvitation(profile: String, group: String, member: String): JSONObject =
        request("group.invitation_retry", JSONObject().put("profile", profile)
            .put("group", group).put("member", member))

    fun groupInvitation(profile: String, invitation: String, accept: Boolean): JSONObject =
        request(if (accept) "group.invitation_accept" else "group.invitation_decline",
            JSONObject().put("profile", profile).put("invitation", invitation))

    fun leaveGroup(profile: String, group: String): JSONObject =
        request("group.leave", JSONObject().put("profile", profile).put("group", group))

    fun closeGroup(profile: String, group: String): JSONObject =
        request("group.close", JSONObject().put("profile", profile).put("group", group))

    fun removeGroupMember(profile: String, group: String, member: String): JSONObject =
        request("group.member_remove", JSONObject().put("profile", profile)
            .put("group", group).put("member", member))

    fun sendGroup(profile: String, group: String, text: String): JSONObject =
        request("group.message_enqueue", JSONObject().put("profile", profile)
            .put("group", group).put("text", text))

    fun groups(profile: String): JSONObject =
        request("group.query", JSONObject().put("profile", profile))

    fun reactionSet(profile: String, message: String, emoji: String, active: Boolean): JSONObject =
        request("message.reaction_set", JSONObject().put("profile", profile)
            .put("message", message).put("emoji", emoji).put("active", active))

    fun networkSettings(profile: String): JSONObject =
        request("settings.query", JSONObject().put("profile", profile))

    fun updateNetworkSettings(profile: String, settings: JSONObject): JSONObject =
        request("settings.update", JSONObject().put("profile", profile)
            .put("settings", settings))

    fun callControl(profile: String, action: String, params: JSONObject,
                    idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("call.control", payload, idempotencyKey)
    }

    fun callMedia(profile: String, call: String): JSONObject =
        request("call.media_query", JSONObject().put("profile", profile).put("call", call))

    fun callIceServers(profile: String): JSONObject =
        request("call.ice_servers", JSONObject().put("profile", profile))

    fun callSettingsGet(profile: String): JSONObject =
        request("call.settings_query", JSONObject().put("profile", profile))

    fun callSettingsUpdate(profile: String, settings: JSONObject): JSONObject =
        request("call.settings_update", JSONObject().put("profile", profile)
            .put("settings", settings))

    fun draftGet(profile: String, peer: String): JSONObject =
        request("peer.draft_get", JSONObject().put("profile", profile).put("peer", peer))

    fun draftSet(profile: String, peer: String, text: String): JSONObject =
        request("peer.draft_set", JSONObject().put("profile", profile).put("peer", peer)
            .put("text", text))

    fun deletePeer(profile: String, peer: String): JSONObject =
        request("peer.delete", JSONObject().put("profile", profile).put("peer", peer))

    fun revoke(profile: String, peer: String): JSONObject =
        request("peer.revoke", JSONObject().put("profile", profile).put("peer", peer))

    fun pairingCreate(profile: String, options: JSONObject = JSONObject()): JSONObject =
        request("peer.pairing_create", JSONObject(options.toString()).put("profile", profile))

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
        connectionMode: String? = null,
        i2pAccessPoint: String? = null,
        i2pLabel: String? = null,
    ): JSONObject {
        requireKey(idempotencyKey, "workspace invitations")
        val params = JSONObject().put("profile", profile).put("workspace", workspace)
        if (connectionMode != null) {
            if (connectionMode !in setOf("webrtc", "email", "i2p", "participant")) {
                throw CoreException("invalid_request")
            }
            params.put("connection_mode", connectionMode)
        }
        if (i2pAccessPoint != null) params.put("i2p_access_point", i2pAccessPoint)
        if (i2pLabel != null) params.put("i2p_label", i2pLabel)
        return dispatch("workspace.invitation_create", params, idempotencyKey)
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

    fun workspaceConnection(profile: String, action: String,
                            params: JSONObject = JSONObject(),
                            idempotencyKey: String? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return if (idempotencyKey == null) request("workspace.connection", payload)
        else dispatch("workspace.connection", payload, idempotencyKey)
    }

    fun workspaceHistory(profile: String, workspace: String, action: String,
                         params: JSONObject = JSONObject(),
                         idempotencyKey: String? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return if (idempotencyKey == null) request("workspace.history", payload)
        else dispatch("workspace.history", payload, idempotencyKey)
    }

    fun workspaceAccessRecommendation(profile: String, workspace: String, action: String,
                                      params: JSONObject = JSONObject(),
                                      idempotencyKey: String? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return if (idempotencyKey == null) request("workspace.access_recommendation", payload)
        else dispatch("workspace.access_recommendation", payload, idempotencyKey)
    }

    fun runtimeQuery(profile: String, action: String): JSONObject =
        request("runtime.query", JSONObject().put("profile", profile).put("action", action))

    fun runtimeMutate(profile: String, action: String, params: JSONObject,
                      idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("runtime.mutate", payload, idempotencyKey)
    }

    fun peerDecide(profile: String, peer: String, accept: Boolean): JSONObject =
        dispatch("peer.decide", JSONObject().put("profile", profile)
            .put("peer", peer).put("accept", accept), null)

    fun linkPreview(profile: String, provider: String, identifier: String): JSONObject =
        dispatch("link.preview", JSONObject().put("profile", profile)
            .put("provider", provider).put("identifier", identifier), null)

    fun conversation(profile: String, action: String, kind: String,
                     targetId: String): JSONObject =
        dispatch("conversation.mutate", JSONObject().put("profile", profile)
            .put("action", action).put("kind", kind).put("target_id", targetId), null)

    fun peerUpdate(profile: String, peer: String, action: String,
                   displayName: String? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("peer", peer)
            .put("action", action)
        if (displayName != null) payload.put("display_name", displayName)
        return dispatch("peer.update", payload, null)
    }

    fun routeUpdate(profile: String, action: String, params: JSONObject,
                    idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("route.update", payload, idempotencyKey)
    }

    fun workspaceDirectOpen(profile: String, workspace: String, member: String,
                            idempotencyKey: String): JSONObject =
        dispatch("workspace.direct_open", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("member", member), idempotencyKey)

    fun workspaceDisplayNameDecide(profile: String, workspace: String, request: String,
                                   approve: Boolean, idempotencyKey: String): JSONObject =
        dispatch("workspace.display_name_decide", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("request", request)
            .put("approve", approve), idempotencyKey)

    fun remoteProfile(profile: String, action: String, params: JSONObject,
                      idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("remote_profile.mutate", payload, idempotencyKey)
    }

    fun workspaceDraftSet(profile: String, workspace: String, conversation: String,
                          text: String, idempotencyKey: String,
                          threadRoot: String? = null, mentions: List<String>? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("conversation", conversation).put("text", text)
        if (threadRoot != null) payload.put("thread_root", threadRoot)
        if (!mentions.isNullOrEmpty()) payload.put("mention_member_ids", org.json.JSONArray(mentions))
        return dispatch("workspace.draft_set", payload, idempotencyKey)
    }

    fun groupDraftSet(profile: String, group: String, text: String): JSONObject =
        dispatch("group.draft_set", JSONObject().put("profile", profile)
            .put("group", group).put("text", text), null)

    fun workspaceMemberRemove(profile: String, workspace: String, member: String,
                              idempotencyKey: String): JSONObject =
        dispatch("workspace.member_remove", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("member", member), idempotencyKey)

    fun workspaceChannelState(profile: String, workspace: String, action: String,
                              params: JSONObject, idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("workspace.channel_state", payload, idempotencyKey)
    }

    fun workspaceChannelRecover(profile: String, workspace: String, channel: String,
                                  idempotencyKey: String): JSONObject =
        dispatch("workspace.channel_recover", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("channel", channel), idempotencyKey)

    fun workspaceSnapshot(profile: String): JSONObject =
        request("workspace.snapshot", JSONObject().put("profile", profile))

    fun workspaceTimelineQuery(profile: String, workspace: String, view: String,
                               params: JSONObject = JSONObject()): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("view", view)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return request("workspace.timeline_query", payload)
    }

    fun workspaceTimelineMutation(profile: String, workspace: String, action: String,
                                  params: JSONObject, idempotencyKey: String): JSONObject {
        val payload = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("workspace.timeline_mutation", payload, idempotencyKey)
    }

    fun workspaceInvitationRevoke(profile: String, workspace: String, invitation: String,
                                  idempotencyKey: String): JSONObject =
        dispatch("workspace.invitation_revoke", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("invitation", invitation), idempotencyKey)

    fun workspaceAdmissionGrantList(profile: String, workspace: String): JSONObject =
        request("workspace.admission_grant_list",
            JSONObject().put("profile", profile).put("workspace", workspace))

    fun workspaceAdmissionGrantCreate(profile: String, workspace: String, member: String,
                                      device: String, maxAdmissions: Int, lifetimeDays: Int,
                                      v2Ready: Boolean, idempotencyKey: String): JSONObject =
        dispatch("workspace.admission_grant_create", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("admin_member", member)
            .put("admin_device", device).put("max_admissions", maxAdmissions)
            .put("lifetime_days", lifetimeDays).put("v2_ready", v2Ready), idempotencyKey)

    fun workspaceAdmissionGrantAccept(profile: String, workspace: String, grant: String,
                                      idempotencyKey: String): JSONObject =
        dispatch("workspace.admission_grant_accept", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("grant", grant), idempotencyKey)

    fun workspaceAdmissionGrantEnd(profile: String, workspace: String, grant: String,
                                   idempotencyKey: String): JSONObject =
        dispatch("workspace.admission_grant_end", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("grant", grant), idempotencyKey)

    fun workspaceAuthorityOffer(profile: String, workspace: String, transitionKind: String,
                                successorMember: String, successorDevice: String,
                                outgoingRole: String?, idempotencyKey: String): JSONObject =
        dispatch("workspace.authority_offer", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("transition_kind", transitionKind)
            .put("successor_member", successorMember)
            .put("successor_device", successorDevice)
            .put("outgoing_owner_role", outgoingRole ?: JSONObject.NULL), idempotencyKey)

    fun workspaceAuthorityAccept(profile: String, workspace: String, transition: String,
                                 idempotencyKey: String): JSONObject =
        dispatch("workspace.authority_accept", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("transition", transition), idempotencyKey)

    fun workspaceAuthorityFinalize(profile: String, workspace: String, transition: String,
                                   idempotencyKey: String): JSONObject =
        dispatch("workspace.authority_finalize", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("transition", transition), idempotencyKey)

    fun workspaceReportAuthorityLoss(profile: String, workspace: String,
                                     idempotencyKey: String): JSONObject =
        dispatch("workspace.authority_loss_report", JSONObject().put("profile", profile)
            .put("workspace", workspace), idempotencyKey)

    fun workspaceClose(profile: String, workspace: String, idempotencyKey: String): JSONObject =
        dispatch("workspace.close", JSONObject().put("profile", profile)
            .put("workspace", workspace), idempotencyKey)

    fun workspaceLeave(profile: String, workspace: String, idempotencyKey: String): JSONObject =
        dispatch("workspace.leave", JSONObject().put("profile", profile)
            .put("workspace", workspace), idempotencyKey)

    fun workspaceRemoveData(profile: String, workspace: String, confirmation: String,
                            idempotencyKey: String): JSONObject =
        dispatch("workspace.remove_data", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("confirmation", confirmation), idempotencyKey)

    fun workspaceAdminRequestSubmit(profile: String, workspace: String, requestKind: String,
                                     targetMember: String?, requestedRole: String?,
                                     note: String, idempotencyKey: String): JSONObject {
        val params = JSONObject().put("profile", profile).put("workspace", workspace)
            .put("request_kind", requestKind)
        if (targetMember != null) params.put("target_member", targetMember)
        if (requestedRole != null) params.put("requested_role", requestedRole)
        if (note.isNotEmpty()) params.put("note", note)
        return dispatch("workspace.admin_request_submit", params, idempotencyKey)
    }

    fun workspaceDisplayNameRequest(profile: String, workspace: String, displayName: String,
                                    idempotencyKey: String): JSONObject =
        dispatch("workspace.display_name_request", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("display_name", displayName), idempotencyKey)

    fun workspaceReadHintSync(profile: String, workspace: String, enabled: Boolean,
                              idempotencyKey: String): JSONObject =
        dispatch("workspace.read_hint_sync", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("enabled", enabled), idempotencyKey)

    fun workspaceAdminRequest(profile: String, workspace: String, requestId: String,
                              action: String, idempotencyKey: String): JSONObject {
        val operation = when (action) {
            "approve" -> "workspace.admin_request_approve"
            "decline" -> "workspace.admin_request_decline"
            "cancel" -> "workspace.admin_request_cancel"
            "dismiss" -> "workspace.admin_request_dismiss"
            else -> throw CoreException("invalid_request")
        }
        return dispatch(operation, JSONObject().put("profile", profile)
            .put("workspace", workspace).put("request", requestId), idempotencyKey)
    }

    fun workspaceMetadata(profile: String, workspace: String, name: String,
                           description: String, idempotencyKey: String): JSONObject =
        dispatch("workspace.metadata_update", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("name", name).put("description", description),
            idempotencyKey)

    fun workspaceRetention(profile: String, workspace: String, retentionDays: Int?,
                           idempotencyKey: String): JSONObject =
        dispatch("workspace.retention_update", JSONObject().put("profile", profile)
            .put("workspace", workspace).put("retention_days", retentionDays ?: JSONObject.NULL),
            idempotencyKey)

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

    fun workspaceDeviceRemovalRequest(
        profile: String,
        workspace: String,
        device: String,
        idempotencyKey: String,
    ): JSONObject = dispatch(
        "workspace.device_removal_request",
        JSONObject().put("profile", profile).put("workspace", workspace).put("device", device),
        idempotencyKey,
    )

    fun workspaceDeviceRemovalDecide(
        profile: String,
        workspace: String,
        requestHandle: String,
        approve: Boolean,
        idempotencyKey: String,
    ): JSONObject = dispatch(
        if (approve) "workspace.device_removal_approve"
        else "workspace.device_removal_decline",
        JSONObject().put("profile", profile).put("workspace", workspace)
            .put("request", requestHandle),
        idempotencyKey,
    )

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

    fun pairingAccept(profile: String, document: String, i2pConsent: Boolean = false): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        val params = JSONObject().put("profile", profile).put("document", document)
        if (i2pConsent) params.put("i2p_consent", true)
        return request(
            "peer.pairing_accept",
            params,
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
