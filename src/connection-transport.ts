import type { WebRTCSession, WebRTCSessionPath } from "./webrtc-session";

export type ConnectionTransportKind = "webrtc" | "direct_tcp" | "access_point" | "i2p";

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
      await session.bridge.close();
      session.control?.close();
      session.channel.close();
      session.pc.close();
    },
  };
}
