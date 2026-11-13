package com.meshchat.runtime.core

import org.junit.Assert.*
import org.junit.Test

class CoreExchangeTransportTest {
    @Test fun exchangesOneBoundedFrameAndDetachDoesNotCallTheHost() {
        var calls = 0
        val transport = CoreExchangeTransport { request ->
            calls++
            assertEquals("{}\n", String(request))
            "{\"ok\":true}\n".toByteArray()
        }
        transport.writeLine("{}\n")
        assertEquals("{\"ok\":true}", transport.readLine())
        transport.close()
        assertEquals(1, calls)
        assertNull(transport.readLine())
    }

    @Test fun byteLimitAndSingleFrameAreCheckedBeforeCallingBinder() {
        val transport = CoreExchangeTransport { throw AssertionError("Invalid request reached Binder") }
        for (line in listOf("{}", "{}\n{}\n", "é".repeat(CoreExchangeTransport.MAX_FRAME_BYTES / 2 + 100) + "\n")) {
            assertTrue(runCatching { transport.writeLine(line) }.exceptionOrNull() is CoreException)
        }
    }

    @Test fun malformedUtf8AndMultipleRepliesCloseTheTransport() {
        for (reply in listOf(byteArrayOf(0xc0.toByte(), 0xaf.toByte(), 10), "{}\n{}\n".toByteArray(),
                             ByteArray(CoreExchangeTransport.MAX_FRAME_BYTES + 1), "{}".toByteArray())) {
            var calls = 0
            val transport = CoreExchangeTransport { calls++; reply }
            assertTrue(runCatching { transport.writeLine("{}\n") }.exceptionOrNull() is CoreException)
            assertTrue(runCatching { transport.writeLine("{}\n") }.exceptionOrNull() is CoreException)
            assertEquals(1, calls)
        }
    }
}
