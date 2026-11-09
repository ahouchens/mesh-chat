package com.meshchat.runtime.core

/**
 * One LF-delimited frame channel. Implementations own the bytes; this client
 * owns no retry policy, socket, runtime or authentication decision.
 */
interface CoreTransport {
    /** Return the next line without its terminator, or null at end of stream. */
    fun readLine(): String?

    /** Write exactly one line, including its terminator. */
    fun writeLine(line: String)

    fun close()
}

/** Typed failure selected by the host, never a policy decision made here. */
class CoreException(
    val code: String,
    val requestId: String? = null,
    val retryAfterMs: Long? = null,
) : Exception("core api error: $code")
