import assert from "node:assert/strict";
import { test } from "node:test";

import { CoreClient } from "./client.js";
import { CoreError, ProtocolError, TimeoutError, TransportClosedError } from "./errors.js";
import { MAX_FRAME_BYTES, decodeResponse, encodeRequest } from "./framing.js";
import type { LineTransport } from "./transport.js";

const PROFILE = "p".repeat(64);
const PEER = "q".repeat(64);
const MESSAGE = "m".repeat(64);

const CAPABILITIES = {
  api_major: 1,
  api_minor: 0,
  stability: "experimental",
  operations: ["runtime.capabilities", "profile.query", "message.received", "events.poll"],
  profiles: [PROFILE],
  limits: { frame_bytes: MAX_FRAME_BYTES, received_scan_count: 128 },
};

function success(requestId: string | null, result: unknown): string {
  return `${JSON.stringify({ api_version: 1, request_id: requestId, ok: true, result })}\n`;
}

function failure(requestId: string | null, code: string, retry: number | null = null): string {
  return `${JSON.stringify({
    api_version: 1,
    request_id: requestId,
    ok: false,
    error: { code, retry_after_ms: retry },
  })}\n`;
}

class Scripted implements LineTransport {
  readonly written: string[] = [];
  closed = false;
  readonly #inbox: (string | null)[];

  constructor(...lines: (string | null)[]) {
    this.#inbox = [...lines];
  }

  async readLine(): Promise<string | null> {
    return this.#inbox.length > 0 ? (this.#inbox.shift() ?? null) : null;
  }

  async writeLine(line: string): Promise<void> {
    this.written.push(line);
  }

  close(): void {
    this.closed = true;
  }
}

class Silent implements LineTransport {
  readonly written: string[] = [];
  closed = false;
  readonly #inbox: (string | null)[];

  constructor(...lines: (string | null)[]) {
    this.#inbox = [...lines];
  }

  async readLine(): Promise<string | null> {
    const value = this.#inbox.shift();
    if (value !== undefined) {
      return value;
    }
    return new Promise<string | null>(() => undefined);
  }

  async writeLine(line: string): Promise<void> {
    this.written.push(line);
  }

  close(): void {
    this.closed = true;
  }
}

function parse(line: string): Record<string, unknown> {
  return JSON.parse(line) as Record<string, unknown>;
}

test("open negotiates capabilities before any other command", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  assert.deepEqual(client.capabilities.operations, CAPABILITIES.operations);
  const first = parse(transport.written[0] ?? "");
  assert.equal(first.api_version, 1);
  assert.equal(first.operation, "runtime.capabilities");
  assert.deepEqual(first.params, {});
});

test("received sends a bounded cursor page and returns the typed result", async () => {
  const page = {
    profile: PROFILE,
    messages: [{ profile: PROFILE, message: MESSAGE, peer: PEER, kind: "text", text: "Hello", state: "delivered", created_at: 1_800_000_000 }],
    next_cursor: null,
    more: false,
  };
  const transport = new Scripted(success("client:1", CAPABILITIES), success("client:2", page));
  const client = await CoreClient.open(transport);
  const result = await client.received(PROFILE, null, 2);
  assert.equal(result.messages.length, 1);
  const sent = parse(transport.written[1] ?? "");
  assert.equal(sent.operation, "message.received");
  assert.deepEqual(sent.params, { profile: PROFILE, cursor: null, limit: 2 });
});

test("limits outside the declared bounds never reach the transport", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  await assert.rejects(client.received(PROFILE, null, 0), ProtocolError);
  await assert.rejects(client.pollEvents(PROFILE, null, 129), ProtocolError);
  await assert.rejects(client.diagnostics(PROFILE, 257), ProtocolError);
  assert.equal(transport.written.length, 1);
});

