const COMPACT_QR_PREFIX = "MESHQR1:";

// Keep renderer-side imports aligned with the strict native ingress bound for
// the largest supported family (a direct connection document). The service applies
// each invitation family's smaller authoritative limit after this transport
// layer has recovered the original signed text.
export const MAX_INVITATION_DOCUMENT_BYTES = 2 * 1024 * 1024;

// Version 40-L holds 2,953 bytes in byte mode. Leave room for differences in
// QR encoders and future transport labels instead of rendering a code at the
// absolute edge of the standard.
export const MAX_COMPACT_QR_BYTES = 2_800;
const MAX_COMPACT_TOKEN_CHARS = 8 * 1024;

export type InvitationInputKind =
  | "personal"
  | "workspace"
  | "workspace_device"
  | "connection_reply"
  | "direct_connection"
  | "route_update"
  | "compact_qr"
  | "unknown";

export class InvitationTransferError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvitationTransferError";
  }
}

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function compact(value: string): string {
  // Remove invisible copy artifacts only at the outside of the document.
  // U+200D is also the joiner in many emoji and may occur inside signed JSON;
  // altering it there would invalidate the exact bytes the sender signed.
  return value
    .trim()
    .replace(/^[\u200b\u200c\u200d\u2060\ufeff]+|[\u200b\u200c\u200d\u2060\ufeff]+$/gu, "")
    .trim();
}

function jsonDocumentMarkers(value: string): { type?: string; purpose?: string } {
  if (!value.startsWith("{") || value.length > MAX_INVITATION_DOCUMENT_BYTES) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const record = parsed as Record<string, unknown>;
    return {
      type: typeof record.type === "string" ? record.type : undefined,
      purpose: typeof record.purpose === "string" ? record.purpose : undefined,
    };
  } catch {
    return {};
  }
}

export function classifyInvitationInput(raw: string): InvitationInputKind {
  const value = compact(raw);
  const lower = value.toLowerCase();
  const markers = jsonDocumentMarkers(value);
  if (value.startsWith(COMPACT_QR_PREFIX)) return "compact_qr";
  if (value.startsWith("mesh-direct:") || markers.type === "direct_connection") return "direct_connection";
  if (
    lower.startsWith("meshchat://workspace-device/")
    || /^meshworkspacedevice\d*(?::|$)/i.test(value)
    || markers.type === "workspace_device_link_offer"
  ) return "workspace_device";
  // Connection documents can legitimately carry purpose="workspace". Match
  // their specific signed-document types before the broader workspace marker
  // so raw JSON files and QR values reach the correct verifier.
  if (
    lower.startsWith("meshchat://connect/")
    || /^meshconnect\d*(?::|$)/i.test(value)
    || markers.type === "connection_response"
  ) return "connection_reply";
  if (
    lower.startsWith("meshchat://route/")
    || /^meshroute\d*(?::|$)/i.test(value)
    || markers.type === "route_update"
  ) return "route_update";
  if (
    lower.startsWith("meshchat://workspace/")
    || /^meshworkspace\d*(?::|$)/i.test(value)
    || markers.type === "workspace_invite"
    || markers.purpose === "workspace"
  ) return "workspace";
  if (
    lower.startsWith("meshchat://invite/")
    || /^meshchat\d*(?::|$)/i.test(value)
    || markers.type === "invitation"
    || markers.purpose === "personal"
  ) return "personal";
  return "unknown";
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/u, "");
}

function base64UrlToBytes(value: string): Uint8Array {
  if (!value || value.length > MAX_COMPACT_TOKEN_CHARS || !/^[A-Za-z0-9_-]+$/u.test(value)) {
    throw new InvitationTransferError("This Mesh Chat QR code is incomplete or damaged.");
  }
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  let binary: string;
  try {
    binary = atob(padded);
  } catch {
    throw new InvitationTransferError("This Mesh Chat QR code is incomplete or damaged.");
  }
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function readBounded(
  stream: ReadableStream<Uint8Array>,
  maximum: number,
): Promise<Uint8Array> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximum) {
        await reader.cancel();
        throw new InvitationTransferError("This invitation is too large for Mesh Chat to open safely.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

async function transform(
  bytes: Uint8Array,
  mode: "compress" | "decompress",
  maximum: number,
): Promise<Uint8Array | null> {
  const Constructor = mode === "compress" ? globalThis.CompressionStream : globalThis.DecompressionStream;
  if (typeof Constructor !== "function") return null;
  const input = new Blob([bytes as BlobPart]).stream();
  const output = input.pipeThrough(new Constructor("deflate")) as ReadableStream<Uint8Array>;
  return readBounded(output, maximum);
}

/**
 * Build a QR-safe transport for a raw signed invitation document.
 *
 * Compression changes only the camera transport. Decoding recovers the exact
 * original bytes, which are still verified by the normal invitation parser.
 */
export async function createInvitationQrValue(raw: string): Promise<string | null> {
  const bytes = new TextEncoder().encode(raw);
  if (!bytes.byteLength || bytes.byteLength > MAX_INVITATION_DOCUMENT_BYTES) return null;
  // Preserve QR interoperability with older Mesh Chat builds whenever the
  // original signed JSON comfortably fits a standard code.
  if (bytes.byteLength <= 2_200) return raw;
  try {
    const compressed = await transform(bytes, "compress", MAX_COMPACT_QR_BYTES);
    if (compressed) {
      const encoded = `${COMPACT_QR_PREFIX}${bytesToBase64Url(compressed)}`;
      if (utf8Length(encoded) <= MAX_COMPACT_QR_BYTES) return encoded;
    }
  } catch {
    // Older WebViews can expose the compression constructor without supporting
    // the selected format. A small raw document remains a safe fallback.
  }
  return bytes.byteLength <= MAX_COMPACT_QR_BYTES ? raw : null;
}

/** Expand a compact camera transport into the exact original signed value. */
export async function normalizeInvitationInput(raw: string): Promise<string> {
  const value = compact(raw);
  if (value.startsWith("mesh-direct:")) return value.replace(/\s/gu, "");
  if (!value.startsWith(COMPACT_QR_PREFIX)) return value;
  const compressed = base64UrlToBytes(value.slice(COMPACT_QR_PREFIX.length));
  let expanded: Uint8Array | null;
  try {
    expanded = await transform(compressed, "decompress", MAX_INVITATION_DOCUMENT_BYTES);
  } catch (reason) {
    if (reason instanceof InvitationTransferError) throw reason;
    throw new InvitationTransferError("This Mesh Chat QR code is incomplete or damaged.");
  }
  if (!expanded) {
    throw new InvitationTransferError("This QR invitation needs a newer system WebView. Update it and try again.");
  }
  let decoded: string;
  try {
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(expanded);
  } catch {
    throw new InvitationTransferError("This Mesh Chat QR code contains invalid text.");
  }
  if (!decoded || classifyInvitationInput(decoded) === "unknown") {
    throw new InvitationTransferError("This QR code does not contain a Mesh Chat invitation.");
  }
  return decoded;
}
