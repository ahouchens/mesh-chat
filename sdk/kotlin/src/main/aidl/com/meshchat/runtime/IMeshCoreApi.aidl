package com.meshchat.runtime;

/**
 * Authenticated local-only core API exchange.
 *
 * The service is protected by the signature permission
 * com.meshchat.runtime.permission.CORE_API. Callers pass one opaque framed
 * request and receive one framed reply; the caller identity is never part of
 * the frame.
 */
interface IMeshCoreApi {
    byte[] exchange(in byte[] frame);
}
