package com.meshchat.runtime

import org.json.JSONObject
import org.json.JSONTokener

/** Private host adapter. Caller identity and grants are supplied only by Binder. */
internal class CoreHostClient(private val exchange: (ByteArray) -> ByteArray) {
    private var sequence = 0L

    fun request(operation: String, params: JSONObject = JSONObject(), key: String? = null): JSONObject {
        val requestId = "host:${++sequence}"
        val request = JSONObject().put("api_version", 1).put("request_id", requestId)
            .put("operation", operation).put("params", params)
        if (key != null) request.put("idempotency_key", key)
        val frame = (request.toString() + "\n").toByteArray(Charsets.UTF_8)
        if (frame.size > CoreDispatch.MAX_FRAME_BYTES) throw CoreHostFailure("invalid_request")
        val reply = exchange(frame)
        if (reply.isEmpty() || reply.size > CoreDispatch.MAX_FRAME_BYTES || reply.last() != '\n'.code.toByte()) {
            throw CoreHostFailure("protocol")
        }
        val response = try {
            val decoded = Charsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(reply)).toString()
            val tokens = JSONTokener(decoded)
            val value = tokens.nextValue() as? JSONObject ?: throw CoreHostFailure("protocol")
            if (tokens.nextClean() != '\u0000') throw CoreHostFailure("protocol")
            value
        }
            catch (_: Exception) { throw CoreHostFailure("protocol") }
        if (response.opt("api_version") != 1) throw CoreHostFailure("protocol")
        val correlated = response.opt("request_id") == requestId
        if (response.opt("ok") == false) {
            val error = response.optJSONObject("error") ?: throw CoreHostFailure("protocol")
            val code = error.opt("code") as? String ?: throw CoreHostFailure("protocol")
            val admissionFailure = response.has("request_id") && response.isNull("request_id") &&
                code in setOf("forbidden", "invalid_request", "resource_exhausted", "unavailable")
            if (!correlated && !admissionFailure) throw CoreHostFailure("protocol")
            throw CoreHostFailure(error)
        }
        if (!correlated || response.opt("ok") != true) throw CoreHostFailure("protocol")
        return response.optJSONObject("result") ?: throw CoreHostFailure("protocol")
    }
}

internal class CoreHostFailure(val error: JSONObject) : Exception(error.optString("code")) {
    constructor(code: String) : this(JSONObject().put("code", code).put("retry_after_ms", JSONObject.NULL))
}

/** UI conveniences resolve opaque handles through the same caller-scoped session. */
internal class CoreHostCommands(private val client: CoreHostClient) {
    fun execute(action: String, payload: JSONObject): JSONObject = when (action) {
        "capabilities" -> capabilities()
        "profile" -> client.request("profile.query", profileParams())
        "request" -> {
            val operation = payload.getString("operation")
            val advertised = capabilities().getJSONArray("operations")
            if ((0 until advertised.length()).none { advertised.optString(it) == operation }) {
                throw CoreHostFailure("unsupported_operation")
            }
            client.request(operation, payload.getJSONObject("params"),
                if (payload.isNull("idempotencyKey")) null else payload.getString("idempotencyKey"))
        }
        "peer", "draftGet", "draftSet", "sendMessage" -> peerCommand(action, payload)
        else -> throw CoreHostFailure("invalid_request")
    }

    private fun capabilities(): JSONObject {
        val result = client.request("runtime.capabilities")
        if (result.optInt("api_major", -1) != 1) throw CoreHostFailure("incompatible_version")
        return result
    }

    private fun profileParams(): JSONObject {
        val profile = capabilities().optJSONArray("profiles")?.optString(0)
        if (profile.isNullOrEmpty()) throw CoreHostFailure("unavailable")
        return JSONObject().put("profile", profile)
    }

    private fun peerCommand(action: String, payload: JSONObject): JSONObject {
        val params = profileParams()
        val destination = payload.getString("destination")
        val profile = client.request("profile.query", params)
        val peers = profile.getJSONArray("peers")
        val peer = (0 until peers.length()).asSequence().map { peers.getString(it) }.firstOrNull {
            client.request("peer.query", JSONObject(params.toString()).put("peer", it))
                .optString("destination") == destination
        } ?: throw CoreHostFailure("not_found")
        params.put("peer", peer)
        return when (action) {
            "peer" -> params.put("destination", destination)
            "draftGet" -> client.request("peer.draft_get", params)
            "draftSet" -> client.request("peer.draft_set", params.put("text", payload.getString("text")))
            else -> client.request("message.enqueue", JSONObject().put("profile", params.getString("profile"))
                .put("recipient", peer).put("text", payload.getString("text")), payload.getString("idempotencyKey"))
        }
    }
}
