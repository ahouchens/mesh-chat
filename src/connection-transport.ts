import type { WebRTCSession, WebRTCSessionPath } from "./webrtc-session";

export type ConnectionTransportKind = "webrtc" | "direct_tcp" | "access_point" | "i2p";

export interface ConnectionTransportChoice {
  kind: ConnectionTransportKind;
  label: string;
  description: string;
}

export const CONNECTION_TRANSPORT_CHOICES: ConnectionTransportChoice[] = [
  { kind: "direct_tcp", label: "Direct TCP or same network", description: "Signed invitation with a direct participant host, email-assisted or same-network route." },
  { kind: "access_point", label: "Approved access point", description: "Route through an access point already approved by this device." },
  { kind: "webrtc", label: "WebRTC direct or relay", description: "Signed offer/answer over a direct or TURN-relayed DataChannel." },
  { kind: "i2p", label: "I2P access point", description: "Relayed through an I2P Reticulum access point with explicit consent." },
];

export interface ConnectionTransport {
  kind: ConnectionTransportKind;
  path: WebRTCSessionPath;
  close: () => Promise<void>;
}

/**
 * Common boundary for connection transports. WebRTC is the first adapter;
 * direct TCP/access-point/I2P will expose the same shape to the Connect flow.
 */
export function webRTCTransport(session: WebRTCSession): ConnectionTransport {
  return {
    kind: "webrtc",
    path: session.path,
    close: async () => {
      try {
        await session.bridge.close();
      } finally {
        session.control?.close();
        session.channel.close();
        session.pc.close();
      }
    },
  };
}