test("a typed failure becomes a CoreError with code and retry hint", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES), failure("client:2", "resync_required", 1500));
  const client = await CoreClient.open(transport);
  await assert.rejects(client.received(PROFILE), (error: unknown) => {
    assert.ok(error instanceof CoreError);
    assert.equal(error.code, "resync_required");
    assert.equal(error.retryAfterMs, 1500);
    return true;
  });
});

test("an uncorrelated response is a protocol error, not a success", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES), success("client:99", { ok: true }));
  const client = await CoreClient.open(transport);
  await assert.rejects(client.profileQuery(PROFILE), ProtocolError);
});

test("EOF closes the client and fails the outstanding request", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES), null);
  const client = await CoreClient.open(transport);
  await assert.rejects(client.profileQuery(PROFILE), TransportClosedError);
  assert.equal(client.closed, true);
  await assert.rejects(client.profileQuery(PROFILE), TransportClosedError);
});

test("a silent peer times out without closing the transport or resending", async () => {
  const transport = new Silent(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  await assert.rejects(client.request("profile.query", { profile: PROFILE }, { timeoutMs: 10 }), TimeoutError);
  assert.equal(transport.written.length, 2);
  assert.equal(client.closed, false);
});

test("concurrent requests stay serialized and correlated in order", async () => {
  const first = { profile: PROFILE, display_name: "Alex", destination: "a".repeat(32), connections: [] };
  const second = { profile: PROFILE, display_name: "Alex", destination: "a".repeat(32), connections: [] };
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", first),
    success("client:3", second),
  );
  const client = await CoreClient.open(transport);
  const [a, b] = await Promise.all([client.profileQuery(PROFILE), client.profileQuery(PROFILE)]);
  assert.deepEqual(a, first);
  assert.deepEqual(b, second);
  assert.equal(parse(transport.written[1] ?? "").operation, "profile.query");
  assert.equal(parse(transport.written[2] ?? "").operation, "profile.query");
});

test("mutations refuse a missing idempotency key before writing", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  await assert.rejects(client.enqueue(PROFILE, PEER, "Hello", "short"), ProtocolError);
  await assert.rejects(client.acknowledge(PROFILE, "c".repeat(16), "short"), ProtocolError);
  assert.equal(transport.written.length, 1);
});

test("acknowledgments and enqueues carry their caller-scoped key", async () => {
  const accepted = { profile: PROFILE, message: MESSAGE, accepted: true, accepted_at: 1, idempotency_expires_at: 2 };
  const transport = new Scripted(success("client:1", CAPABILITIES), success("client:2", accepted));
  const client = await CoreClient.open(transport);
  await client.enqueue(PROFILE, PEER, "Hello", "enqueue-key-0001");
  const sent = parse(transport.written[1] ?? "");
  assert.equal(sent.idempotency_key, "enqueue-key-0001");
  assert.deepEqual(sent.params, { profile: PROFILE, recipient: PEER, kind: "text", text: "Hello" });
});

test("the frame contract rejects oversized requests and byte-order marks", () => {
  assert.throws(
    () =>
      encodeRequest({
        api_version: 1,
        request_id: "client:1",
        operation: "message.enqueue",
        params: { text: "x".repeat(MAX_FRAME_BYTES) },
      }),
    ProtocolError,
  );
  assert.throws(() => decodeResponse(`\uFEFF${success("client:1", {})}`), ProtocolError);
  assert.throws(() => decodeResponse(JSON.stringify({ api_version: 1, request_id: "client:1", ok: true, result: {} })), ProtocolError);
});

test("malformed JSON and unsupported versions are protocol errors", () => {
  assert.throws(() => decodeResponse("{not json}\n"), ProtocolError);
  assert.throws(
    () => decodeResponse(`${JSON.stringify({ api_version: 2, request_id: "client:1", ok: true, result: {} })}\n`),
    ProtocolError,
  );
  assert.throws(
    () => decodeResponse(`${JSON.stringify({ api_version: 1, request_id: "bad id", ok: true, result: {} })}\n`),
    ProtocolError,
  );
});
