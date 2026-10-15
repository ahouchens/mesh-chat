import { deflateSync, inflateSync } from "node:zlib";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  classifyInvitationInput,
  createInvitationQrValue,
  InvitationTransferError,
  MAX_COMPACT_QR_BYTES,
  MAX_INVITATION_DOCUMENT_BYTES,
  normalizeInvitationInput,
} from "./invitation-transfer";

type TestTransform = { mode: "compress" | "decompress" };

function readableBytes(bytes: Uint8Array): ReadableStream<Uint8Array> {
  let delivered = false;
  return {
    getReader: () => ({
      read: async () => {
        if (delivered) return { done: true, value: undefined };
        delivered = true;
        return { done: false, value: bytes };
      },
      cancel: async () => { delivered = true; },
      releaseLock: () => undefined,
    }),
  } as unknown as ReadableStream<Uint8Array>;
}

class TestBlob {
  private readonly bytes: Uint8Array;

  constructor(parts: BlobPart[]) {
    const chunks = parts.map((part) => {
      if (typeof part === "string") return new TextEncoder().encode(part);
      if (part instanceof ArrayBuffer) return new Uint8Array(part);
      if (ArrayBuffer.isView(part)) {
        return new Uint8Array(part.buffer, part.byteOffset, part.byteLength);
      }
      throw new TypeError("Unsupported test Blob part");
    });
    const length = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
    this.bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      this.bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
  }

  stream() {
    return {
      pipeThrough: (transform: TestTransform) => readableBytes(
        new Uint8Array(transform.mode === "compress"
          ? deflateSync(this.bytes)
          : inflateSync(this.bytes)),
      ),
    };
  }
}

class TestCompressionStream {
  readonly mode = "compress" as const;

  constructor(format: string) {
    if (format !== "deflate") throw new TypeError("Unsupported format");
  }
}

class TestDecompressionStream {
  readonly mode = "decompress" as const;

  constructor(format: string) {
    if (format !== "deflate") throw new TypeError("Unsupported format");
  }
}

function installCompressionStreams() {
  vi.stubGlobal("Blob", TestBlob as unknown as typeof Blob);
  vi.stubGlobal("CompressionStream", TestCompressionStream as unknown as typeof CompressionStream);
  vi.stubGlobal("DecompressionStream", TestDecompressionStream as unknown as typeof DecompressionStream);
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/u, "");
}

