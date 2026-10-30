import { afterEach, expect, it, vi } from "vitest";
import { DesktopTransport, type TransportEvent } from "./desktop-transport";

const sdp = "v=0\r\na=fingerprint:sha-256 " + Array(32).fill("AB").join(":") + "\r\n";
const options = { resource: "physical-1", ice: { iceServers: [], iceTransportPolicy: "relay" as const },
  channels: [{ label: "mesh-reticulum", binary: true, ordered: true },
    { label: "meshchat-reconnect", binary: false, ordered: true }] };

class Channel extends EventTarget {
  readyState = "open";
  binaryType = "arraybuffer";
  bufferedAmount = 0;
  sent: unknown[] = [];
  constructor(readonly label: string) { super(); }
  send(value: unknown) { this.sent.push(value); }
  close() { this.readyState = "closed"; this.dispatchEvent(new Event("close")); }
}

class Peer extends EventTarget {
  channels: Channel[] = [];
  signalingState = "stable";
  iceConnectionState = "connected";
  iceGatheringState = "complete";
  localDescription: { sdp: string } | null = null;
  remoteDescription: unknown;
  createOffer = vi.fn(async () => ({ type: "offer", sdp }));
  createAnswer = vi.fn(async () => ({ type: "answer", sdp }));
  async setLocalDescription(value: { sdp: string }) { this.localDescription = value; }
  async setRemoteDescription(value: unknown) { this.remoteDescription = value; }
  createDataChannel(label: string) { const channel = new Channel(label); this.channels.push(channel); return channel; }
  close() { this.signalingState = "closed"; this.iceConnectionState = "closed"; }
}

function fixture(sink: (event: TransportEvent) => boolean = () => true) {
  const peers: Peer[] = [];
  const configurations: RTCConfiguration[] = [];
  const host = new DesktopTransport(sink, (configuration) => {
    configurations.push(configuration);
    const peer = new Peer(); peers.push(peer);
    return peer as unknown as RTCPeerConnection;
  });
  return { host, peers, configurations };
}

afterEach(() => vi.useRealTimers());

it("preserves relay-only configuration and performs no peer retry", async () => {
  const { host, peers, configurations } = fixture();
  expect((await host.createOffer(options)).sdp).toBe(sdp);
  expect(configurations).toEqual([options.ice]);
  expect(peers).toHaveLength(1);
  expect(peers[0].channels.map(channel => channel.label)).toEqual(options.channels.map(channel => channel.label));
  host.close(options.resource);
  host.close(options.resource);
  expect(peers).toHaveLength(1);
  expect(host.inspect(options.resource)).toBeNull();
});

it("bounds live and pending allocations and rejects duplicate resources", async () => {
  const { host, peers } = fixture();
  await Promise.all(Array.from({ length: 16 }, (_, index) => host.createOffer({ ...options, resource: `physical-${index}` })));
  await expect(host.createOffer({ ...options, resource: "overflow" })).rejects.toThrow("capacity");
  await expect(host.createOffer(options)).rejects.toThrow("capacity");
  expect(peers).toHaveLength(16);
  host.close("physical-0");
  await host.createOffer({ ...options, resource: "replacement" });
  host.closeAll();
});

it("cancels gathering and fences late callbacks after resource reuse", async () => {
  vi.useFakeTimers();
  const events: TransportEvent[] = [];
  const { host, peers } = fixture(event => { events.push(event); return true; });
  const pending = host.createOffer(options);
  peers[0].iceGatheringState = "gathering";
  const rejected = expect(pending).rejects.toThrow("retired");
  await vi.advanceTimersByTimeAsync(0);
  host.close(options.resource);
  await rejected;
  await host.createOffer(options);
  const before = events.length;
  peers[0].dispatchEvent(new Event("iceconnectionstatechange"));
  peers[0].channels[0].dispatchEvent(new MessageEvent("message", { data: new Uint8Array([1]).buffer }));
  expect(events).toHaveLength(before);
  expect(host.inspect(options.resource)?.ice_connection_state).toBe("connected");
  host.closeAll();
});

it("bounds packet and control sends independently", async () => {
  const { host, peers } = fixture();
  await host.createOffer(options);
  expect(host.send(options.resource, new Uint8Array(1065))).toBe(false);
  expect(host.send(options.resource, new Uint8Array([1, 2]))).toBe(true);
  peers[0].channels[0].bufferedAmount = 256 * 1024;
  expect(host.send(options.resource, new Uint8Array([1]))).toBe(false);
  expect(host.sendControl(options.resource, "meshchat-reconnect", "control")).toBe(true);
  expect(host.sendControl(options.resource, "media", "control")).toBe(false);
  expect(host.sendControl(options.resource, "meshchat-reconnect", "x".repeat(65537))).toBe(false);
  host.closeAll();
});

