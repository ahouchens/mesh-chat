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
  options: { onError?: (error: unknown) => void; onClosed?: (bridgeId: string) => void } = {},
): Promise<WebRTCBridge> {
  if (channel.readyState !== "open") {
    throw new Error("The WebRTC DataChannel is not open.");
  }
  const attached = await serviceCommand<AttachResult>("webrtc_attach");
  let closed = false;
  let unlisten: (() => void) | null = null;

  const fail = (reason: unknown) => {
    if (!closed) options.onError?.(reason);
  };

  const close = async () => {
    if (closed) return;
    closed = true;
    unlisten?.();
    unlisten = null;
    try {
      channel.onmessage = null;
      channel.onclose = null;
      channel.onerror = null;
      if (channel.readyState === "open") channel.close();
    } finally {
      try {
        await serviceCommand("webrtc_detach", { bridge_id: attached.bridge_id });
      } catch {
        // The service may already have retired the bridge.
      }
      options.onClosed?.(attached.bridge_id);
    }
  };

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
  channel.onclose = () => { void close(); };
  channel.onerror = () => { void close(); };

  unlisten = await onServiceEvent((event: ServiceEvent) => {
    if (event.event !== "webrtc_packet" || event.bridge_id !== attached.bridge_id) return;
    if (closed || channel.readyState !== "open" || typeof event.data !== "string") return;
    try {
      const packet = base64ToBytes(event.data);
      if (packet.byteLength <= attached.max_packet) channel.send(packet);
    } catch (reason) {
      fail(reason);
    }
  });

  return {
    bridgeId: attached.bridge_id,
    maxPacket: attached.max_packet,
    close,
  };
}
