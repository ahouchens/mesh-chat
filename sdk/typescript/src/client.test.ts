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

test("an unsupported public API major is refused before any command", async () => {
  const transport = new Scripted(success("client:1", { ...CAPABILITIES, api_major: 2 }));
  await assert.rejects(CoreClient.open(transport), ProtocolError);
  assert.equal(transport.written.length, 1);
});

test("relationship and pairing helpers use the declared contract", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { profile: PROFILE, peer: PEER, trust: "approved" }),
    success("client:3", { profile: PROFILE, peer: PEER, trust: "blocked" }),
    success("client:4", {
      profile: PROFILE,
      file: "signed-invitation",
      link: "meshchat://invite/token",
      expires_at: 1767225600,
    }),
    success("client:5", { profile: PROFILE, peer: PEER, trust: "awaiting_consent" }),
  );
  const client = await CoreClient.open(transport);
  assert.equal((await client.approve(PROFILE, PEER)).trust, "approved");
  assert.equal((await client.revoke(PROFILE, PEER)).trust, "blocked");
  assert.equal((await client.pairingCreate(PROFILE)).file, "signed-invitation");
  assert.equal((await client.pairingAccept(PROFILE, "signed-invitation")).trust, "awaiting_consent");
  const requests = transport.written.map((line) => JSON.parse(line));
  assert.equal(requests[1].operation, "peer.approve");
  assert.deepEqual(requests[1].params, { profile: PROFILE, peer: PEER });
  assert.equal("idempotency_key" in requests[1], false);
  assert.equal(requests[4].operation, "peer.pairing_accept");
  assert.deepEqual(requests[4].params, { profile: PROFILE, document: "signed-invitation" });
});

test("pairing acceptance refuses an empty document before dispatch", async () => {
  const transport = new Scripted(success("client:1", CAPABILITIES));
  const client = await CoreClient.open(transport);
  await assert.rejects(() => client.pairingAccept(PROFILE, ""), ProtocolError);
  assert.equal(transport.written.length, 1);
});

test("device link decisions use declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      links: [{ request: "r".repeat(64), state: "pending" }],
    }),
    success("client:3", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      link: "r".repeat(64),
      state: "approved",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal(
    (await client.workspaceDeviceLinks(PROFILE, "w".repeat(64))).links[0].request,
    "r".repeat(64),
  );
  assert.equal(
    (await client.workspaceDeviceLinkApprove(
      PROFILE, "w".repeat(64), "r".repeat(64), "d".repeat(16),
    )).state,
    "approved",
  );
  assert.equal(JSON.parse(transport.written[2]).operation, "workspace.device_link_approve");
});

test("device link submission uses the declared envelope", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      name: "Core",
      state: "linking",
    }),
  );
  const client = await CoreClient.open(transport);
  const submitted = await client.workspaceDeviceLinkSubmit(
    PROFILE, "link-document", "s".repeat(16),
  );
  assert.equal(submitted.state, "linking");
  const sent = JSON.parse(transport.written[1]);
  assert.equal(sent.operation, "workspace.device_link_submit");
  assert.equal(sent.idempotency_key, "s".repeat(16));
});

test("device link helpers use the declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      document: "link-document",
      link: "meshchat://workspace-device/token",
      expires_at: 1,
    }),
    success("client:3", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      name: "Core",
      member_display_name: "Alex",
      device_count: 1,
      expires_at: 1,
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal(
    (await client.workspaceDeviceLinkCreate(PROFILE, "w".repeat(64), "l".repeat(16))).document,
    "link-document",
  );
  assert.equal(
    (await client.workspaceDeviceLinkPreview(PROFILE, "link-document")).device_count,
    1,
  );
  const create = JSON.parse(transport.written[1]);
  const preview = JSON.parse(transport.written[2]);
  assert.equal(create.operation, "workspace.device_link_create");
  assert.equal(preview.operation, "workspace.device_link_preview");
});

test("workspace policy update uses the declared envelope", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel_creation: "owner_and_admins",
      posting: "owner_and_admins",
      invitation_requests: "owner_only",
    }),
  );
  const client = await CoreClient.open(transport);
  const applied = await client.workspacePolicyUpdate(
    PROFILE, "w".repeat(64), "owner_and_admins", "owner_and_admins", "owner_only", "y".repeat(16),
  );
  assert.equal(applied.posting, "owner_and_admins");
  assert.equal(JSON.parse(transport.written[1]).operation, "workspace.policy_update");
});

test("channel transfer helpers use declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      member: "m".repeat(64),
      state: "offered",
    }),
    success("client:3", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      state: "accepted",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal(
    (await client.workspaceChannelTransferOffer(
      PROFILE, "w".repeat(64), "c".repeat(64), "m".repeat(64), "o".repeat(16),
    )).state,
    "offered",
  );
  assert.equal(
    (await client.workspaceChannelTransferAccept(
      PROFILE, "w".repeat(64), "c".repeat(64), "a".repeat(16),
    )).state,
    "accepted",
  );
  assert.equal(JSON.parse(transport.written[1]).operation, "workspace.channel_transfer_offer");
});

