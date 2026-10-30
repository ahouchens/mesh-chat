import assert from "node:assert/strict";
import { test } from "node:test";

import { CoreClient } from "./client.js";
import { AbortError, CoreError, ProtocolError } from "./errors.js";
import type { LineTransport } from "./transport.js";

const PROFILE = "p".repeat(64);
const PEER = "q".repeat(64);

const CAPABILITIES = {
  api_major: 1,
  api_minor: 0,
  stability: "experimental",
  operations: ["runtime.capabilities", "message.received", "message.list", "events.poll", "events.ack"],
  profiles: [PROFILE],
  limits: { frame_bytes: 4194304 },
};

function success(requestId: string | null, result: unknown): string {
  return `${JSON.stringify({ api_version: 1, request_id: requestId, ok: true, result })}\n`;
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

class Slow implements LineTransport {
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

function sent(transport: Scripted | Slow, index: number): Record<string, unknown> {
  return JSON.parse(transport.written[index] ?? "") as Record<string, unknown>;
}

test("abort before dispatch writes nothing", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    client.request("message.list", { profile: PROFILE, cursor: null, limit: 1 }, { signal: controller.signal }),
    AbortError,
  );
  assert.equal(transport.written.length, 1);
});

test("abort during a read rejects without resending or closing", async () => {
  const transport = new Slow(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  const controller = new AbortController();
  const pending = client.request("message.list", { profile: PROFILE, cursor: null, limit: 1 }, {
    signal: controller.signal,
  });
  setTimeout(() => controller.abort(), 10);
  await assert.rejects(pending, AbortError);
  assert.equal(transport.written.length, 2);
  assert.equal(client.closed, false);
});

test("consumer resynchronizes through every snapshot page", async () => {
  const { CoreConsumer } = await import("./consumer.js");
  const page = (message: string, next: string | null, watermark: string | null) => ({
    profile: PROFILE,
    messages: [{ profile: PROFILE, message, recipient: PEER, kind: "text", text: "Hello", state: "queued", created_at: 1 }],
    next_cursor: next,
    events_cursor: watermark,
  });
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", page("m".repeat(64), "cursor-one", null)),
    success("client:3", page("n".repeat(64), null, "cursor-watermark")),
  );
  const client = await CoreClient.open(transport);
  const consumer = new CoreConsumer(client, PROFILE);
  const result = await consumer.resynchronize();
  assert.equal(result.messages.length, 2);
  assert.equal(result.eventsCursor, "cursor-watermark");
  assert.equal(consumer.cursor, "cursor-watermark");
  assert.deepEqual(sent(transport, 2)["params"], { profile: PROFILE, cursor: "cursor-one", limit: 128 });
});

test("polling deduplicates redelivered events and advances the cursor", async () => {
  const { CoreConsumer } = await import("./consumer.js");
  const event = { id: "e".repeat(64), message: "m".repeat(64), type: "message.changed", state: "delivered",
    timestamp: 1, direction: "inbound" };
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { profile: PROFILE, messages: [], next_cursor: null, events_cursor: "start" }),
    success("client:3", { profile: PROFILE, events: [event], next_cursor: "next", more: false }),
    success("client:4", { profile: PROFILE, events: [event], next_cursor: "next", more: false }),
  );
  const client = await CoreClient.open(transport);
  const consumer = new CoreConsumer(client, PROFILE);
  await consumer.resynchronize();
  const first = await consumer.poll();
  assert.equal(first.events.length, 1);
  assert.equal(consumer.cursor, "next");
  const second = await consumer.poll();
  assert.equal(second.events.length, 0);
});

test("a resync_required poll clears the cursor instead of skipping events", async () => {
  const { CoreConsumer } = await import("./consumer.js");
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { profile: PROFILE, messages: [], next_cursor: null, events_cursor: "start" }),
    `${JSON.stringify({ api_version: 1, request_id: "client:3", ok: false,
      error: { code: "resync_required", retry_after_ms: null } })}\n`,
  );
  const client = await CoreClient.open(transport);
  const consumer = new CoreConsumer(client, PROFILE);
  await consumer.resynchronize();
  await assert.rejects(consumer.poll(), (error: unknown) => {
    assert.ok(error instanceof CoreError);
    assert.equal(error.code, "resync_required");
    return true;
  });
  assert.equal(consumer.cursor, null);
});

test("confirm acknowledges exactly the consumer's current cursor", async () => {
  const { CoreConsumer } = await import("./consumer.js");
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { profile: PROFILE, messages: [], next_cursor: null, events_cursor: "cursor-watermark" }),
    success("client:3", { profile: PROFILE, checkpoint: "k".repeat(64), acknowledged: true,
      acknowledged_at: 1, expires_at: 2 }),
  );
  const client = await CoreClient.open(transport);
  const consumer = new CoreConsumer(client, PROFILE);
  await consumer.resynchronize();
  const accepted = await consumer.confirm("ack-key-00000001");
  assert.equal(accepted.checkpoint, "k".repeat(64));
  const ack = sent(transport, 2);
  assert.equal(ack.operation, "events.ack");
  assert.equal(ack.idempotency_key, "ack-key-00000001");
  assert.deepEqual(ack.params, { profile: PROFILE, cursor: "cursor-watermark" });
});

test("confirm refuses to acknowledge an unset cursor", async () => {
  const { CoreConsumer } = await import("./consumer.js");
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  const consumer = new CoreConsumer(client, PROFILE);
  await assert.rejects(consumer.confirm("ack-key-00000001"), ProtocolError);
  assert.equal(transport.written.length, 1);
});
