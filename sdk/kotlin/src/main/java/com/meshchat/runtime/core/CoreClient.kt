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
        private val REQUIRED_KEYS = setOf("call.control", "call.operation_abandon","connection.retry","events.ack","message.enqueue","message.enqueue_draft","peer.composer_update","profile.create","profile.lock","profile.select","profile.unlock","remote_profile.mutate","route.update","runtime.mutate","workspace.admin_request_approve","workspace.admin_request_cancel","workspace.admin_request_decline","workspace.admin_request_dismiss","workspace.admin_request_submit","workspace.admission_grant_accept","workspace.admission_grant_create","workspace.admission_grant_end","workspace.admission_grant_list","workspace.authority_accept","workspace.authority_finalize","workspace.authority_loss_report","workspace.authority_offer","workspace.channel_archive","workspace.channel_create","workspace.channel_members_update","workspace.channel_recover","workspace.channel_state","workspace.channel_transfer_accept","workspace.channel_transfer_offer","workspace.channel_update","workspace.close","workspace.create","workspace.device_link_approve","workspace.device_link_create","workspace.device_link_decline","workspace.device_link_submit","workspace.device_remove","workspace.direct_open","workspace.display_name_decide","workspace.display_name_request","workspace.draft_set","workspace.invitation_create","workspace.invitation_revoke","workspace.join","workspace.join_approve","workspace.join_decline","workspace.join_prompt","workspace.leave","workspace.member_remove","workspace.member_role","workspace.metadata_update","workspace.policy_update","workspace.read_hint_sync","workspace.remove_data","workspace.retention_update","workspace.timeline_mutation")
        private val KEYED_ACTIONS = mapOf("workspace.connection" to setOf("invite_contact","prompt_dismiss","prompt_submit","reconnect_consent"),"workspace.history" to setOf("cancel","hide_direct","hide_message","prune","start"),"workspace.access_recommendation" to setOf("apply","apply_by_id","create","send"))
        const val VERSION = "0.3.0-experimental"
        const val MAX_FRAME_CHARS = 4 * 1024 * 1024
        const val MAX_BATCH = 128
        const val MAX_DIAGNOSTICS = 256

        @JvmStatic
        fun open(transport: CoreTransport): CoreClient {
            val client = CoreClient(transport)
            val capabilities = client.request("runtime.capabilities", JSONObject())
            val major = capabilities.opt("api_major")
            if (major !is Number || major.toDouble() != 1.0) {
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

    fun request(operation: String, params: JSONObject, idempotencyKey: String): JSONObject =
        dispatch(operation, params, idempotencyKey)

    private fun dispatch(operation: String, params: JSONObject, key: String?): JSONObject {
        if (closed) throw CoreException("transport_closed")
        if (key != null || operation in REQUIRED_KEYS || params.optString("action") in (KEYED_ACTIONS[operation] ?: emptySet())) {
            require(key != null && Regex("[A-Za-z0-9._:-]{16,128}").matches(key)) {
                "operation requires a caller-provided idempotency key"
            }
        }
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

    fun nativeCommand(command: String, payload: JSONObject = JSONObject()): JSONObject =
        request("native.command", JSONObject().put("command", command).put("payload", payload))

    fun applicationSnapshot(): JSONObject = request("application.snapshot", JSONObject())

    private fun requireProfileRuntime() {
        val operations = capabilities.optJSONArray("operations") ?: throw CoreException("unsupported_operation")
        val supported = (0 until operations.length()).map { operations.optString(it) }.toSet()
        val limits = capabilities.optJSONObject("limits") ?: throw CoreException("unsupported_operation")
        val names = listOf("profile_slots", "profile_lifecycle_keys_per_host", "profile_lifecycle_keys_per_caller_profile", "profile_unlock_credentials")
        val minor = capabilities.opt("api_minor")
        if (minor !is Number || minor.toDouble() < 1 || !minor.toDouble().isFinite() || minor.toDouble() % 1.0 != 0.0 ||
            !supported.containsAll(listOf("profile.catalog", "profile.lock", "profile.select", "profile.unlock")) ||
            names.any { name -> val value = limits.opt(name); value !is Number || !value.toDouble().isFinite() ||
                value.toDouble() <= 0 || value.toDouble() > 9007199254740991.0 || value.toDouble() % 1.0 != 0.0 }) throw CoreException("unsupported_operation")
    }

    fun profileCatalog(): JSONObject { requireProfileRuntime(); return request("profile.catalog", JSONObject()) }
    fun lockProfile(profile: String, idempotencyKey: String): JSONObject {
        requireProfileRuntime(); return dispatch("profile.lock", JSONObject().put("profile", profile), idempotencyKey)
    }
    fun selectProfile(profile: String, idempotencyKey: String): JSONObject {
        requireProfileRuntime(); return dispatch("profile.select", JSONObject().put("profile", profile), idempotencyKey)
    }
    fun unlockProfile(profile: String, credentialHandle: String, idempotencyKey: String): JSONObject {
        requireProfileRuntime(); return dispatch("profile.unlock", JSONObject().put("profile", profile).put("credential_handle", credentialHandle), idempotencyKey)
    }

    private fun requireCallRecovery() {
        val operations = capabilities.optJSONArray("operations") ?: throw CoreException("unsupported_operation")
        val supported = (0 until operations.length()).map { operations.optString(it) }.toSet()
        val limits = capabilities.optJSONObject("limits") ?: throw CoreException("unsupported_operation")
        val names = listOf("call_operations_per_caller_profile", "call_operations_per_vault", "call_operation_retention_seconds",
            "call_operation_keys_per_caller_profile", "call_operation_keys_per_vault")
        val minor = capabilities.opt("api_minor")
        if (minor !is Number || minor.toDouble() < 1 || !minor.toDouble().isFinite() || minor.toDouble() % 1.0 != 0.0 ||
            !supported.containsAll(listOf("call.operation_list", "call.operation_query", "call.operation_abandon")) ||
            names.any { name -> val value = limits.opt(name); value !is Number || !value.toDouble().isFinite() ||
                value.toDouble() <= 0 || value.toDouble() > 9007199254740991.0 || value.toDouble() % 1.0 != 0.0 }) throw CoreException("unsupported_operation")
    }

    fun callOperationList(profile: String): JSONObject {
        requireCallRecovery(); return request("call.operation_list", JSONObject().put("profile", profile))
    }
    fun callOperationQuery(profile: String, operation: String): JSONObject {
        requireCallRecovery(); return request("call.operation_query", JSONObject().put("profile", profile).put("operation", operation))
    }
    fun callOperationAbandon(profile: String, operation: String, idempotencyKey: String): JSONObject {
        requireCallRecovery(); return dispatch("call.operation_abandon", JSONObject().put("profile", profile).put("operation", operation), idempotencyKey)
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

    fun unblock(profile: String, peer: String): JSONObject =
        request("peer.unblock", JSONObject().put("profile", profile).put("peer", peer))

    @JvmOverloads
    fun createGroup(profile: String, title: String, postingPolicy: String,
                    members: List<String>, idempotencyKey: String? = null): JSONObject {
        val params = JSONObject().put("profile", profile).put("title", title)
            .put("posting_policy", postingPolicy).put("members", JSONArray(members))
        if (idempotencyKey == null) return request("group.create", params)
        requireOptionalKeyed("group.create")
        return dispatch("group.create", params, idempotencyKey)
    }

    private fun requireOptionalKeyed(operation: String) {
        val operations = capabilities.optJSONArray("optional_keyed_operations") ?: throw CoreException("unsupported_operation")
        val implemented = capabilities.optJSONArray("operations") ?: throw CoreException("unsupported_operation")
        val limits = capabilities.optJSONObject("limits") ?: throw CoreException("unsupported_operation")
        val minor = capabilities.opt("api_minor")
        if (minor !is Number || !minor.toDouble().isFinite() || minor.toDouble() < 1 || minor.toDouble() % 1.0 != 0.0 ||
            !(0 until operations.length()).any { operations.optString(it) == operation } ||
            !(0 until implemented.length()).any { implemented.optString(it) == operation } ||
            listOf("optional_key_idempotency_seconds", "optional_keys_per_caller_profile", "optional_keys_per_vault").any { name ->
                val value = limits.opt(name); value !is Number || !value.toDouble().isFinite() || value.toDouble() <= 0 ||
                    value.toDouble() > 9007199254740991.0 || value.toDouble() % 1.0 != 0.0 }) throw CoreException("unsupported_operation")
    }

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

    @JvmOverloads
    fun sendGroup(profile: String, group: String, text: String, idempotencyKey: String? = null): JSONObject {
        val params = JSONObject().put("profile", profile).put("group", group).put("text", text)
        if (idempotencyKey == null) return request("group.message_enqueue", params)
        requireOptionalKeyed("group.message_enqueue")
        return dispatch("group.message_enqueue", params, idempotencyKey)
    }

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

    fun composerQuery(profile: String, peer: String, sendRevision: String? = null): JSONObject {
        requireComposer()
        val params = JSONObject().put("profile", profile).put("peer", peer)
        if (sendRevision != null) params.put("send_revision", sendRevision)
        return request("peer.composer_query", params)
    }

    fun composerUpdate(profile: String, peer: String, expectedRevision: String?, text: String, updateKey: String): JSONObject {
        requireComposer()
        require(text.toByteArray(Charsets.UTF_8).size <= capabilities.getJSONObject("limits").getLong("composer_text_utf8_bytes")) {
            "composer text exceeds negotiated byte limit"
        }
        return dispatch("peer.composer_update", JSONObject().put("profile", profile).put("peer", peer)
            .put("expected_revision", expectedRevision ?: JSONObject.NULL).put("text", text), updateKey)
    }

    fun enqueueDraft(profile: String, recipient: String, draftRevision: String): JSONObject {
        requireComposer()
        return dispatch("message.enqueue_draft", JSONObject().put("profile", profile).put("recipient", recipient)
            .put("draft_revision", draftRevision), draftRevision)
    }

    private fun requireComposer() {
        val operations = capabilities.optJSONArray("operations") ?: throw CoreException("unsupported_operation")
        val supported = (0 until operations.length()).map { operations.optString(it) }.toSet()
        val limits = capabilities.optJSONObject("limits") ?: throw CoreException("unsupported_operation")
        val names = listOf("composer_text_utf8_bytes", "composers_per_caller_profile", "composers_per_vault",
            "composer_update_idempotency_seconds", "composer_update_keys_per_caller_profile", "composer_update_keys_per_vault",
            "composer_send_idempotency_seconds", "composer_send_keys_per_caller_profile", "composer_send_keys_per_vault")
        val minor = capabilities.opt("api_minor")
        if (minor !is Number || minor.toDouble() < 1 || !minor.toDouble().isFinite() || minor.toDouble() % 1.0 != 0.0 || !supported.containsAll(
                listOf("peer.composer_query", "peer.composer_update", "message.enqueue_draft")) ||
                names.any { name -> val value = limits.opt(name); value !is Number ||
                    !value.toDouble().isFinite() || value.toDouble() <= 0 || value.toDouble() > 9007199254740991.0 ||
                    value.toDouble() % 1.0 != 0.0 }) throw CoreException("unsupported_operation")
    }

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

    fun remoteProfiles(profile: String): JSONObject =
        dispatch("remote_profile.query", JSONObject().put("profile", profile), null)

    fun createWorkspace(profile: String, name: String, description: String,
                        idempotencyKey: String): JSONObject =
        dispatch("workspace.create", JSONObject().put("profile", profile)
            .put("name", name).put("description", description), idempotencyKey)

    fun createProfile(displayName: String): JSONObject =
        dispatch("profile.create", JSONObject().put("display_name", displayName), null)

    fun workspaceJoinPrompt(profile: String, prompt: String,
                            idempotencyKey: String): JSONObject =
        dispatch("workspace.join_prompt", JSONObject().put("profile", profile)
            .put("prompt", prompt), idempotencyKey)

    fun pairingPreview(profile: String, document: String): JSONObject =
        dispatch("peer.pairing_preview", JSONObject().put("profile", profile)
            .put("document", document), null)

    fun connectionDocument(profile: String, action: String, params: JSONObject): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("connection.document", payload, null)
    }

    fun connectionSupport(profile: String, action: String, params: JSONObject): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("connection.support", payload, null)
    }

    fun recoveryTransfer(profile: String, action: String, params: JSONObject): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("recovery.transfer", payload, null)
    }

    fun contactInvitation(profile: String, action: String, params: JSONObject): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
        val keys = params.keys()
        while (keys.hasNext()) { val key = keys.next(); payload.put(key, params.get(key)) }
        return dispatch("contact.invitation", payload, null)
    }

    fun linkPreview(profile: String, provider: String, identifier: String): JSONObject =
        dispatch("link.preview", JSONObject().put("profile", profile)
            .put("provider", provider).put("identifier", identifier), null)

    fun conversation(profile: String, action: String, kind: String,
                     targetId: String, extra: JSONObject? = null): JSONObject {
        val payload = JSONObject().put("profile", profile).put("action", action)
            .put("kind", kind).put("target_id", targetId)
        if (extra != null) {
            val keys = extra.keys()
            while (keys.hasNext()) { val key = keys.next(); payload.put(key, extra.get(key)) }
        }
        return dispatch("conversation.mutate", payload, null)
    }

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

    @JvmOverloads
    fun workspaceAdmissionGrantList(profile: String, workspace: String, idempotencyKey: String? = null): JSONObject =
        dispatch("workspace.admission_grant_list",
            JSONObject().put("profile", profile).put("workspace", workspace), idempotencyKey)

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

    @JvmOverloads
    fun workspaceJoin(profile: String, document: String, idempotencyKey: String? = null): JSONObject {
        if (document.isEmpty()) throw CoreException("invalid_request")
        return dispatch(
            "workspace.join",
            JSONObject().put("profile", profile).put("document", document), idempotencyKey,
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
