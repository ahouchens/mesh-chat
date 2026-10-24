import { onServiceEvent, serviceCommand } from "./api";
import type { ServiceEvent } from "./api";

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

export function shouldAutoCloseWebRTCOnboarding(
  phase: string,
  onboarding: string,
  handedOff: boolean,
): boolean {
  if (phase !== "connected" || !handedOff) return false;
  // Review, invitation preparation, and errors need the user's attention.
  return !["preview", "sending", "error"].includes(onboarding);
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
  // Install close handlers before the native attach can finish. Its interface
  // must still be detached if the channel closes while that call is pending.
  const attachment = Promise.resolve().then(() => serviceCommand<AttachResult>("webrtc_attach"));
  let closed = false;
  let unlisten: (() => void) | null = null;
  let closing: Promise<void> | null = null;

  const fail = (reason: unknown) => {
    if (!closed) options.onError?.(reason);
  };

  const close = (): Promise<void> => {
    if (closing) return closing;
    closed = true;
    closing = (async () => {
      try { unlisten?.(); } catch { /* Continue retiring the native interface. */ }
      unlisten = null;
      channel.onmessage = null;
      channel.onclose = null;
      channel.onerror = null;
      try { if (channel.readyState === "open") channel.close(); } catch { /* Already closed. */ }
      const attached = await attachment.catch(() => null);
      if (!attached) return;
      try {
        await serviceCommand("webrtc_detach", { bridge_id: attached.bridge_id });
      } catch {
        // The service may already have retired the bridge.
      }
      options.onClosed?.(attached.bridge_id);
    })();
    return closing;
  };

  const ensureOpen = () => {
    if (closed || channel.readyState !== "open" || options.isCurrent?.() === false) {
      throw new Error("The WebRTC bridge closed before attachment completed.");
    }
  };
  channel.onclose = () => { void close(); };
  channel.onerror = () => { void close(); };
  try {
    const attached = await attachment;
    ensureOpen();
    channel.binaryType = "arraybuffer";
    channel.onmessage = (event) => {
      void channelBytes(event.data)
        .then((packet) => {
          if (!packet || closed) return;
          if (packet.byteLength > attached.max_packet) {
            fail(new Error("The WebRTC packet exceeded the Reticulum MTU."));
            return;
          }
          return serviceCommand<PacketResult>("webrtc_packet", {
            bridge_id: attached.bridge_id,
            data: bytesToBase64(packet),
          });
        })
        .catch(fail);
    };
    const stopListening = await onServiceEvent((event: ServiceEvent) => {
      if (event.event !== "webrtc_packet" || event.bridge_id !== attached.bridge_id) return;
      if (closed || channel.readyState !== "open" || typeof event.data !== "string") return;
      try {
        const packet = base64ToBytes(event.data);
        if (packet.byteLength <= attached.max_packet) channel.send(packet);
      } catch (reason) {
        fail(reason);
      }
    });
    // close() may already have run while native event registration was pending.
    if (closed) stopListening();
    else unlisten = stopListening;
    ensureOpen();

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
