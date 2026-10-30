/**
 * Experimental client for the private Mesh Chat Core API.
 *
 * This wraps the versioned frame contract only. It does not authenticate a host
 * endpoint, start a runtime, implement peer retry policy or own a data directory.
 * Until a supported Windows/Android host binding ships, the surface stays
 * experimental and is not a redistribution promise.
 */

import { CoreError, ProtocolError, TimeoutError, TransportClosedError } from "./errors.js";
import { decodeResponse, encodeRequest, type RequestEnvelope } from "./framing.js";
import type { LineTransport } from "./transport.js";
import type {
  Acceptance,
  Acknowledgment,
  Capabilities,
  ConnectionView,
  DiagnosticsView,
  EventPage,
  ProfileView,
  ReceivedPage,
} from "./types.js";

export const DEFAULT_TIMEOUT_MS = 30_000;
export const MAX_BATCH = 128;
export const MAX_DIAGNOSTICS = 256;

export interface CoreClientOptions {
  requestTimeoutMs?: number;
}

export interface RequestOptions {
  idempotencyKey?: string;
  timeoutMs?: number;
}

export class CoreClient {
  readonly #transport: LineTransport;
  readonly #timeoutMs: number;
  #tail: Promise<unknown> = Promise.resolve();
  #capabilities: Capabilities | null = null;
  #sequence = 0;
  #closed = false;

  private constructor(transport: LineTransport, options: CoreClientOptions) {
    this.#transport = transport;
    this.#timeoutMs = options.requestTimeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** Negotiate once, then expose the negotiated capabilities and limits. */
  static async open(transport: LineTransport, options: CoreClientOptions = {}): Promise<CoreClient> {
    const client = new CoreClient(transport, options);
    const capabilities = await client.request<Capabilities>("runtime.capabilities", {});
    client.#capabilities = capabilities;
    return client;
  }

  get capabilities(): Capabilities {
    if (this.#capabilities === null) {
      throw new ProtocolError("client is not negotiated");
    }
    return this.#capabilities;
  }

  get closed(): boolean {
    return this.#closed;
  }

  close(): void {
    if (!this.#closed) {
      this.#closed = true;
      this.#transport.close();
    }
  }

  /**
   * Send one request. Requests are serialized because the host binding reads one
   * frame at a time; results keep their submission order.
   */
  async request<T>(operation: string, params: Record<string, unknown> = {}, options: RequestOptions = {}): Promise<T> {
    if (this.#closed) {
      throw new TransportClosedError();
    }
    const requestId = `client:${(++this.#sequence).toString(36)}`;
    const envelope: RequestEnvelope = { api_version: 1, request_id: requestId, operation, params };
    if (options.idempotencyKey !== undefined) {
      envelope.idempotency_key = options.idempotencyKey;
    }
    const line = encodeRequest(envelope);
    const run = (): Promise<unknown> =>
      this.#exchange(line, requestId, options.timeoutMs ?? this.#timeoutMs);
    const result = this.#tail.then(run, run);
    this.#tail = result.then(
      () => undefined,
      () => undefined,
    );
    return (await result) as T;
  }

  async #exchange(line: string, requestId: string, timeoutMs: number): Promise<unknown> {
    if (this.#closed) {
      throw new TransportClosedError();
    }
    await this.#transport.writeLine(line);
    const response = decodeResponse(await this.#read(requestId, timeoutMs));
    if (response.request_id !== requestId) {
      throw new ProtocolError("response does not correlate with the dispatched request");
    }
    if (!response.ok) {
      throw new CoreError(response.error.code, response.request_id, response.error.retry_after_ms);
    }
    return response.result;
  }

  async #read(requestId: string, timeoutMs: number): Promise<string> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new TimeoutError(requestId)), timeoutMs);
      });
      const line = await Promise.race([this.#transport.readLine(), deadline]);
      if (line === null) {
        this.close();
        throw new TransportClosedError();
      }
      return line;
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    }
  }

  async profileQuery(profile: string): Promise<ProfileView> {
    return this.request<ProfileView>("profile.query", { profile });
  }

  async connectionSnapshot(profile: string, connection: string): Promise<ConnectionView> {
    return this.request<ConnectionView>("connection.snapshot", { profile, connection });
  }

  async received(profile: string, cursor: string | null = null, limit = MAX_BATCH): Promise<ReceivedPage> {
    bounded(limit, MAX_BATCH, "received page");
    return this.request<ReceivedPage>("message.received", { profile, cursor, limit });
  }

  async enqueue(
    profile: string,
    recipient: string,
    text: string,
    idempotencyKey: string,
  ): Promise<Acceptance> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("mutations require a caller-scoped idempotency key");
    }
    return this.request<Acceptance>(
      "message.enqueue",
      { profile, recipient, kind: "text", text },
      { idempotencyKey },
    );
  }

  async pollEvents(profile: string, cursor: string | null = null, limit = MAX_BATCH): Promise<EventPage> {
    bounded(limit, MAX_BATCH, "event page");
    return this.request<EventPage>("events.poll", { profile, cursor, limit });
  }

  async acknowledge(profile: string, cursor: string, idempotencyKey: string): Promise<Acknowledgment> {
    if (idempotencyKey.length < 16) {
      throw new ProtocolError("acknowledgments require a caller-scoped idempotency key");
    }
    return this.request<Acknowledgment>("events.ack", { profile, cursor }, { idempotencyKey });
  }

  async diagnostics(profile: string, limit = MAX_DIAGNOSTICS): Promise<DiagnosticsView> {
    bounded(limit, MAX_DIAGNOSTICS, "diagnostic page");
    return this.request<DiagnosticsView>("diagnostics.query", { profile, limit });
  }
}

function bounded(limit: number, maximum: number, what: string): void {
  if (!Number.isInteger(limit) || limit < 1 || limit > maximum) {
    throw new ProtocolError(`${what} is outside the declared bounds`);
  }
}
