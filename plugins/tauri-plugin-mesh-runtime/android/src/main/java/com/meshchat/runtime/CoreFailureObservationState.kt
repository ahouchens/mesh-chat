package com.meshchat.runtime

import java.util.concurrent.atomic.AtomicReference
import org.json.JSONObject
import org.json.JSONTokener

/** Selected values only: no Core error, response buffer or exception crosses this boundary. */
internal data class CoreFailureSelection(val operation: String, val stage: String, val category: String, val cause: String) {
    fun json(): JSONObject = JSONObject().put("v", 1).put("operation", operation)
        .put("stage", stage).put("category", category).put("cause", cause)
}

internal object CoreFailureValues {
    val stages = mapOf(
        "runtime.capabilities" to setOf("core_admission", "capabilities", "session_escape", "frame_encode"),
        "call.ice_servers" to setOf("core_admission", "ice_adapter", "ice_service", "ice_return", "ice_view",
            "broker_url", "broker_request", "tls_context", "broker_open", "broker_status", "broker_read",
            "broker_size", "broker_json", "broker_validate", "session_escape", "frame_encode"))
    private val categories = setOf("network_unavailable", "api_internal", "invalid_observation", "validation",
        "storage_unavailable", "unexpected", "response_encoding")
    private val causes = setOf("certificate_verification", "tls_other", "name_resolution", "timeout", "http_error",
        "json_decode", "file_not_found", "permission_denied", "other", "none", "unknown")

    fun select(raw: String?, correlation: CoreFailureCorrelation): CoreFailureSelection? = try {
        if (raw == null || raw.toByteArray(Charsets.UTF_8).size > 1024 || correlation.code != "internal") null
        else {
            val tokens = JSONTokener(raw)
            val value = tokens.nextValue() as? JSONObject
            if (value == null || tokens.nextClean() != '\u0000' || value.keys().asSequence().toSet() !=
                setOf("v", "request_id", "operation", "error_code", "stage", "category", "cause") ||
                value.opt("v") !is Int || value.opt("v") != 1 || value.opt("request_id") != correlation.requestId ||
                !correlation.requestId.matches(Regex("[A-Za-z0-9._:-]{1,80}")) ||
                value.opt("operation") != correlation.operation || value.opt("error_code") != "internal") null
            else {
                val stage = value.opt("stage") as? String
                val category = value.opt("category") as? String
                val cause = value.opt("cause") as? String
                if (stage !in (stages[correlation.operation] ?: emptySet()) || category !in categories || cause !in causes ||
                    ((category == "response_encoding") != (stage == "frame_encode")) ||
                    (category == "invalid_observation" && stage !in setOf("ice_return", "ice_view"))) null
                else CoreFailureSelection(if (correlation.operation == "runtime.capabilities") "runtime_capabilities" else "ice_servers",
                    stage!!, category!!, cause!!).takeIf { it.json().toString().toByteArray(Charsets.UTF_8).size <= 512 }
            }
        }
    } catch (_: Exception) { null }
}

/** Minted only at the existing validated correlated internal-error throw. */
internal data class CoreFailureCorrelation(val requestId: String, val operation: String, val code: String, val client: Any)

/** Current publication identity, not an error registry. At most one serialized typed command is attached. */
internal class CoreObservationPublication {
    private val generation = AtomicReference(Any())
    private val active = AtomicReference<CoreCommandObservation?>(null)
    fun token(): Any = generation.get()
    fun current(token: Any) = generation.get() === token
    fun attach(scope: CoreCommandObservation) {
        active.getAndSet(scope)?.takeIf { it !== scope }?.close()
    }
    fun detach(scope: CoreCommandObservation) { active.compareAndSet(scope, null) }
    fun invalidate() {
        generation.set(Any())
        active.getAndSet(null)?.close()
    }
}

internal class CoreFrameObservation internal constructor(val qualificationBinding: String,
    private val owner: CoreCommandObservation) {
    val sink = AtomicReference<String>(null)
    fun active() = owner.owns(this)
    fun failedDelivery() = owner.close()
}

/** One command, one current frame, one selected failure; all state transitions are bounded and synchronized. */
internal class CoreCommandObservation(val qualificationBinding: String) {
    private enum class State { OPEN, SELECTED, CLOSED }
    private var state = State.OPEN
    private var publication: CoreObservationPublication? = null
    private var generation: Any? = null
    private var client: Any? = null
    private var binder: Any? = null
    private var frame: CoreFrameObservation? = null
    private var selected: CoreFailureSelection? = null

    @Synchronized fun bind(publication: CoreObservationPublication, token: Any, client: Any, binder: Any, local: Boolean) {
        if (state != State.OPEN) return
        if (!local || !publication.current(token) || !qualificationBinding.matches(Regex("[a-f0-9]{64}")) || this.publication != null) { close(); return }
        this.publication = publication
        generation = token
        this.client = client
        this.binder = binder
        publication.attach(this)
        if (!current()) close()
    }

    private fun current() = generation?.let { publication?.current(it) } == true

    @Synchronized fun capture(stub: Any, ownUid: Boolean, ownerScope: Boolean): CoreFrameObservation? {
        if (state != State.OPEN || !current() || !ownUid || !ownerScope || binder !== stub || frame != null) {
            close(); return null
        }
        return CoreFrameObservation(qualificationBinding, this).also { frame = it }
    }

    @Synchronized fun owns(ticket: CoreFrameObservation) = state == State.OPEN && current() && frame === ticket

    @Synchronized fun succeeded(client: Any) {
        if (this.client === client && state == State.OPEN) { frame?.sink?.set(null); frame = null }
    }

    fun failed(correlation: CoreFailureCorrelation?) {
        val ticket = synchronized(this) {
            if (state != State.OPEN || !current() || correlation == null || correlation.client !== client) null else frame
        } ?: return
        val value = CoreFailureValues.select(ticket.sink.get(), correlation!!) ?: return
        synchronized(this) {
            if (state == State.OPEN && current() && frame === ticket && correlation.client === client) {
                selected = value
                state = State.SELECTED
            }
        }
    }

    @Synchronized fun finish(): CoreFailureSelection? {
        val result = selected.takeIf { state == State.SELECTED && current() }
        close()
        return result
    }

    @Synchronized fun stillCurrent() = current()

    @Synchronized fun close() {
        state = State.CLOSED
        selected = null
        frame?.sink?.set(null)
        frame = null
        publication?.detach(this)
    }
}

/** Only bridges a verified LOCAL synchronous call to service admission; tickets cross the executor explicitly. */
internal object CoreObservationContext {
    private val command = ThreadLocal<CoreCommandObservation>()
    fun present() = command.get() != null
    fun closeCurrent() { command.get()?.close() }
    fun enter(scope: CoreCommandObservation): Boolean {
        val current = command.get()
        if (current != null) { current.close(); return false }
        command.set(scope)
        return true
    }
    fun leave(scope: CoreCommandObservation) { scope.close(); if (command.get() === scope) command.remove() }
    fun bind(publication: CoreObservationPublication, token: Any, client: Any, binder: Any, local: Boolean) {
        command.get()?.bind(publication, token, client, binder, local)
    }
    fun capture(stub: Any, ownUid: Boolean, ownerScope: Boolean) = command.get()?.capture(stub, ownUid, ownerScope)
    fun succeeded(client: Any) { command.get()?.succeeded(client) }
    fun failed(correlation: CoreFailureCorrelation?) { command.get()?.failed(correlation) }
}
