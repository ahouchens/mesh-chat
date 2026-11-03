package com.meshchat.runtime.core

import java.nio.ByteBuffer
import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction

/** Single-caller bounded exchange transport. Closing detaches only this client. */
class CoreExchangeTransport(private val exchange: (ByteArray) -> ByteArray) : CoreTransport {
    private var reply: String? = null
    private var closed = false

    override fun writeLine(line: String) {
        if (closed) throw CoreException("transport_closed")
        if (reply != null) throw CoreException("protocol")
        val request = try {
            if (!singleFrame(line)) throw IllegalArgumentException()
            val encoded = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .encode(CharBuffer.wrap(line))
            if (encoded.remaining() > MAX_FRAME_BYTES) throw IllegalArgumentException()
            ByteArray(encoded.remaining()).also { encoded.get(it) }
        } catch (_: Exception) { throw CoreException("invalid_request") }
        try {
            val response = exchange(request)
            if (response.isEmpty() || response.size > MAX_FRAME_BYTES) throw IllegalArgumentException()
            val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(response)).toString()
            if (!singleFrame(text)) throw IllegalArgumentException()
            reply = text.dropLast(1)
        } catch (_: Exception) {
            close()
            throw CoreException("transport_closed")
        }
    }

    override fun readLine(): String? = reply.also { reply = null }
    override fun close() { closed = true; reply = null }

    private fun singleFrame(text: String) = text.length in 2..MAX_FRAME_BYTES && text.endsWith('\n') &&
        text.indexOf('\n') == text.lastIndex && !text.contains('\r')

    companion object { const val MAX_FRAME_BYTES = 256 * 1024 }
}