function realisticWorkspaceInvitation(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const token = (seed: number, length: number) => {
    let state = seed >>> 0;
    let value = "";
    for (let index = 0; index < length; index += 1) {
      state = (state * 1664525 + 1013904223) >>> 0;
      value += alphabet[state % alphabet.length];
    }
    return value;
  };
  const workspaceId = "11111111-1111-4111-8111-111111111111";
  const memberId = "22222222-2222-4222-8222-222222222222";
  const deviceId = "33333333-3333-4333-8333-333333333333";
  const device = {
    created_at: 1_800_000_000,
    destination: token(1, 32),
    device_id: deviceId,
    display_name: "Alex",
    hints: [],
    member_id: memberId,
    public_identity: token(2, 86),
    signature: token(3, 86),
    type: "workspace_device_card",
    v: 1,
    workspace_id: workspaceId,
  };
  const genesis = {
    authority_device_id: deviceId,
    created_at: 1_800_000_000,
    description: "Private field coordination",
    name: "Lakewatcher Operations",
    nonce: token(4, 43),
    owner_device_card: device,
    owner_member_id: memberId,
    signature: token(5, 86),
    type: "workspace_genesis",
    v: 1,
    workspace_id: workspaceId,
  };
  const offeredManifest = {
    authority_destination: device.destination,
    authority_device_id: deviceId,
    created_at: 1_800_000_000,
    description: genesis.description,
    epoch: 1,
    members: [{ devices: [device], display_name: "Alex", member_id: memberId, role: "owner", status: "active" }],
    name: genesis.name,
    policies: { channel_creation: "owner_admins", invitation_requests: "owner_only", posting: "members" },
    previous_manifest_hash: token(6, 64),
    retention_days: 90,
    signature: token(7, 86),
    status: "active",
    type: "workspace_manifest_root",
    v: 1,
    workspace_id: workspaceId,
  };
  return JSON.stringify({
    authority_chain: [],
    created_at: 1_800_000_000,
    expires_at: 1_800_604_800,
    genesis,
    genesis_digest: token(8, 64),
    nonce: token(9, 43),
    offered_manifest: offeredManifest,
    offered_manifest_digest: token(10, 64),
    signature: token(11, 86),
    type: "workspace_invite",
    use_limit: 1,
    v: 1,
    workspace_id: workspaceId,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("invitation transfer classification", () => {
  it.each([
    ["MESHCHAT4:personal", "personal"],
    ["meshchat://invite/personal", "personal"],
    ["MESHWORKSPACE4:workspace", "workspace"],
    ["MESHWORKSPACE4", "workspace"],
    ["meshchat://workspace/workspace", "workspace"],
    ['{"v":4,"type":"email_invitation","purpose":"workspace"}', "workspace"],
    ["MESHWORKSPACEDEVICE1:device", "workspace_device"],
    ["MESHCONNECT1:reply", "connection_reply"],
    ['{ "type": "connection_response", "purpose": "workspace" }', "connection_reply"],
    ["MESHROUTE1:route", "route_update"],
    ['{"type":"route_update","purpose":"workspace"}', "route_update"],
    ["MESHQR1:compact", "compact_qr"],
    ["not an invitation", "unknown"],
  ] as const)("classifies %s as %s", (value, expected) => {
    expect(classifyInvitationInput(value)).toBe(expected);
  });
});

describe("compact invitation QR transport", () => {
  it("round-trips a long workspace invitation without changing its signed text", async () => {
    installCompressionStreams();
    const invitation = `MESHWORKSPACE4:${"abc_DEF-123".repeat(430)}`;

    const qrValue = await createInvitationQrValue(invitation);

    expect(qrValue).toMatch(/^MESHQR1:/);
    expect(new TextEncoder().encode(qrValue!).byteLength).toBeLessThanOrEqual(MAX_COMPACT_QR_BYTES);
    expect(classifyInvitationInput(qrValue!)).toBe("compact_qr");
    await expect(normalizeInvitationInput(qrValue!)).resolves.toBe(invitation);
  });

  it("fits and round-trips a realistic signed workspace document", async () => {
    installCompressionStreams();
    const invitation = realisticWorkspaceInvitation();
    expect(new TextEncoder().encode(invitation).byteLength).toBeGreaterThan(2_200);

    const qrValue = await createInvitationQrValue(invitation);

    expect(qrValue).toMatch(/^MESHQR1:/);
    expect(new TextEncoder().encode(qrValue!).byteLength).toBeLessThanOrEqual(MAX_COMPACT_QR_BYTES);
    await expect(normalizeInvitationInput(qrValue!)).resolves.toBe(invitation);
  });

  it("leaves a short invitation interoperable with older scanners", async () => {
    const invitation = "MESHWORKSPACE4:short_signed_value";

    await expect(createInvitationQrValue(invitation)).resolves.toBe(invitation);
    await expect(normalizeInvitationInput(invitation)).resolves.toBe(invitation);
  });

  it("preserves invisible joiners inside signed invitation text", async () => {
    const invitation = 'MESHWORKSPACE4:{"display_name":"Family 👨‍👩‍👧‍👦","signature":"signed"}';

    await expect(normalizeInvitationInput(`\u200b ${invitation} \u2060`)).resolves.toBe(invitation);
  });

  it("rejects a corrupt compact QR token before decompression", async () => {
    await expect(normalizeInvitationInput("MESHQR1:not+base64"))
      .rejects.toEqual(expect.objectContaining({
        name: InvitationTransferError.name,
        message: "This Mesh Chat QR code is incomplete or damaged.",
      }));
  });

  it("rejects compact QR content that expands beyond the invitation document bound", async () => {
    installCompressionStreams();
    const oversized = new TextEncoder().encode(
      `MESHWORKSPACE4:${"a".repeat(MAX_INVITATION_DOCUMENT_BYTES)}`,
    );
    const qrValue = `MESHQR1:${base64Url(new Uint8Array(deflateSync(oversized)))}`;

    await expect(normalizeInvitationInput(qrValue)).rejects.toThrow(
      "This invitation is too large for Mesh Chat to open safely.",
    );
  });
});
