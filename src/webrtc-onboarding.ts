import { onServiceEvent, serviceCommand } from "./api";
import type { ServiceEvent } from "./api";
import { getWebRTCSessions } from "./webrtc-session";

export interface WebRTCBridge {
  readonly bridgeId: string;
  readonly maxPacket: number;
  close: () => Promise<void>;
}

interface AttachResult {
  bridge_id: string;
  max_packet: number;
  state: string;
}

interface PacketResult {
  accepted: number;
}

const MAX_STARTUP_PACKETS = 128;
const MAX_STARTUP_BYTES = MAX_STARTUP_PACKETS * 1064;

export function shouldAutoCloseWebRTCOnboarding(
  phase: string,
  onboarding: string,
  handedOff: boolean,
): boolean {
  if (phase !== "connected" || !handedOff) return false;
  // A connected transport can still be waiting for its first invitation.
  // In particular, unmounting Android's dialog removes its control listener.
  // Only dismiss after a concrete onboarding outcome has been handed off.
  return ["sent", "waiting-approval", "approved", "declined"].includes(onboarding);
}

export function isWindowsWebRTCPlatform(userAgent: string): boolean {
  return /\bWindows\b/i.test(userAgent);
}

export function webRTCWindowsChecklist(role: "offer" | "join" | null): string[] {
  const items = [
    "Set this Wi-Fi network to Private in Windows network settings.",
    "Allow Mesh Chat and msedgewebview2.exe on Private networks for UDP and TCP.",
    "Temporarily disable VPNs, third-party firewalls, and guest/client-isolation networks.",
  ];
  if (role === "offer") {
    items.push("If Android still cannot reach this Windows offer, create the offer on Android and join from Windows instead.");
  } else {
    items.push("If the other device cannot reach this Windows answer, check the same firewall rule before retrying.");
  }
  return items;
}