test("channel archive uses the declared envelope", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      state: "archived",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal(
    (await client.workspaceChannelArchive(PROFILE, "w".repeat(64), "c".repeat(64), "r".repeat(16))).state,
    "archived",
  );
  const sent = JSON.parse(transport.written[1]);
  assert.equal(sent.operation, "workspace.channel_archive");
  assert.equal(sent.idempotency_key, "r".repeat(16));
});

test("channel edit helpers use the declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      members: ["m".repeat(64)],
    }),
    success("client:3", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      members: ["m".repeat(64)],
    }),
    success("client:4", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      name: "Renamed",
      topic: "Ops",
      visibility: "private",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal(
    (await client.workspaceChannelMembers(PROFILE, "w".repeat(64), "c".repeat(64))).members[0],
    "m".repeat(64),
  );
  await client.workspaceChannelMembersUpdate(
    PROFILE, "w".repeat(64), "c".repeat(64), ["m".repeat(64)], "m".repeat(16),
  );
  const edited = await client.workspaceChannelUpdate(
    PROFILE, "w".repeat(64), "c".repeat(64), "Renamed", "Ops", "e".repeat(16),
  );
  assert.equal(edited.name, "Renamed");
  const update = JSON.parse(transport.written[3]);
  assert.equal(update.operation, "workspace.channel_update");
  assert.equal(update.params.topic, "Ops");
});

test("channel helpers use the declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channels: [{ channel: "c".repeat(64), name: "General", visibility: "public", state: "active" }],
    }),
    success("client:3", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      channel: "c".repeat(64),
      name: "Core Chat",
      visibility: "public",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal((await client.workspaceChannels(PROFILE, "w".repeat(64))).channels[0].name, "General");
  const created = await client.workspaceChannelCreate(
    PROFILE, "w".repeat(64), "Core Chat", "c".repeat(16),
  );
  assert.equal(created.name, "Core Chat");
  const create = JSON.parse(transport.written[2]);
  assert.equal(create.operation, "workspace.channel_create");
  assert.equal(create.idempotency_key, "c".repeat(16));
});

test("workspace review helpers use the declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      members: [{ member: "m".repeat(64), display_name: "Blair", role: "member", status: "active" }],
    }),
    success("client:3", { profile: PROFILE, workspace: "w".repeat(64), decision: "declined" }),
    success("client:4", {
      profile: PROFILE,
      workspace: "w".repeat(64),
      member: "m".repeat(64),
      role: "admin",
    }),
  );
  const client = await CoreClient.open(transport);
  assert.equal((await client.workspaceMembers(PROFILE, "w".repeat(64))).members[0].role, "member");
  assert.equal(
    (await client.workspaceJoinDecline(PROFILE, "w".repeat(64), "r".repeat(64), "d".repeat(16))).decision,
    "declined",
  );
  assert.equal(
    (await client.workspaceMemberRole(PROFILE, "w".repeat(64), "m".repeat(64), "admin", "r".repeat(16))).role,
    "admin",
  );
  const decline = JSON.parse(transport.written[2]);
  const role = JSON.parse(transport.written[3]);
  assert.equal(decline.operation, "workspace.join_decline");
  assert.equal(decline.idempotency_key, "d".repeat(16));
  assert.equal(role.operation, "workspace.member_role");
  assert.deepEqual(role.params, {
    profile: PROFILE,
    workspace: "w".repeat(64),
    member: "m".repeat(64),
    role: "admin",
  });
});

test("workspace preview and join use the declared envelopes", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", {
      profile: PROFILE,
      name: "Core",
      description: "",
      member_count: 1,
      retention_days: 30,
      expires_at: 1,
      requires_i2p_consent: false,
    }),
    success("client:3", { profile: PROFILE, workspace: "w".repeat(64), name: "Core", state: "joining" }),
  );
  const client = await CoreClient.open(transport);
  assert.equal((await client.workspacePreview(PROFILE, "invitation")).name, "Core");
  assert.equal((await client.workspaceJoin(PROFILE, "invitation", "k".repeat(16))).state, "joining");
  const preview = JSON.parse(transport.written[1]);
  const join = JSON.parse(transport.written[2]);
  assert.equal(preview.operation, "workspace.invitation_preview");
  assert.equal("idempotency_key" in preview, false);
  assert.equal(join.operation, "workspace.join");
  assert.equal(join.idempotency_key, "k".repeat(16));
});

test("pairingRequest targets the peer without a caller key", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { profile: PROFILE, peer: PEER, state: "requested" }),
  );
  const client = await CoreClient.open(transport);
  assert.equal((await client.pairingRequest(PROFILE, PEER)).state, "requested");
  const sent = JSON.parse(transport.written[1]);
  assert.equal(sent.operation, "peer.pairing_request");
  assert.deepEqual(sent.params, { profile: PROFILE, peer: PEER });
  assert.equal("idempotency_key" in sent, false);
});

test("stopRuntime asks the owner and never attaches a key", async () => {
  const transport = new Scripted(
    success("client:1", CAPABILITIES),
    success("client:2", { stopping: true, already_stopping: false }),
  );
  const client = await CoreClient.open(transport);
  assert.deepEqual(await client.stopRuntime(), { stopping: true, already_stopping: false });
  const sent = JSON.parse(transport.written[1]);
  assert.equal(sent.operation, "runtime.stop");
  assert.deepEqual(sent.params, {});
  assert.equal("idempotency_key" in sent, false);
});
