package com.meshchat.runtime

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CoreFailureObservationTest {
    private val binding = "a".repeat(64)
    private fun observation(id: String, operation: String, stage: String = if (operation == "runtime.capabilities") "capabilities" else "tls_context") =
        JSONObject().put("v", 1).put("request_id", id).put("operation", operation).put("error_code", "internal")
            .put("stage", stage).put("category", "unexpected").put("cause", "file_not_found").toString()
    private fun failure(request: JSONObject, code: String = "internal", id: Any = request.get("request_id")) =
        JSONObject().put("api_version", 1).put("request_id", id).put("ok", false)
            .put("error", JSONObject().put("code", code).put("retry_after_ms", JSONObject.NULL))
            .toString().plus("\n").toByteArray()
    private fun success(request: JSONObject) = JSONObject().put("api_version", 1).put("request_id", request.get("request_id"))
        .put("ok", true).put("result", JSONObject().put("api_major", 1)
            .put("operations", JSONArray().put("call.ice_servers"))).toString().plus("\n").toByteArray()
    private fun request() = JSONObject().put("operation", "call.ice_servers").put("params", JSONObject()).put("idempotencyKey", JSONObject.NULL)

    @Test fun actualCapabilitiesFailureSelectsOnlyFirstExistingExchange() { actualFailure("runtime.capabilities", 1) }
    @Test fun actualIceFailureSelectsSecondExistingExchange() { actualFailure("call.ice_servers", 2) }
    private fun actualFailure(operation: String, count: Int) {
        val publication = CoreObservationPublication()
        val scope = CoreCommandObservation(binding)
        val stub = Any()
        val frames = mutableListOf<String>()
        val bytes = mutableListOf<ByteArray>()
        val client = CoreHostClient { frame ->
            val request = JSONObject(String(frame))
            val actual = request.getString("operation")
            frames.add(actual)
            val ticket = scope.capture(stub, true, true)!!
            if (actual == operation) {
                ticket.sink.set(observation(request.getString("request_id"), actual))
                failure(request).also { bytes.add(it.copyOf()) }
            } else success(request)
        }
        assertTrue(CoreObservationContext.enter(scope))
        try {
            scope.bind(publication, publication.token(), client, stub, true)
            try { CoreHostCommands(client).execute("request", request()); fail("Expected internal") }
            catch (error: CoreHostFailure) {
                assertEquals("internal", error.error.getString("code"))
                assertSame(client, error.correlation!!.client)
                assertEquals(operation, error.correlation!!.operation)
                scope.failed(error.correlation)
                val selected = scope.finish()!!
                assertEquals(if (count == 1) "runtime_capabilities" else "ice_servers", selected.operation)
                assertEquals("file_not_found", selected.cause)
                assertFalse(selected.json().toString().contains("host:"))
            }
            assertEquals(count, frames.size)
            assertEquals(listOf("runtime.capabilities", "call.ice_servers").take(count), frames)
            assertEquals(1, bytes.size)
        } finally { CoreObservationContext.leave(scope) }
    }

    @Test fun existingErrorJsonAndReplyBytesStayUntouched() {
        lateinit var original: ByteArray
        var retained = ""
        val client = CoreHostClient { request ->
            val id = JSONObject(String(request)).getString("request_id")
            retained = " { \"api_version\":1, \"request_id\":\"$id\", \"ok\":false, \"error\":{\"code\":\"internal\",\"retry_after_ms\":17,\"outcome\":\"unknown\"} } \n"
            retained.toByteArray().also { original = it }
        }
        try { client.request("call.ice_servers"); fail("Expected failure") }
        catch (error: CoreHostFailure) {
            assertEquals(17, error.error.getInt("retry_after_ms"))
            assertEquals("unknown", error.error.getString("outcome"))
            assertEquals("internal", error.correlation!!.code)
        }
        assertEquals(retained, String(original))
    }

    @Test fun protocolNullIdAndNonInternalCannotMintCorrelation() {
        val cases = listOf<(JSONObject) -> ByteArray>(
            { failure(it, id = JSONObject.NULL) }, { failure(it, id = "foreign") }, { failure(it, "unavailable") },
            { failure(it).dropLast(1).toByteArray() }, { byteArrayOf(0xc3.toByte(), 0x28, 0x0a) },
            { ByteArray(CoreDispatch.MAX_FRAME_BYTES + 1) }, { "{}\n".toByteArray() })
        cases.forEach { produce ->
            val client = CoreHostClient { produce(JSONObject(String(it))) }
            try { client.request("call.ice_servers"); fail("Expected failure") }
            catch (error: CoreHostFailure) { assertNull(error.correlation) }
        }
        for (operation in listOf("settings.update", "message.enqueue")) {
            val client = CoreHostClient { failure(JSONObject(String(it))) }
            try { client.request(operation); fail("Expected failure") }
            catch (error: CoreHostFailure) { assertNull(error.correlation) }
        }
    }

    @Test fun exactFixedDtoRejectsRawMalformedAndMismatchedMetadata() {
        val correlation = CoreFailureCorrelation("host:1", "call.ice_servers", "internal", Any())
        val valid = JSONObject(observation("host:1", "call.ice_servers"))
        assertNotNull(CoreFailureValues.select(valid.toString(), correlation))
        val invalid = listOf(
            valid.toString() + "{}", "not JSON", " ".repeat(1025) + valid,
            JSONObject(valid.toString()).put("v", true).toString(), valid.toString().replace("\"v\":1", "\"v\":1.0"),
            JSONObject(valid.toString()).put("request_id", "other").toString(),
            JSONObject(valid.toString()).put("operation", "runtime.capabilities").toString(),
            JSONObject(valid.toString()).put("error_code", "unavailable").toString(),
            JSONObject(valid.toString()).put("raw", "PRIVATE_CREDENTIAL").toString(),
            JSONObject(valid.toString()).put("stage", "capabilities").toString(),
            JSONObject(valid.toString()).put("category", "response_encoding").toString(),
            JSONObject(valid.toString()).put("category", "invalid_observation").toString(),
            JSONObject(valid.toString()).put("cause", "PRIVATE_PATH").toString())
        invalid.forEach { assertNull(it, CoreFailureValues.select(it, correlation)) }
        assertNull(CoreFailureValues.select(valid.toString(), correlation.copy(code = "unavailable")))
    }

    @Test fun operationStageAndCategoryMatrixIsExact() {
        for ((operation, stages) in CoreFailureValues.stages) for (stage in stages) {
            val value = JSONObject(observation("host:1", operation, stage))
            if (stage == "frame_encode") value.put("category", "response_encoding")
            assertNotNull(CoreFailureValues.select(value.toString(), CoreFailureCorrelation("host:1", operation, "internal", Any())))
            if (stage == "frame_encode") {
                value.put("category", "unexpected")
                assertNull(CoreFailureValues.select(value.toString(), CoreFailureCorrelation("host:1", operation, "internal", Any())))
            }
        }
    }

    @Test fun publicationClientAndStubIdentityCannotBeReusedEvenWhenHostIdRepeats() {
        val publication = CoreObservationPublication()
        val oldClient = Any(); val stub = Any()
        val old = CoreCommandObservation(binding)
        old.bind(publication, publication.token(), oldClient, stub, true)
        val stale = old.capture(stub, true, true)!!
        publication.invalidate()
        stale.sink.set(observation("host:1", "call.ice_servers"))
        old.failed(CoreFailureCorrelation("host:1", "call.ice_servers", "internal", oldClient))
        assertNull(old.finish())
        val currentClient = Any()
        val current = CoreCommandObservation(binding)
        current.bind(publication, publication.token(), currentClient, stub, true)
        current.capture(stub, true, true)!!.sink.set(stale.sink.get())
        current.failed(CoreFailureCorrelation("host:1", "call.ice_servers", "internal", oldClient))
        assertNull(current.finish())
        val beforeRebind = publication.token()
        publication.invalidate()
        val raced = CoreCommandObservation(binding)
        raced.bind(publication, beforeRebind, currentClient, stub, true)
        assertNull(raced.capture(stub, true, true))
    }

    @Test fun foreignProxyWrongStubMissingBindingAndNestedScopesHaveNoAdmission() {
        for (mode in listOf("foreign", "consumer", "proxy", "stub", "binding")) {
            val scope = CoreCommandObservation(if (mode == "binding") "PRIVATE" else binding)
            val publication = CoreObservationPublication(); val stub = Any()
            scope.bind(publication, publication.token(), Any(), stub, mode != "proxy")
            assertNull(scope.capture(if (mode == "stub") Any() else stub, mode != "foreign", mode != "consumer"))
        }
        val scope = CoreCommandObservation(binding)
        assertTrue(CoreObservationContext.enter(scope))
        try {
            assertFalse(CoreObservationContext.enter(CoreCommandObservation(binding)))
            assertNull(scope.capture(Any(), true, true))
        } finally { CoreObservationContext.leave(scope) }
        assertNull(CoreObservationContext.capture(Any(), true, true))
    }

    @Test fun successClearsFrameAndCannotInheritStrayProducerRecord() {
        val publication = CoreObservationPublication(); val client = Any(); val stub = Any()
        val scope = CoreCommandObservation(binding)
        scope.bind(publication, publication.token(), client, stub, true)
        val first = scope.capture(stub, true, true)!!
        first.sink.set(observation("host:1", "runtime.capabilities"))
        scope.succeeded(client)
        assertFalse(first.active())
        scope.capture(stub, true, true)!!
        scope.failed(CoreFailureCorrelation("host:2", "call.ice_servers", "internal", client))
        assertNull(scope.finish())
    }

    @Test fun frameTicketIsExplicitAndWorkerDoesNotInheritCallThreadScope() {
        val publication = CoreObservationPublication(); val client = Any(); val stub = Any()
        val scope = CoreCommandObservation(binding)
        assertTrue(CoreObservationContext.enter(scope))
        try {
            scope.bind(publication, publication.token(), client, stub, true)
            val ticket = CoreObservationContext.capture(stub, true, true)!!
            CoreDispatch({ caller, frame, captured ->
                assertFalse(CoreObservationContext.present())
                assertSame(ticket, captured)
                assertEquals("owner", caller.scope)
                captured!!.sink.set(observation("host:1", "call.ice_servers"))
                frame
            }).use { assertArrayEquals(byteArrayOf(1), it.exchange(CoreCaller.fromUid(1, 1, "host"), byteArrayOf(1), ticket)) }
            scope.failed(CoreFailureCorrelation("host:1", "call.ice_servers", "internal", client))
            assertNotNull(scope.finish())
        } finally { CoreObservationContext.leave(scope) }
    }

    @Test fun timeoutClosesTicketWithoutReleasingOccupiedOrAcceptingLateResult() {
        val publication = CoreObservationPublication(); val client = Any(); val stub = Any()
        val scope = CoreCommandObservation(binding)
        scope.bind(publication, publication.token(), client, stub, true)
        val ticket = scope.capture(stub, true, true)!!
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val finished = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        val dispatch = CoreDispatch({ _, _, captured ->
            entered.countDown()
            release.await()
            captured!!.sink.set(observation("host:1", "call.ice_servers"))
            finished.countDown()
            byteArrayOf(1)
        }, timeoutMillis = 50)
        try {
            val caller = CoreCaller.fromUid(1, 1, "host")
            val first = pool.submit<ByteArray> { dispatch.exchange(caller, byteArrayOf(1), ticket) }
            assertTrue(entered.await(2, TimeUnit.SECONDS))
            assertArrayEquals(CoreDispatch.errorFrame("unavailable"), first.get(2, TimeUnit.SECONDS))
            assertFalse(ticket.active())
            assertArrayEquals(CoreDispatch.errorFrame("resource_exhausted"), dispatch.exchange(caller, byteArrayOf(2)))
            publication.invalidate()
            release.countDown()
            assertTrue(finished.await(2, TimeUnit.SECONDS))
            scope.failed(CoreFailureCorrelation("host:1", "call.ice_servers", "internal", client))
            assertNull(scope.finish())
        } finally { release.countDown(); dispatch.close(); pool.shutdownNow() }
    }

    @Test fun selectionHasOneWinnerAndForeignErrorCannotBorrowIt() {
        val publication = CoreObservationPublication(); val client = Any(); val stub = Any()
        val scope = CoreCommandObservation(binding)
        scope.bind(publication, publication.token(), client, stub, true)
        val ticket = scope.capture(stub, true, true)!!
        ticket.sink.set(observation("host:1", "call.ice_servers"))
        scope.failed(null)
        scope.failed(CoreFailureCorrelation("host:2", "call.ice_servers", "internal", client))
        assertNull(scope.finish())
        ticket.sink.set(observation("host:1", "call.ice_servers"))
        scope.failed(CoreFailureCorrelation("host:1", "call.ice_servers", "internal", client))
        assertNull(scope.finish())
    }
}
