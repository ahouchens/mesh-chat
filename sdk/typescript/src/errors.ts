/** Stable error taxonomy returned by the core API or detected locally. */
export class CoreError extends Error {
  constructor(
    readonly code: string,
    readonly requestId: string | null,
    readonly retryAfterMs: number | null,
  ) {
    super(`core api error: ${code}`);
    this.name = "CoreError";
  }
}

/** A response did not match the versioned frame contract. */
export class ProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtocolError";
  }
}

/** The host closed the stream before the response arrived. */
export class TransportClosedError extends Error {
  constructor() {
    super("core api transport closed");
    this.name = "TransportClosedError";
  }
}

/** A request exceeded its declared deadline; the outcome is unknown. */
export class TimeoutError extends Error {
  constructor(readonly requestId: string) {
    super(`core api request timed out: ${requestId}`);
    this.name = "TimeoutError";
  }
}

/** The caller cancelled locally; the remote outcome is unknown. */
export class AbortError extends Error {
  constructor(readonly requestId: string) {
    super(`core api request aborted: ${requestId}`);
    this.name = "AbortError";
  }
}