it("drops bulk overflow but quarantines lost lifecycle or consent events", async () => {
  let accept = true;
  const { host, peers } = fixture(() => accept);
  await host.createOffer(options);
  accept = false;
  peers[0].channels[0].dispatchEvent(new MessageEvent("message", { data: new Uint8Array([1]).buffer }));
  expect(host.inspect(options.resource)?.packet_drops).toBe(1);
  peers[0].channels[1].dispatchEvent(new MessageEvent("message", { data: "revocation" }));
  expect(host.inspect(options.resource)).toBeNull();
  await expect(host.createOffer({ ...options, resource: "next" })).rejects.toThrow("quarantined");
});

it("rejects unsupported channel purposes before creating a peer", async () => {
  const { host, peers } = fixture();
  await expect(host.createOffer({ ...options, channels: [{ label: "media", binary: true, ordered: true }] })).rejects.toThrow("channels");
  expect(peers).toHaveLength(0);
});

it("expires incomplete gathering and retires the exact allocation", async () => {
  vi.useFakeTimers();
  const { host, peers } = fixture();
  const pending = host.createOffer(options);
  peers[0].iceGatheringState = "gathering";
  const rejected = expect(pending).rejects.toThrow("transport_timeout");
  await vi.advanceTimersByTimeAsync(25000);
  await rejected;
  expect(peers[0].signalingState).toBe("closed");
  expect(host.inspect(options.resource)).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it("redacts browser errors and cancels their deadline", async () => {
  vi.useFakeTimers();
  const { host, peers } = fixture();
  const pending = host.createOffer(options);
  peers[0].createOffer.mockRejectedValue(new Error("private SDP and ICE credential"));
  await expect(pending).rejects.toThrow(/^transport_failed$/);
  expect(host.inspect(options.resource)).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it("quarantines failed native disposal without claiming its capacity is available", async () => {
  const { host, peers } = fixture();
  await host.createOffer(options);
  await host.createOffer({ ...options, resource: "other" });
  peers[0].close = () => { throw new Error("native disposal failed"); };
  expect(() => host.close(options.resource)).toThrow("transport_disposal_failed");
  expect(host.inspect("other")).toBeNull();
  await expect(host.createOffer({ ...options, resource: "replacement" })).rejects.toThrow("quarantined");
});

it("redacts peer construction failures before reserving a resource", async () => {
  const create = vi.fn((): RTCPeerConnection => { throw new Error("private TURN credential"); });
  const host = new DesktopTransport(() => true, create);
  await expect(host.createOffer(options)).rejects.toThrow(/^transport_failed$/);
  expect(host.inspect(options.resource)).toBeNull();
});

it("bounds answer work and cancels all pending operations on retirement", async () => {
  vi.useFakeTimers();
  const { host, peers } = fixture();
  await host.createOffer(options);
  peers[0].setRemoteDescription = vi.fn(() => new Promise<void>(() => {}));
  const pending = Array.from({ length: 16 }, () => host.applyAnswer(options.resource, sdp));
  const rejected = pending.map(operation => expect(operation).rejects.toThrow("transport_retired"));
  await vi.advanceTimersByTimeAsync(0);
  await expect(host.applyAnswer(options.resource, sdp)).rejects.toThrow("transport_capacity");
  expect(peers[0].setRemoteDescription).toHaveBeenCalledTimes(16);
  host.close(options.resource);
  await Promise.all(rejected);
  expect(vi.getTimerCount()).toBe(0);
  await host.createOffer({ ...options, resource: "replacement" });
  host.closeAll();
});

it("accepts only negotiated channel purposes on the answering peer", async () => {
  const events: TransportEvent[] = [];
  const { host, peers } = fixture(event => { events.push(event); return true; });
  await host.acceptOffer(options, sdp);
  expect(peers[0].remoteDescription).toEqual({ type: "offer", sdp });
  const channel = new Channel("mesh-reticulum");
  const unknown = new Channel("media");
  for (const value of [channel, unknown, new Channel("mesh-reticulum")]) {
    const event = Object.assign(new Event("datachannel"), { channel: value });
    peers[0].dispatchEvent(event);
    if (value !== channel) expect(value.readyState).toBe("closed");
  }
  channel.dispatchEvent(new MessageEvent("message", { data: new Uint8Array([1, 2]).buffer }));
  expect(events.at(-1)).toEqual({ event: "message", resource: options.resource, data: "AQI=" });
  host.closeAll();
});