export function bytesToBase64(value: ArrayBuffer): string {  const bytes = new Uint8Array(value);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

export function base64ToBytes(value: string): ArrayBuffer {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

async function channelBytes(data: unknown): Promise<ArrayBuffer | null> {
  if (data instanceof ArrayBuffer) return data;
  if (ArrayBuffer.isView(data)) {
    return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
  }
  if (typeof Blob !== "undefined" && data instanceof Blob) return data.arrayBuffer();
  return null;
}

/**
 * Attach one open Reticulum DataChannel to the Python bridge.
 *
 * The service owns the Reticulum interface; this module only moves bounded
 * binary packets in both directions. Close the returned bridge when the
 * DataChannel or onboarding session ends.
 */
export async function attachWebRTCBridge(
  channel: RTCDataChannel,
  options: { onError?: (error: unknown) => void; onClosed?: (bridgeId: string) => void; isCurrent?: () => boolean } = {},
): Promise<WebRTCBridge> {
  if (channel.readyState !== "open") {
    throw new Error("The WebRTC DataChannel is not open.");
  }
  let closed = false;
  let unlisten: (() => void) | null = null;
  let closing: Promise<void> | null = null;
  let attached: AttachResult | null = null;
  let attachment: Promise<AttachResult>;
  const pendingInbound: unknown[] = [];
  const pendingOutbound: ServiceEvent[] = [];
  let pendingInboundBytes = 0;
  let pendingOutboundBytes = 0;

  const fail = (reason: unknown) => {
    if (!closed) options.onError?.(reason);
  };

  const close = (): Promise<void> => {
    if (closing) return closing;
    closed = true;
    pendingInbound.length = pendingOutbound.length = 0;
    pendingInboundBytes = pendingOutboundBytes = 0;
    closing = (async () => {
      try { unlisten?.(); } catch { /* Continue retiring the native interface. */ }
      unlisten = null;
      channel.onmessage = null;
      channel.onclose = null;
      channel.onerror = null;
      try { if (channel.readyState === "open") channel.close(); } catch { /* Already closed. */ }
      const native = await attachment.catch(() => null);
      if (!native) return;
      try {
        await serviceCommand("webrtc_detach", { bridge_id: native.bridge_id });
      } catch {
        // The service may already have retired the bridge.
      }
      options.onClosed?.(native.bridge_id);
    })();
    return closing;
  };

  const ensureOpen = () => {
    if (closed || channel.readyState !== "open" || options.isCurrent?.() === false) {
      throw new Error("The WebRTC bridge closed before attachment completed.");
    }
  };
  const overflow = () => {
    fail(new Error("The WebRTC bridge startup packet queue is full."));
    void close();
  };
  const inbound = (data: unknown) => {
    void channelBytes(data).then((packet) => {
      if (!packet || closed || !attached) return;
      if (packet.byteLength > attached.max_packet) {
        fail(new Error("The WebRTC packet exceeded the Reticulum MTU."));
        return;
      }
      return serviceCommand<PacketResult>("webrtc_packet", {
        bridge_id: attached.bridge_id,
        data: bytesToBase64(packet),
      });
    }).catch(fail);
  };
  const outbound = (event: ServiceEvent) => {
    if (!attached || event.bridge_id !== attached.bridge_id || typeof event.data !== "string") return;
    if (closed || channel.readyState !== "open") return;
    try {
      const packet = base64ToBytes(event.data);
      if (packet.byteLength <= attached.max_packet) channel.send(packet);
    } catch (reason) {
      fail(reason);
    }
  };
  // The peer may announce as soon as the DataChannel opens, while native
  // attachment or event registration is still pending. Preserve those bytes.
  channel.binaryType = "arraybuffer";
  channel.onmessage = (event) => {
    if (closed) return;
    if (attached) { inbound(event.data); return; }
    const data: unknown = event.data;
    const size = data instanceof ArrayBuffer || ArrayBuffer.isView(data)
      ? data.byteLength
      : typeof Blob !== "undefined" && data instanceof Blob ? data.size : 0;
    if (!size) return;
    if (pendingInbound.length >= MAX_STARTUP_PACKETS || pendingInboundBytes + size > MAX_STARTUP_BYTES) {
      overflow();
      return;
    }
    pendingInbound.push(data);
    pendingInboundBytes += size;
  };
  channel.onclose = () => { void close(); };
  channel.onerror = () => {
    // An error notification is not itself a channel closure. Retiring an open
    // messaging carrier here turns a recoverable SCTP error into a permanent
    // outage when the peers have no mailbox to negotiate a replacement.
    fail(new Error("The WebRTC DataChannel reported an error."));
    if (channel.readyState === "closing" || channel.readyState === "closed") void close();
  };
  attachment = Promise.resolve().then(async () => {
    // Native attach announces immediately. Its listener must already exist;
    // Android's shared UI poll irreversibly drains each native event batch.
    const stopListening = await onServiceEvent((event: ServiceEvent) => {
      if (closed || event.event !== "webrtc_packet" || typeof event.data !== "string") return;
      if (attached) { outbound(event); return; }
      // Established peers already have their own packet listeners. Their
      // traffic must not consume this attachment's bounded startup queue.
      if (getWebRTCSessions().some((session) => session.bridge.bridgeId === event.bridge_id)) return;
      if (pendingOutbound.length >= MAX_STARTUP_PACKETS || pendingOutboundBytes + event.data.length > MAX_STARTUP_BYTES * 2) {
        overflow();
        return;
      }
      pendingOutbound.push(event);
      pendingOutboundBytes += event.data.length;
    });
    if (closed) stopListening();
    else unlisten = stopListening;
    ensureOpen();
    return serviceCommand<AttachResult>("webrtc_attach");
  });
  try {
    attached = await attachment;
    ensureOpen();
    for (const packet of pendingInbound.splice(0)) inbound(packet);
    for (const event of pendingOutbound.splice(0)) outbound(event);
    pendingInboundBytes = pendingOutboundBytes = 0;

    return {
      bridgeId: attached.bridge_id,
      maxPacket: attached.max_packet,
      close,
    };
  } catch (reason) {
    await close();
    throw reason;
  }
}
